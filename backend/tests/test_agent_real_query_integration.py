"""Agent 接入数据中台真实查询服务后的集成与结构测试。

本文件**不调用真实 LLM、不连真实 PostgreSQL、不发 HTTP**。
真实执行器被替换成 async 替身，所以整套测试在任何机器上都能跑。

真实数据库的冒烟验证单独放在 tests/smoke_agent_real_query.py，
不会被 pytest 收集——默认测试套件不依赖数据库。

替换的替身（classifier / sql_generator / result_explainer 等）直接复用
test_data_query_graph.py 里那几份：它们本来就设计成「绝不碰模型」，
再写一遍只会多出一份会走样的副本。
"""

import ast
import pathlib

import pytest

import app.agent.data_query as data_query_pkg
from app.agent.data_query import query_execution
from app.agent.data_query.constants import (
    MAX_GRAPH_STEPS,
    NODE_EXECUTE_QUERY,
    NODE_FINISH,
    NODE_REPAIR_SQL,
    NODE_VALIDATE_SQL,
)
from app.agent.data_query.graph import (
    build_graph,
    build_mock_data_query_graph,
    get_data_query_graph,
)
from app.agent.data_query.query_execution import (
    CONTRACT_MESSAGE,
    REJECTED_MESSAGE,
    UNAVAILABLE_MESSAGE,
    QueryResultContractError,
    ensure_query_result_contract,
    execute_real_query,
    to_agent_query_result,
)
from app.agent.data_query.query_execution import (
    FAILED_MESSAGE as REAL_QUERY_FAILED_MESSAGE,
)
from app.agent.data_query.result_explanation import (
    MOCK_SOURCE_NOTE,
    build_explanation_prompt,
)
from app.agent.data_query.state import QueryResult
from app.services.safe_query import (
    DatabaseUnavailableError,
    SafeQueryResult,
    UnsafeSqlError,
)
from tests.test_data_query_graph import (
    BAD_SQL,
    QUESTION,
    TREND_SQL,
    FakeChartSuggester,
    FakeClassifier,
    FakeResultExplainer,
    FakeSqlGenerator,
    FakeSqlRepairer,
    SyncGraph,
)

# 一份「真实查询」应有的样子：source 是 postgres，数字是对得上的
TREND_REAL_RESULT: QueryResult = {
    "columns": ["month", "sales_amount"],
    "rows": [
        {"month": 1, "sales_amount": 140892.02},
        {"month": 2, "sales_amount": 125000.00},
    ],
    "row_count": 2,
    "source": "postgres",
}


class FakeQueryExecutor:
    """冒充**真实**执行器：返回 postgres 结果，或抛出指定的异常。

    和 FakeMockExecutor 一样，最要紧的是 calls —— 「不该执行时一次都没执行」
    只能靠记录调用的替身来证明。
    """

    def __init__(self, result: object = None, *, raises: BaseException | None = None):
        self.result = TREND_REAL_RESULT if result is None else result
        self.raises = raises
        self.calls: list[dict] = []

    async def __call__(self, *, sql: str, intent: str):
        self.calls.append({"sql": sql, "intent": intent})
        if self.raises is not None:
            raise self.raises
        return self.result


def graph_with_executor(executor, **overrides):
    """用指定的执行器 + 全套假模型构建图。"""
    kwargs = {
        "classifier": FakeClassifier(),
        "sql_generator": FakeSqlGenerator(),
        "sql_repairer": FakeSqlRepairer(),
        "query_executor": executor,
        "result_explainer": FakeResultExplainer(),
        "chart_suggester": FakeChartSuggester(),
    }
    kwargs.update(overrides)
    return SyncGraph(build_graph(**kwargs))


# ==========================================================================
# 1. 合规的真实查询
# ==========================================================================


def test_compliant_real_query_flows_through_to_a_postgres_result():
    executor = FakeQueryExecutor()
    explainer = FakeResultExplainer()

    result = graph_with_executor(executor, result_explainer=explainer).invoke(
        {"question": QUESTION}
    )

    # 恰好执行一次，且拿到的正是通过 Agent 校验的那条草稿
    assert len(executor.calls) == 1
    assert executor.calls == [{"sql": TREND_SQL, "intent": "trend"}]

    assert result["query_result"]["source"] == "postgres"
    assert result["query_result"]["row_count"] == len(result["query_result"]["rows"]) == 2


