from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from app.agent.business_analysis.schemas import BusinessAnalysisRequest
from app.services.business_analysis_runner import (
    BusinessAnalysisBusyError,
    run_business_analysis,
)


class FakeConnection:
    def __init__(self):
        self.statements = []

    async def execute(self, statement, params):
        self.statements.append((statement, params))


class FakeAgent:
    async def astream_events(self, payload, config, version):
        assert payload["messages"][0]["content"] == "分析销售额"
        assert config["configurable"]["thread_id"] == "thread-1"
        assert version == "v2"
        yield {"event": "on_tool_start", "name": "analyze_business_data"}
        yield {
            "event": "on_tool_end",
            "name": "analyze_business_data",
            "data": {"output": {"summary": "销售额下降"}},
        }
        yield {
            "event": "on_chat_model_stream",
            "data": {"chunk": SimpleNamespace(content="## 核心结论\n销售额下降")},
        }


@pytest.mark.anyio
async def test_runner_emits_start_tool_report_and_complete_events():
    request = BusinessAnalysisRequest(thread_id="thread-1", message="分析销售额")
    connection = FakeConnection()
    events = [
        event
        async for event in run_business_analysis(
            request,
            agent=FakeAgent(),
            connection=connection,
        )
    ]

    assert [event.type for event in events] == [
        "run_started",
        "tool_started",
        "tool_completed",
        "report_delta",
        "run_completed",
    ]
    assert any("UPDATE business_analysis_runs" in str(statement) for statement, _ in connection.statements)


@pytest.mark.anyio
async def test_same_thread_cannot_start_two_runs():
    gate = asyncio.Event()

    class BlockingAgent:
        async def astream_events(self, payload, config, version):
            yield {"event": "on_tool_start", "name": "analyze_business_data"}
            await gate.wait()

    request = BusinessAnalysisRequest(thread_id="same", message="分析销售额")
    first = asyncio.create_task(
        _collect(
            run_business_analysis(
                request,
                agent=BlockingAgent(),
                connection=FakeConnection(),
            )
        )
    )
    await asyncio.sleep(0)

    with pytest.raises(BusinessAnalysisBusyError):
        await _collect(
            run_business_analysis(
                request,
                agent=BlockingAgent(),
                connection=FakeConnection(),
            )
        )

    gate.set()
    await first


@pytest.mark.anyio
async def test_runner_stops_when_tool_call_limit_is_reached(monkeypatch):
    class ManyToolsAgent:
        async def astream_events(self, payload, config, version):
            for _ in range(2):
                yield {"event": "on_tool_start", "name": "analyze_business_data"}

    monkeypatch.setattr(
        "app.services.business_analysis_runner.get_settings",
        lambda: SimpleNamespace(
            business_analysis_max_steps=12,
            business_analysis_max_tool_calls=1,
            business_analysis_run_timeout_seconds=90,
            business_analysis_context_char_limit=12000,
        ),
    )
    request = BusinessAnalysisRequest(thread_id="limited", message="分析销售额")
    events = [
        event
        async for event in run_business_analysis(
            request,
            agent=ManyToolsAgent(),
            connection=FakeConnection(),
        )
    ]

    assert events[-1].type == "error"
    assert events[-1].error_code == "AGENT_RUN_LIMIT_REACHED"


async def _collect(events):
    return [event async for event in events]
