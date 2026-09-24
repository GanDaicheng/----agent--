from collections.abc import AsyncIterator

from fastapi.testclient import TestClient

from app.agent.business_analysis.schemas import AnalysisEvent
from app.main import app


async def fake_events(_request) -> AsyncIterator[AnalysisEvent]:
    yield AnalysisEvent.run_started("run-1")
    yield AnalysisEvent.status("正在分析")
    yield AnalysisEvent.run_completed("run-1", "report-1")


def test_business_analysis_endpoint_streams_sse(monkeypatch):
    monkeypatch.setattr(
        "app.api.business_analysis_routes.run_business_analysis",
        fake_events,
    )

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/agent/business-analysis/runs",
            json={"thread_id": "thread-1", "message": "分析销售额"},
        )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert "event: run_started" in response.text
    assert '"run_id":"run-1"' in response.text
    assert "event: run_completed" in response.text


def test_business_analysis_endpoint_rejects_blank_message():
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/agent/business-analysis/runs",
            json={"thread_id": "thread-1", "message": "   "},
        )

    assert response.status_code == 422


def test_business_analysis_endpoint_rejects_missing_thread_id():
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/agent/business-analysis/runs",
            json={"message": "分析销售额"},
        )

    assert response.status_code == 422


def test_business_analysis_threads_returns_public_history(monkeypatch):
    async def fake_threads(_thread_id):
        return [{"id": "run-1", "status": "completed"}]

    monkeypatch.setattr(
        "app.api.business_analysis_routes.load_thread_history",
        fake_threads,
    )
    with TestClient(app) as client:
        response = client.get(
            "/api/v1/agent/business-analysis/threads/thread-1"
        )

    assert response.status_code == 200
    assert response.json() == [{"id": "run-1", "status": "completed"}]


def test_business_analysis_preferences_can_be_read_and_written(monkeypatch):
    async def fake_load(_user_id):
        return {"currency_unit": "万元"}

    async def fake_save(_user_id, _key, _value):
        return None

    monkeypatch.setattr(
        "app.api.business_analysis_routes.load_user_preferences_api",
        fake_load,
    )
    monkeypatch.setattr(
        "app.api.business_analysis_routes.save_user_preference_api",
        fake_save,
    )
    with TestClient(app) as client:
        read_response = client.get(
            "/api/v1/agent/business-analysis/preferences/user-1"
        )
        write_response = client.put(
            "/api/v1/agent/business-analysis/preferences/user-1",
            json={"key": "currency_unit", "value": "万元"},
        )

    assert read_response.status_code == 200
    assert read_response.json() == {"currency_unit": "万元"}
    assert write_response.status_code == 204