def test_postgres_run_reports_a_real_data_event_and_never_says_mock():
    executor = FakeQueryExecutor()

    result = graph_with_executor(executor).invoke({"question": QUESTION})

    assert any("真实数据查询完成" in event for event in result["events"])
    # 真实数据一条「模拟」字样都不该出现
    assert not any("模拟" in event for event in result["events"])


def test_real_answer_does_not_carry_the_mock_source_note():
    executor = FakeQueryExecutor()

    result = graph_with_executor(executor).invoke({"question": QUESTION})

    assert MOCK_SOURCE_NOTE not in result["answer"]
    assert "模拟" not in result["answer"]


def test_chart_suggestion_still_points_at_fields_that_really_exist():
    executor = FakeQueryExecutor()

    result = graph_with_executor(executor).invoke({"question": QUESTION})

    suggestion = result["chart_suggestion"]
    assert suggestion["chart_type"] == "line"
    for field in (suggestion["x_field"], suggestion["y_field"]):
        assert field in result["query_result"]["columns"]


# ==========================================================================
# 2. Agent 校验没过 → 绝不碰数据服务
# ==========================================================================


def test_invalid_draft_never_reaches_the_real_executor():
    executor = FakeQueryExecutor()

    result = graph_with_executor(
        executor,
        sql_generator=FakeSqlGenerator(sql=BAD_SQL),
        sql_repairer=FakeSqlRepairer(sql=BAD_SQL),
    ).invoke({"question": QUESTION})

    assert executor.calls == []
    assert "query_result" not in result
    # 既有行为不变：校验失败仍会尝试修复一次
    assert result["retry_count"] == 1


def test_repair_success_still_reaches_the_real_executor_once():
    executor = FakeQueryExecutor()

    result = graph_with_executor(
        executor,
        sql_generator=FakeSqlGenerator(sql=BAD_SQL),
        sql_repairer=FakeSqlRepairer(),
    ).invoke({"question": QUESTION})

    assert len(executor.calls) == 1
    assert executor.calls[0]["sql"] == TREND_SQL
    assert result["query_result"]["source"] == "postgres"


# ==========================================================================
# 3. 数据服务拒绝（第二层防线真的会拦人）
# ==========================================================================


def test_data_service_rejection_end_is_a_controlled_terminal_state():
    issues = ["查询必须包含 LIMIT，且限制在 1 到 200 行之间。"]
    executor = FakeQueryExecutor(raises=UnsafeSqlError(issues))
    explainer = FakeResultExplainer()
    suggester = FakeChartSuggester()

    result = graph_with_executor(
        executor, result_explainer=explainer, chart_suggester=suggester
    ).invoke({"question": QUESTION})

    assert result["error"] == REJECTED_MESSAGE
    assert "query_result" not in result
    # 只调用了一次：被拒绝后不再重试，也不回头再走一遍 repair_sql
    assert len(executor.calls) == 1
    assert explainer.calls == []
    assert suggester.calls == []


def test_data_service_rejection_does_not_leak_sql_or_issues():
    issues = ["SELECT * 不被允许", "orders.net_amount 相关说明"]
    executor = FakeQueryExecutor(raises=UnsafeSqlError(issues))

    result = graph_with_executor(executor).invoke({"question": QUESTION})

    # 只检查「对外可见」的部分：error 和 events。
    # sql_draft 里当然有 SQL——那是设计（下游 repair_sql 要用），
    # 但它绝不能出现在错误信息和执行轨迹里。
    visible = repr(result["error"]) + repr(result["events"])
    for leak in issues:
        assert leak not in visible
    assert TREND_SQL not in visible
    assert "SELECT" not in visible
    # 事件里只允许出现安全类别（异常类名）
    assert any("UnsafeSqlError" in event for event in result["events"])


