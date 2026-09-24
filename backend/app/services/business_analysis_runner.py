from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from typing import Any

from app.agent.business_analysis.agent import get_business_analysis_agent
from app.agent.business_analysis.events import to_public_event
from app.agent.business_analysis.schemas import AnalysisEvent, BusinessAnalysisRequest
from app.agent.business_analysis.tools import bind_report_saver
from app.core.config import get_settings
from app.repositories.database import get_engine
from app.services.analysis_report import create_run, save_report


class BusinessAnalysisBusyError(RuntimeError):
    """The same thread already has an active run in this process."""


class _RunLimitReached(RuntimeError):
    pass


_active_threads: set[str] = set()


@asynccontextmanager
async def _connection_scope(connection: Any | None):
    if connection is not None:
        yield connection
        return
    async with get_engine().begin() as active:
        yield active


def _extract_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    content = getattr(value, "content", None)
    if isinstance(content, str):
        return content
    if isinstance(value, dict):
        content = value.get("content") or value.get("summary")
        if isinstance(content, str):
            return content
    return ""


async def _agent_events(
    agent: Any,
    request: BusinessAnalysisRequest,
    *,
    max_steps: int,
    max_tool_calls: int,
) -> AsyncIterator[AnalysisEvent]:
    payload = {"messages": [{"role": "user", "content": request.message}]}
    config = {
        "configurable": {
            "thread_id": request.thread_id,
            "user_id": request.user_id or "anonymous",
        }
    }
    steps = 0
    tool_calls = 0
    async for raw in agent.astream_events(payload, config=config, version="v2"):
        steps += 1
        if steps > max_steps:
            raise _RunLimitReached
        event_name = raw.get("event") if isinstance(raw, dict) else None
        if event_name == "on_tool_start":
            tool_calls += 1
            if tool_calls > max_tool_calls:
                raise _RunLimitReached
            public = to_public_event(
                {"type": "tool_started", "tool": raw.get("name")}
            )
        elif event_name == "on_tool_end":
            output = raw.get("data", {}).get("output") if isinstance(raw, dict) else None
            public = to_public_event(
                {
                    "type": "tool_completed",
                    "tool": raw.get("name"),
                    "summary": _extract_text(output),
                }
            )
        elif event_name == "on_chat_model_stream":
            chunk = raw.get("data", {}).get("chunk") if isinstance(raw, dict) else None
            content = _extract_text(chunk)
            public = to_public_event({"type": "report_delta", "content": content}) if content else None
        else:
            public = None
        if public is not None:
            yield public


async def run_business_analysis(
    request: BusinessAnalysisRequest,
    *,
    agent: Any | None = None,
    connection: Any | None = None,
) -> AsyncIterator[AnalysisEvent]:
    """Run one resumable supervisor task and expose safe public events."""

    if request.thread_id in _active_threads:
        raise BusinessAnalysisBusyError("该分析会话已有任务正在运行。")
    _active_threads.add(request.thread_id)
    settings = get_settings()
    active_agent = agent or get_business_analysis_agent()
    report_chunks: list[str] = []

    try:
        async with _connection_scope(connection) as active_connection:
            run_id = await create_run(
                active_connection,
                thread_id=request.thread_id,
                user_id=request.user_id,
            )
            yield AnalysisEvent.run_started(run_id)

            async def report_saver(*, run_id: str, report: dict[str, Any]) -> str:
                return await save_report(active_connection, run_id=run_id, report=report)

            async with bind_report_saver(report_saver):
                try:
                    async with asyncio.timeout(settings.business_analysis_run_timeout_seconds):
                        async for event in _agent_events(
                            active_agent,
                            request,
                            max_steps=settings.business_analysis_max_steps,
                            max_tool_calls=settings.business_analysis_max_tool_calls,
                        ):
                            if event.type == "report_delta" and event.content:
                                report_chunks.append(event.content)
                            yield event
                except _RunLimitReached:
                    yield AnalysisEvent.error("AGENT_RUN_LIMIT_REACHED")
                    return
                except TimeoutError:
                    yield AnalysisEvent.error("AGENT_RUN_TIMEOUT")
                    return

            report_id = await save_report(
                active_connection,
                run_id=run_id,
                report={"summary": "".join(report_chunks)[: settings.business_analysis_context_char_limit]},
            )
            yield AnalysisEvent.run_completed(run_id, report_id)
    except BusinessAnalysisBusyError:
        raise
    except Exception:
        yield AnalysisEvent.error("AGENT_RUN_FAILED")
    finally:
        _active_threads.discard(request.thread_id)
