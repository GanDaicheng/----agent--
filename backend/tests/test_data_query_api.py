"""数据服务接口（POST /api/v1/data/query）的 HTTP 层测试。

通过 monkeypatch 把执行服务替换成替身，完整 pytest 因此不依赖真实 PostgreSQL。
真实数据库的行为由单独的冒烟验证覆盖。

同时回归检查原有的 /、/docs、/chat、/health/db、/api/v1/health 没有退化。
"""

import pytest
from fastapi.testclient import TestClient

from app.api import routes
from app.main import app
from app.services.database_health import DatabaseHealthResult
from app.services.safe_query import (
    MAX_SQL_LENGTH,
    DatabaseUnavailableError,
    QueryExecutionError,
    ResultSerializationError,
    ResultTooLargeError,
    SafeQueryResult,
    UnsafeSqlError,
)

ENDPOINT = "/api/v1/data/query"

# 带标记的 SQL：用于确认响应里绝不会回显 SQL 原文
MARKER = "zzmarkerzz"
SAMPLE_SQL = (
    f"SELECT {MARKER} AS c FROM orders LIMIT 5"
)  # 只作请求体，真正的校验被替换掉了

SAMPLE_RESULT = SafeQueryResult(
    columns=["month", "sales_amount"],
    rows=[{"month": 1, "sales_amount": 103245.36}, {"month": 2, "sales_amount": 110000.0}],
    row_count=2,
)


def patch_service(monkeypatch, *, result=None, error=None):
    """把路由里引用到的 execute_safe_query 换成替身。"""
    calls: list[str] = []

    async def fake_execute(sql: str) -> SafeQueryResult:
        calls.append(sql)
        if error is not None:
            raise error
        return result if result is not None else SAMPLE_RESULT

    # routes 里是 from ... import 进来的，所以要覆盖 routes 模块上的那个名字
    monkeypatch.setattr(routes, "execute_safe_query", fake_execute)
    return calls


# --------------------------------------------------------------------------
# 成功路径
# --------------------------------------------------------------------------


def test_valid_query_returns_200(monkeypatch):
    calls = patch_service(monkeypatch)

    with TestClient(app) as client:
        response = client.post(ENDPOINT, json={"sql": SAMPLE_SQL})

    assert response.status_code == 200
    assert calls == [SAMPLE_SQL]


def test_success_response_matches_the_contract(monkeypatch):
    patch_service(monkeypatch)

    with TestClient(app) as client:
        body = client.post(ENDPOINT, json={"sql": SAMPLE_SQL}).json()

    assert set(body) == {"columns", "rows", "row_count", "source"}
    assert body["columns"] == ["month", "sales_amount"]
    assert body["rows"] == [
        {"month": 1, "sales_amount": 103245.36},
        {"month": 2, "sales_amount": 110000.0},
    ]
    assert body["row_count"] == len(body["rows"]) == 2
    assert body["source"] == "postgres"


def test_success_response_does_not_echo_the_sql(monkeypatch):
    patch_service(monkeypatch)

    with TestClient(app) as client:
        response = client.post(ENDPOINT, json={"sql": SAMPLE_SQL})

    assert MARKER not in response.text


def test_columns_order_matches_row_keys(monkeypatch):
    patch_service(monkeypatch)

    with TestClient(app) as client:
        body = client.post(ENDPOINT, json={"sql": SAMPLE_SQL}).json()

    for row in body["rows"]:
        assert list(row) == body["columns"]


# --------------------------------------------------------------------------
# 请求体校验：422
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"sql": ""},
        {"sql": "x" * (MAX_SQL_LENGTH + 1)},
        {"sql": 123},
        {"sq": "SELECT 1"},
    ],
)
def test_invalid_request_body_returns_422(payload, monkeypatch):
    calls = patch_service(monkeypatch)

    with TestClient(app) as client:
        response = client.post(ENDPOINT, json=payload)

    assert response.status_code == 422
    # 请求体不合法时根本不该走到执行服务
    assert calls == []


@pytest.mark.parametrize(
    "sql",
    [
        "   ",  # 纯空白：能过 Pydantic 的 min_length，由服务层校验拦下
        "DELETE FROM orders",
        "SELECT * FROM orders LIMIT 5",
        "SELECT orders.order_id FROM orders",
        "SELECT pg_sleep(10) AS v FROM orders LIMIT 5",
        "SELECT t.table_name FROM information_schema.tables AS t LIMIT 5",
    ],
)
def test_unsafe_sql_is_rejected_by_the_real_validator(sql):
    """不替换执行服务，走真实校验链路。

    这些 SQL 在 AST 校验阶段就被拒绝，根本不会连数据库，
    所以这个测试既验证了端到端的拒绝行为，也不需要真实 PostgreSQL。
    """
    with TestClient(app) as client:
        response = client.post(ENDPOINT, json={"sql": sql})

    assert response.status_code == 422
    detail = response.json()["detail"]
    assert detail["message"] == "SQL 未通过安全校验。"
    assert detail["issues"]
    assert sql not in response.text


# --------------------------------------------------------------------------
# 受控异常 → 状态码
# --------------------------------------------------------------------------