def test_rejection_does_not_touch_the_retry_budget():
    """重试额度只属于 repair_sql，执行阶段的失败不该动它。"""
    executor = FakeQueryExecutor(raises=UnsafeSqlError(["x"]))

    result = graph_with_executor(executor).invoke({"question": QUESTION})

    assert result["retry_count"] == 0


# ==========================================================================
# 4. 数据库不可用
# ==========================================================================


def test_database_unavailable_degrades_to_the_documented_message():
    executor = FakeQueryExecutor(raises=DatabaseUnavailableError())
    explainer = FakeResultExplainer()

    result = graph_with_executor(executor, result_explainer=explainer).invoke(
        {"question": QUESTION}
    )

    assert result["error"] == "数据服务暂时不可用，请稍后重试。"
    assert result["error"] == UNAVAILABLE_MESSAGE
    assert explainer.calls == []
    # 后续节点不得把错误覆盖成结论
    assert "answer" not in result
    assert "chart_suggestion" not in result


@pytest.mark.parametrize(
    "leak",
    ["postgresql://", "data_platform", "sup3r-s3cret", "asyncpg", "5432"],
)
def test_unavailable_error_message_never_leaks_connection_details(leak):
    """连接类异常的原文本最容易夹带连接串，这里逐项确认它没漏出去。"""
    executor = FakeQueryExecutor(raises=DatabaseUnavailableError())

    result = graph_with_executor(executor).invoke({"question": QUESTION})

    assert leak not in repr(result)


# ==========================================================================
# 5. 其他执行异常必须脱敏
# ==========================================================================


def test_execution_error_is_sanitized():
    secret = "postgresql://user:secret@host failed key=sk-secret"
    executor = FakeQueryExecutor(raises=RuntimeError(secret))

    result = graph_with_executor(executor).invoke({"question": QUESTION})

    assert result["error"] == REAL_QUERY_FAILED_MESSAGE

    # 密钥、连接串在整份 State 里都不该出现
    blob = repr(result)
    for leak in ("postgresql://", "secret", "sk-secret", "RuntimeError("):
        assert leak not in blob

    # SQL 原文留在 sql_draft 里是设计，但它不能进错误信息和事件
    visible = repr(result["error"]) + repr(result["events"])
    assert TREND_SQL not in visible
    assert "SELECT" not in visible


@pytest.mark.parametrize(
    "exc",
    [TimeoutError("超时"), OSError("连接被拒"), ValueError("乱七八糟")],
)
def test_every_execution_error_degrades_to_the_same_safe_message(exc):
    executor = FakeQueryExecutor(raises=exc)

    result = graph_with_executor(executor).invoke({"question": QUESTION})

    assert result["error"] == REAL_QUERY_FAILED_MESSAGE
    assert f"execute_query：数据查询未完成（{type(exc).__name__}）" in result["events"]


# ==========================================================================
# 6. 结果契约不合法 → fail closed
# ==========================================================================


@pytest.mark.parametrize(
    "bad_result",
    [
        # row_count 与明细长度对不上
        {
            "columns": ["month", "sales_amount"],
            "rows": [{"month": 1, "sales_amount": 1.0}],
            "row_count": 5,
            "source": "postgres",
        },
        # 缺 source
        {"columns": ["month"], "rows": [{"month": 1}], "row_count": 1},
        # 缺 row_count
        {"columns": ["month"], "rows": [{"month": 1}], "source": "postgres"},
        # source 不在约定里
        {"columns": ["month"], "rows": [{"month": 1}], "row_count": 1, "source": "sqlite"},
        # columns 不是字符串列表
        {"columns": [1, 2], "rows": [], "row_count": 0, "source": "postgres"},
        # 整个返回值不是键值结构
        "just a string",
    ],
)
def test_broken_result_contract_fails_closed(bad_result):
    executor = FakeQueryExecutor(result=bad_result)
    explainer = FakeResultExplainer()
    suggester = FakeChartSuggester()

    result = graph_with_executor(
        executor, result_explainer=explainer, chart_suggester=suggester
    ).invoke({"question": QUESTION})

    assert result["error"] == CONTRACT_MESSAGE
    assert "query_result" not in result
    # 不静默补齐、也不继续往下解释
    assert explainer.calls == []
    assert suggester.calls == []
    assert "answer" not in result


