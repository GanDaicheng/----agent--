import json

import pytest
from pydantic import ValidationError

from app.agent.business_analysis.schemas import (
    AnalysisEvent,
    BusinessAnalysisRequest,
    ToolResult,
)


def test_request_strips_message_and_requires_thread_id():
    request = BusinessAnalysisRequest(thread_id="thread-1", message="  分析销售额  ")

    assert request.message == "分析销售额"


def test_request_rejects_blank_message():
    with pytest.raises(ValidationError):
        BusinessAnalysisRequest(thread_id="thread-1", message="   ")


def test_public_event_never_contains_raw_sql():
    event = AnalysisEvent.tool_completed(
        tool="analyze_business_data",
        summary="返回趋势摘要",
        metadata={"sql": "SELECT * FROM orders"},
    )

    payload = event.to_sse_payload()

    assert "SELECT" not in payload
    assert "orders" not in payload
    assert "返回趋势摘要" in payload


def test_tool_result_serializes_only_json_safe_fields():
    result = ToolResult(
        status="ok",
        summary="查询完成",
        data={"row_count": 2},
        sources=[],
        artifact_id=None,
    )

    assert json.loads(result.model_dump_json()) == {
        "status": "ok",
        "summary": "查询完成",
        "data": {"row_count": 2},
        "sources": [],
        "artifact_id": None,
    }