def test_unsafe_sql_returns_422_with_fixed_issues(monkeypatch):
    issues = ["仅允许执行单条 SELECT 查询。"]
    patch_service(monkeypatch, error=UnsafeSqlError(issues))

    with TestClient(app) as client:
        response = client.post(ENDPOINT, json={"sql": SAMPLE_SQL})

    assert response.status_code == 422
    detail = response.json()["detail"]
    assert detail["message"] == "SQL 未通过安全校验。"
    assert detail["issues"] == issues
    assert MARKER not in response.text


def test_database_unavailable_returns_503(monkeypatch):
    patch_service(monkeypatch, error=DatabaseUnavailableError())

    with TestClient(app) as client:
        response = client.post(ENDPOINT, json={"sql": SAMPLE_SQL})

    assert response.status_code == 503
    assert MARKER not in response.text


def test_query_execution_error_returns_400(monkeypatch):
    patch_service(monkeypatch, error=QueryExecutionError())

    with TestClient(app) as client:
        response = client.post(ENDPOINT, json={"sql": SAMPLE_SQL})

    assert response.status_code == 400
    assert MARKER not in response.text


@pytest.mark.parametrize(
    "error",
    [ResultSerializationError(), ResultTooLargeError()],
)
def test_internal_result_errors_return_500(error, monkeypatch):
    patch_service(monkeypatch, error=error)

    with TestClient(app) as client:
        response = client.post(ENDPOINT, json={"sql": SAMPLE_SQL})

    assert response.status_code == 500


def test_missing_database_configuration_returns_500(monkeypatch):
    from app.core.exceptions import ConfigurationError

    patch_service(monkeypatch, error=ConfigurationError("缺少 DATABASE_URL。"))

    with TestClient(app) as client:
        response = client.post(ENDPOINT, json={"sql": SAMPLE_SQL})

    assert response.status_code == 500


@pytest.mark.parametrize(
    "error",
    [
        UnsafeSqlError(["仅允许执行单条 SELECT 查询。"]),
        DatabaseUnavailableError(),
        QueryExecutionError(),
        ResultSerializationError(),
        ResultTooLargeError(),
    ],
)
def test_error_responses_never_leak_secrets(error, monkeypatch):
    """所有错误响应都不得出现连接串、密码、密钥或表结构细节。"""
    patch_service(monkeypatch, error=error)

    with TestClient(app) as client:
        response = client.post(ENDPOINT, json={"sql": SAMPLE_SQL})

    text = response.text.lower()
    assert "postgresql" not in text
    assert "asyncpg" not in text
    assert "password" not in text
    assert "secret" not in text
    assert MARKER not in response.text
    assert "traceback" not in text


# --------------------------------------------------------------------------
# OpenAPI
# --------------------------------------------------------------------------


def test_endpoint_is_documented():
    with TestClient(app) as client:
        schema = client.get("/openapi.json").json()

    assert ENDPOINT in schema["paths"]
    post = schema["paths"][ENDPOINT]["post"]
    ok_schema = post["responses"]["200"]["content"]["application/json"]["schema"]
    assert ok_schema["$ref"].endswith("SafeQueryResponse")
    # 受控失败的状态码也要出现在文档里
    assert {"400", "422", "503"} <= set(post["responses"])


def test_request_and_response_models_are_in_the_schema():
    with TestClient(app) as client:
        schema = client.get("/openapi.json").json()

    components = schema["components"]["schemas"]
    assert "SafeQueryRequest" in components
    assert "SafeQueryResponse" in components

    request_fields = components["SafeQueryRequest"]["properties"]
    assert "sql" in request_fields
    assert request_fields["sql"]["maxLength"] == MAX_SQL_LENGTH

    response_fields = components["SafeQueryResponse"]["properties"]
    assert set(response_fields) == {"columns", "rows", "row_count", "source"}


# --------------------------------------------------------------------------
# 原有接口不退化
# --------------------------------------------------------------------------


def test_docs_page_is_available():
    with TestClient(app) as client:
        assert client.get("/docs").status_code == 200


def test_root_descriptor_is_unchanged():
    with TestClient(app) as client:
        response = client.get("/")

    assert response.status_code == 200
    assert response.json() == {
        "service": "data-platform-agent-backend",
        "docs": "/docs",
        "health": "/api/v1/health",
    }


def test_chat_endpoint_still_works_without_calling_a_real_model(monkeypatch):
    """只验证路由与请求/响应模型没坏，不触达真实模型。"""
    monkeypatch.setattr(routes, "run_agent", lambda messages: "替身回复")

    with TestClient(app) as client:
        response = client.post("/chat", json={"messages": [{"role": "user", "content": "你好"}]})

    assert response.status_code == 200
    assert response.json() == {"reply": "替身回复"}


def test_health_endpoints_are_unchanged(monkeypatch):
    async def connected() -> DatabaseHealthResult:
        return DatabaseHealthResult(connected=True)

    monkeypatch.setattr(routes, "check_database", connected)

    with TestClient(app) as client:
        assert client.get("/api/v1/health").json() == {
            "status": "ok",
            "service": "backend",
            "database": "connected",
        }
        assert client.get("/health/db").json() == {"status": "ok", "database": "connected"}