def test_contract_violation_does_not_get_silently_corrected():
    """row_count 写错时，绝不能「顺手改成 len(rows)」后放行。"""
    with pytest.raises(QueryResultContractError):
        ensure_query_result_contract(
            {
                "columns": ["month"],
                "rows": [{"month": 1}, {"month": 2}],
                "row_count": 7,
                "source": "postgres",
            }
        )


# ==========================================================================
# 7. 转换与契约函数本身
# ==========================================================================


def test_to_agent_query_result_maps_every_field():
    service_result = SafeQueryResult(
        columns=["month", "sales_amount"],
        rows=[{"month": 1, "sales_amount": 140892.02}],
        row_count=1,
    )

    converted = to_agent_query_result(service_result)

    assert converted == {
        "columns": ["month", "sales_amount"],
        "rows": [{"month": 1, "sales_amount": 140892.02}],
        "row_count": 1,
        "source": "postgres",
    }


def test_to_agent_query_result_rejects_the_wrong_type():
    with pytest.raises(QueryResultContractError):
        to_agent_query_result({"columns": [], "rows": [], "row_count": 0})


def test_conversion_does_not_hand_out_shared_mutable_structures():
    """转出来的结果不能和入参共享同一个 list/dict。"""
    service_result = SafeQueryResult(
        columns=["month"], rows=[{"month": 1}], row_count=1
    )

    converted = to_agent_query_result(service_result)
    converted["rows"][0]["month"] = 999

    assert service_result.rows[0]["month"] == 1


def test_allowed_sources_match_the_state_annotation():
    from typing import get_args

    assert set(get_args(QueryResult.__annotations__["source"])) == set(
        query_execution.ALLOWED_SOURCES
    )


def test_execute_real_query_returns_a_postgres_contract(monkeypatch):
    """真实执行器确实会去调数据服务，并把结果转成 Agent 契约。"""

    async def fake_service(sql: str) -> SafeQueryResult:
        assert sql == TREND_SQL
        return SafeQueryResult(
            columns=["month"], rows=[{"month": 1}], row_count=1
        )

    monkeypatch.setattr(query_execution, "execute_safe_query", fake_service)

    import asyncio

    result = asyncio.run(execute_real_query(sql=TREND_SQL, intent="trend"))

    assert result["source"] == "postgres"
    assert result["row_count"] == 1


# ==========================================================================
# 8. 结构测试
# ==========================================================================

AGENT_PACKAGE_DIR = pathlib.Path(data_query_pkg.__file__).parent

# Agent 不允许直接依赖的模块。数据库只能通过数据中台的服务函数访问；
# HTTP 客户端一律禁止——同进程内没有理由绕道 HTTP 调用自己。
FORBIDDEN_IMPORT_PREFIXES = (
    "sqlalchemy",
    "asyncpg",
    "psycopg2",
    "app.repositories",
    "app.core.config",
    "requests",
    "httpx",
    "urllib",
    "aiohttp",
    "http.client",
)

# 唯一允许接入数据服务的模块
DATA_SERVICE_BRIDGE = "query_execution.py"


