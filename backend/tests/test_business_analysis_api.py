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
