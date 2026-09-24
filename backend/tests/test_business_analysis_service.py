from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest

from app.agent.business_analysis.schemas import BusinessAnalysisRequest
from app.core.exceptions import ConfigurationError
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
async def test_runner_exposes_a_specific_event_when_model_configuration_is_missing(monkeypatch):
    @asynccontextmanager
    async def unavailable_agent(_agent):
        raise ConfigurationError("缺少 OPENAI_API_KEY")
        yield None

    monkeypatch.setattr(
        "app.services.business_analysis_runner._agent_scope",
        unavailable_agent,
    )

    events = [
        event
        async for event in run_business_analysis(
            BusinessAnalysisRequest(thread_id="missing-model-config", message="分析销售额"),
            connection=FakeConnection(),
        )
    ]

    assert [event.type for event in events] == ["error"]
    assert events[0].error_code == "AGENT_CONFIGURATION_ERROR"


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


@pytest.mark.anyio
async def test_runner_marks_timed_out_runs_with_a_safe_error(monkeypatch):
    class SlowAgent:
        async def astream_events(self, payload, config, version):
            await asyncio.sleep(0.02)
            if False:
                yield {}

    monkeypatch.setattr(
        "app.services.business_analysis_runner.get_settings",
        lambda: SimpleNamespace(
            business_analysis_max_steps=12,
            business_analysis_max_tool_calls=8,
            business_analysis_run_timeout_seconds=0.001,
            business_analysis_context_char_limit=12000,
        ),
    )
    events = [
        event
        async for event in run_business_analysis(
            BusinessAnalysisRequest(thread_id="timed-out", message="分析销售额"),
            agent=SlowAgent(),
            connection=FakeConnection(),
        )
    ]

    assert events[-1].type == "error"
    assert events[-1].error_code == "AGENT_RUN_TIMEOUT"


@pytest.mark.anyio
async def test_streamed_tokens_do_not_consume_agent_step_budget(monkeypatch):
    class StreamingAgent:
        async def astream_events(self, payload, config, version):
            yield {"event": "on_chat_model_start", "name": "ChatOpenAI"}
            for token in ("核", "心", "结", "论"):
                yield {
                    "event": "on_chat_model_stream",
                    "data": {"chunk": SimpleNamespace(content=token)},
                }

    monkeypatch.setattr(
        "app.services.business_analysis_runner.get_settings",
        lambda: SimpleNamespace(
            business_analysis_max_steps=1,
            business_analysis_max_tool_calls=8,
            business_analysis_run_timeout_seconds=90,
            business_analysis_context_char_limit=12000,
        ),
    )
    events = [
        event
        async for event in run_business_analysis(
            BusinessAnalysisRequest(thread_id="streamed", message="分析销售额"),
            agent=StreamingAgent(),
            connection=FakeConnection(),
        )
    ]

    assert events[-1].type == "run_completed"
    assert "".join(event.content or "" for event in events if event.type == "report_delta") == "核心结论"


@pytest.mark.anyio
async def test_nested_tool_model_calls_do_not_consume_supervisor_step_budget(monkeypatch):
    class NestedModelAgent:
        async def astream_events(self, payload, config, version):
            for _ in range(3):
                yield {
                    "event": "on_chat_model_start",
                    "metadata": {"langgraph_node": "generate_sql"},
                }
            yield {
                "event": "on_chat_model_start",
                "metadata": {"langgraph_node": "model"},
            }

    monkeypatch.setattr(
        "app.services.business_analysis_runner.get_settings",
        lambda: SimpleNamespace(
            business_analysis_max_steps=1,
            business_analysis_max_tool_calls=8,
            business_analysis_run_timeout_seconds=90,
            business_analysis_context_char_limit=12000,
        ),
    )
    events = [
        event
        async for event in run_business_analysis(
            BusinessAnalysisRequest(thread_id="nested", message="分析销售额"),
            agent=NestedModelAgent(),
            connection=FakeConnection(),
        )
    ]

    assert events[-1].type == "run_completed"


@pytest.mark.anyio
async def test_tool_completed_event_exposes_only_the_tool_summary():
    class VerboseToolAgent:
        async def astream_events(self, payload, config, version):
            yield {"event": "on_tool_start", "name": "analyze_business_data"}
            yield {
                "event": "on_tool_end",
                "name": "analyze_business_data",
                "data": {
                    "output": json.dumps(
                        {
                            "status": "ok",
                            "summary": "销售额在年末达到峰值。",
                            "data": {"rows": [{"private_detail": "do not stream"}]},
                        },
                        ensure_ascii=False,
                    )
                },
            }

    events = [
        event
        async for event in run_business_analysis(
            BusinessAnalysisRequest(thread_id="tool-summary", message="分析销售额"),
            agent=VerboseToolAgent(),
            connection=FakeConnection(),
        )
    ]

    completed = next(event for event in events if event.type == "tool_completed")
    assert completed.summary == "销售额在年末达到峰值。"
    assert "private_detail" not in completed.to_sse_payload()


@pytest.mark.anyio
async def test_runner_injects_whitelisted_user_preferences(monkeypatch):
    async def fake_preferences(_connection, _user_id):
        return {"preferred_region": "华东", "report_style": "简洁"}

    class PreferenceAwareAgent:
        async def astream_events(self, payload, config, version):
            assert payload["messages"][0]["role"] == "system"
            assert '"preferred_region": "华东"' in payload["messages"][0]["content"]
            assert payload["messages"][1] == {"role": "user", "content": "分析销售额"}
            if False:
                yield {}

    monkeypatch.setattr(
        "app.services.business_analysis_runner.load_user_preferences_from_db",
        fake_preferences,
    )
    events = [
        event
        async for event in run_business_analysis(
            BusinessAnalysisRequest(
                thread_id="preferences", message="分析销售额", user_id="user-1"
            ),
            agent=PreferenceAwareAgent(),
            connection=FakeConnection(),
        )
    ]

    assert events[-1].type == "run_completed"


async def _collect(events):
    return [event async for event in events]