def _imported_modules(path: pathlib.Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names |= {alias.name for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


def test_agent_package_can_import_the_data_service_entry():
    """允许的依赖方向：Agent → 数据中台服务函数的公开入口。"""
    from app.services.safe_query import execute_safe_query

    assert query_execution.execute_safe_query is execute_safe_query


def test_agent_never_imports_database_drivers_or_repositories():
    offenders: dict[str, set[str]] = {}
    for path in AGENT_PACKAGE_DIR.glob("*.py"):
        for name in _imported_modules(path):
            if name.startswith(FORBIDDEN_IMPORT_PREFIXES):
                offenders.setdefault(path.name, set()).add(name)
    assert not offenders, f"Agent 引入了不该有的依赖：{offenders}"


def test_agent_never_uses_an_http_client():
    """Agent 与自己同进程，不该通过 HTTP 调用自己的接口。"""
    for path in AGENT_PACKAGE_DIR.glob("*.py"):
        source = path.read_text(encoding="utf-8")
        for marker in ("requests.post", "httpx.", "urllib.request", "aiohttp", "localhost:8000"):
            assert marker not in source, f"{path.name} 里出现了 HTTP 调用痕迹：{marker}"


def test_only_one_module_touches_the_data_service():
    """数据服务的接入点只有一个模块，依赖面越小越好审计。"""
    importers = {
        path.name
        for path in AGENT_PACKAGE_DIR.glob("*.py")
        if any(
            name.startswith("app.services.safe_query")
            for name in _imported_modules(path)
        )
    }
    assert importers == {DATA_SERVICE_BRIDGE}, f"接入点不止一个：{importers}"


def test_production_graph_defaults_to_the_real_executor():
    """默认图必须读真实数据，绝不悄悄回退到 mock。"""
    import inspect

    signature = inspect.signature(build_graph)
    assert signature.parameters["query_executor"].default is execute_real_query


def test_production_graph_actually_calls_the_data_service(monkeypatch):
    """光看默认参数不够，这里让生产接线真正跑一遍。"""
    service_calls: list[str] = []

    async def fake_service(sql: str) -> SafeQueryResult:
        service_calls.append(sql)
        return SafeQueryResult(
            columns=["month", "sales_amount"],
            rows=[
                {"month": 1, "sales_amount": 140892.02},
                {"month": 2, "sales_amount": 125000.00},
            ],
            row_count=2,
        )

    monkeypatch.setattr(query_execution, "execute_safe_query", fake_service)

    # 不传 query_executor → 用默认的真实执行器
    graph = SyncGraph(
        build_graph(
            classifier=FakeClassifier(),
            sql_generator=FakeSqlGenerator(),
            sql_repairer=FakeSqlRepairer(),
            result_explainer=FakeResultExplainer(),
            chart_suggester=FakeChartSuggester(),
        )
    )
    result = graph.invoke({"question": QUESTION})

    assert service_calls == [TREND_SQL]
    assert result["query_result"]["source"] == "postgres"


def test_mock_graph_still_uses_the_mock_executor(monkeypatch):
    """显式工厂才是模拟数据；它绝不能碰数据服务。"""
    service_calls: list[str] = []

    async def fake_service(sql: str) -> SafeQueryResult:  # pragma: no cover
        service_calls.append(sql)
        raise AssertionError("mock 图不该调用数据服务")

    monkeypatch.setattr(query_execution, "execute_safe_query", fake_service)

    graph = SyncGraph(
        build_mock_data_query_graph(
            classifier=FakeClassifier(),
            sql_generator=FakeSqlGenerator(),
            sql_repairer=FakeSqlRepairer(),
            result_explainer=FakeResultExplainer(),
            chart_suggester=FakeChartSuggester(),
        )
    )
    result = graph.invoke({"question": QUESTION})

    assert result["query_result"]["source"] == "mock"
    assert service_calls == []


def test_production_graph_entry_point_is_cached():
    assert get_data_query_graph() is get_data_query_graph()


def test_the_only_back_edge_is_still_repair_sql_to_validate_sql():
    edges = [(edge.source, edge.target) for edge in build_graph().get_graph().edges]
    back_edge = (NODE_REPAIR_SQL, NODE_VALIDATE_SQL)

    assert back_edge in edges
    assert _is_dag(_nodes(), [edge for edge in edges if edge != back_edge])


def test_real_query_path_fits_within_the_step_limit():
    executor = FakeQueryExecutor()

    result = graph_with_executor(executor).invoke({"question": QUESTION})

    assert len(result["events"]) <= MAX_GRAPH_STEPS


def test_repaired_real_query_path_also_fits_within_the_step_limit():
    executor = FakeQueryExecutor()

    result = graph_with_executor(
        executor,
        sql_generator=FakeSqlGenerator(sql=BAD_SQL),
        sql_repairer=FakeSqlRepairer(),
    ).invoke({"question": QUESTION})

    assert len(executor.calls) == 1
    assert len(result["events"]) <= MAX_GRAPH_STEPS


def test_execute_query_is_the_only_touch_point_for_data():
    """执行节点是全图唯一的取数口，且它有且只有一条出边。"""
    edges = [(edge.source, edge.target) for edge in build_graph().get_graph().edges]
    outgoing = [target for source, target in edges if source == NODE_EXECUTE_QUERY]

    assert len(outgoing) == 1
    assert outgoing[0] != NODE_FINISH


# ==========================================================================
# 9. 解释提示词按来源适配
# ==========================================================================


def test_mock_prompt_declares_simulated_data():
    prompt = build_explanation_prompt(source="mock")
    assert "项目内置的模拟数据" in prompt
    assert MOCK_SOURCE_NOTE.split("，")[0] in prompt or "模拟数据" in prompt


def test_real_prompt_does_not_claim_simulated_data():
    prompt = build_explanation_prompt(source="postgres")
    assert "项目内置的模拟数据" not in prompt
    assert "不是模拟数据" in prompt


def test_both_prompts_keep_the_anti_fabrication_rules():
    """来源换了，禁止编造/预测/经营建议这些硬约束一个字都不能松。"""
    for source in ("mock", "postgres"):
        prompt = build_explanation_prompt(source=source)
        for rule in ("严禁编造或推测", "因果关系", "预测", "经营建议", "同比、环比"):
            assert rule in prompt, f"{source} 提示词缺了规则：{rule}"
        assert "{" not in prompt  # 渲染后不该再有占位符


def test_unknown_source_prompt_asserts_nothing_about_provenance():
    prompt = build_explanation_prompt(source="whatever")
    assert "项目内置的模拟数据" not in prompt
    assert "未经确认" in prompt


# ==========================================================================
# 10. 已知差异：Agent 校验器不认 ORDER BY 里的输出别名
# ==========================================================================


def test_agent_validator_still_rejects_an_order_by_alias():
    """记录一个**既有**的两层校验差异，供后续决定是否统一。

    Agent 的 validate_sql 要求每个字段都带表名，因此
        ORDER BY sales_amount DESC
    会被判成「未限定表名」而拒绝；数据服务那一层是明确允许别名引用的
    （别名只能指向已经校验过的投影，绕不过白名单）。

    后果：模型很自然会写出 `ORDER BY sales_amount`，第一次校验会被拒、
    消耗掉唯一一次 repair 机会。

    本任务按边界要求**没有改 Agent 的校验器**（任务书明确要求不得放宽它），
    所以这里把这个行为钉住：哪天决定统一，这条测试会红，提醒改动是有意为之。
    """
    from app.agent.data_query.sql_validation import validate_sql_draft
    from app.agent.data_query.tools import search_datasets, search_metrics

    question = "销售额最高的商品是哪些"
    assets = [
        *search_metrics.invoke({"query": question}),
        *search_datasets.invoke({"query": question}),
    ]

    with_alias = (
        "SELECT products.product_name, SUM(orders.net_amount) AS sales_amount "
        "FROM orders JOIN products ON orders.product_id = products.product_id "
        "GROUP BY products.product_name ORDER BY sales_amount DESC LIMIT 10"
    )
    with_full_expression = with_alias.replace(
        "ORDER BY sales_amount DESC", "ORDER BY SUM(orders.net_amount) DESC"
    )

    assert validate_sql_draft(with_alias, assets)["passed"] is False
    # 换成完整聚合表达式就能过——两条 SQL 的语义完全一样
    assert validate_sql_draft(with_full_expression, assets)["passed"] is True


# --------------------------------------------------------------------------
# 小工具
# --------------------------------------------------------------------------


def _nodes() -> set[str]:
    return set(build_graph().get_graph().nodes)


def _is_dag(nodes: set[str], edges: list[tuple[str, str]]) -> bool:
    """Kahn 拓扑排序：能全部排序完就是无环。"""
    remaining = {node: 0 for node in nodes}
    for _, target in edges:
        remaining[target] = remaining.get(target, 0) + 1

    queue = [node for node, degree in remaining.items() if degree == 0]
    visited = 0

    while queue:
        node = queue.pop()
        visited += 1
        for source, target in edges:
            if source != node:
                continue
            remaining[target] -= 1
            if remaining[target] == 0:
                queue.append(target)

    return visited == len(nodes)
