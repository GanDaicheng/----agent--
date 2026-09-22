"""统一健康检查接口的自动化测试。

测试不依赖真实 PostgreSQL：数据库探测逻辑通过 monkeypatch 替换掉，
这样在任何机器上（包括没有启动容器的 CI）都能稳定跑过。
"""

from contextlib import asynccontextmanager

from fastapi.testclient import TestClient

from app.api import routes
from app.main import app
from app.services import database_health
from app.services.database_health import DatabaseHealthResult

EXPECTED_ROOT = {
    "service": "data-platform-agent-backend",
    "docs": "/docs",
    "health": "/api/v1/health",
}


def test_v1_health_is_200_when_database_is_connected(monkeypatch):
    async def connected() -> DatabaseHealthResult:
        return DatabaseHealthResult(connected=True)

    # 覆盖 routes 模块里引用到的那个名字（它是 from ... import 进来的）
    monkeypatch.setattr(routes, "check_database", connected)

    with TestClient(app) as client:
        response = client.get("/api/v1/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "backend",
        "database": "connected",
    }


def test_v1_health_is_503_when_database_is_unavailable(monkeypatch):
    async def unavailable() -> DatabaseHealthResult:
        return DatabaseHealthResult(
            connected=False,
            error_type="ConnectionRefusedError",
            message="无法连接数据库，请确认 PostgreSQL 容器已启动且 DATABASE_URL 配置正确。",
        )

    monkeypatch.setattr(routes, "check_database", unavailable)

    with TestClient(app) as client:
        response = client.get("/api/v1/health")

    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "error"
    assert body["service"] == "backend"
    assert body["database"] == "unavailable"
    assert "password" not in response.text.lower()


def test_v1_health_does_not_leak_credentials(monkeypatch):
    """不走替身，真实跑一遍 check_database 的异常清洗逻辑。

    驱动抛出的异常原文里往往带着完整连接串（含密码）。这里故意伪造一个，
    确认接口层只回显异常类名和通用说明，绝不把密码透出去。
    """
    secret = "sup3r-s3cret-password"

    @asynccontextmanager
    async def broken_connection():
        raise OSError(
            "could not connect: "
            f"postgresql+asyncpg://data_platform:{secret}@localhost:5432/data_platform"
        )
        yield  # pragma: no cover  —— 只为满足 async 生成器语法

    monkeypatch.setattr(database_health, "get_connection", broken_connection)

    with TestClient(app) as client:
        response = client.get("/api/v1/health")

    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "error"
    assert body["service"] == "backend"
    assert body["database"] == "unavailable"
    assert body["error_type"] == "OSError"

    # 敏感信息一个都不能出现
    assert secret not in response.text
    assert "password" not in response.text.lower()
    assert "postgresql+asyncpg" not in response.text


def test_root_returns_service_descriptor():
    """根路径改为返回服务说明 JSON，不再读取已迁移的旧静态页面。"""
    with TestClient(app) as client:
        response = client.get("/")

    assert response.status_code == 200
    assert response.json() == EXPECTED_ROOT


def test_legacy_health_db_still_works(monkeypatch):
    """/health/db 是宿主机开发用的探针，本次改动不得让它退化。"""

    async def connected() -> DatabaseHealthResult:
        return DatabaseHealthResult(connected=True)

    monkeypatch.setattr(routes, "check_database", connected)

    with TestClient(app) as client:
        response = client.get("/health/db")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "connected"}


def test_legacy_health_db_reports_503_when_unavailable(monkeypatch):
    async def unavailable() -> DatabaseHealthResult:
        return DatabaseHealthResult(
            connected=False,
            error_type="ConnectionRefusedError",
            message="无法连接数据库，请确认 PostgreSQL 容器已启动且 DATABASE_URL 配置正确。",
        )

    monkeypatch.setattr(routes, "check_database", unavailable)

    with TestClient(app) as client:
        response = client.get("/health/db")

    assert response.status_code == 503
    assert response.json()["status"] == "error"
    assert response.json()["database"] == "unavailable"
