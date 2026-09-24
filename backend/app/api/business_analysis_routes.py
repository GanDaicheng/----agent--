from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from app.agent.business_analysis.schemas import AnalysisEvent, BusinessAnalysisRequest
from app.services.business_analysis_runner import (
    BusinessAnalysisBusyError,
    is_thread_busy,
    run_business_analysis,
)

router = APIRouter()


def _format_sse(event: AnalysisEvent) -> str:
    return f"event: {event.type}\ndata: {event.to_sse_payload()}\n\n"


async def _stream_events(request: BusinessAnalysisRequest) -> AsyncIterator[str]:
    try:
        async for event in run_business_analysis(request):
            yield _format_sse(event)
    except asyncio.CancelledError:
        raise
    except BusinessAnalysisBusyError:
        # The route pre-check handles the normal case; this is a race-safe fallback.
        yield _format_sse(AnalysisEvent.error("AGENT_THREAD_BUSY"))
    except Exception:
        yield _format_sse(AnalysisEvent.error("AGENT_RUN_FAILED"))


@router.post("/api/v1/agent/business-analysis/runs")
async def business_analysis_run(request: BusinessAnalysisRequest) -> StreamingResponse:
    if is_thread_busy(request.thread_id):
        raise HTTPException(status_code=409, detail="该分析会话已有任务正在运行。")
    return StreamingResponse(
        _stream_events(request),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
