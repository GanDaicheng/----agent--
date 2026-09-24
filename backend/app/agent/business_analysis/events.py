from __future__ import annotations

import re
from typing import Any

from app.agent.business_analysis.schemas import AnalysisEvent

ALLOWED_TOOLS = {
    "analyze_business_data",
    "search_business_knowledge",
    "get_metric_definition",
    "save_analysis_report",
}
SQL_OR_SECRET = re.compile(
    r"(?:SELECT|INSERT|UPDATE|DELETE|DROP|ALTER|CREATE)\b[^\n]*|password\s*=\s*[^\s]+",
    re.IGNORECASE,
)


def _safe_text(value: Any, *, limit: int = 1000) -> str | None:
    if not isinstance(value, str):
        return None
    return SQL_OR_SECRET.sub("[redacted]", value)[:limit]


def to_public_event(raw_event: Any) -> AnalysisEvent | None:
    """Map internal Agent events to a fixed, non-sensitive public contract."""

    if not isinstance(raw_event, dict):
        return None
    event_type = raw_event.get("type")
    if event_type == "tool_started":
        tool = raw_event.get("tool")
        if tool not in ALLOWED_TOOLS:
            return None
        return AnalysisEvent.tool_started(tool)
    if event_type == "tool_completed":
        tool = raw_event.get("tool")
        if tool not in ALLOWED_TOOLS:
            return None
        summary = _safe_text(raw_event.get("summary")) or "工具调用已完成。"
        return AnalysisEvent.tool_completed(tool, summary)
    if event_type == "status":
        label = _safe_text(raw_event.get("label"))
        return AnalysisEvent.status(label or "正在处理分析任务。")
    if event_type == "report_delta":
        content = _safe_text(raw_event.get("content"), limit=4000)
        return AnalysisEvent.report_delta(content or "")
    if event_type == "run_started" and isinstance(raw_event.get("run_id"), str):
        return AnalysisEvent.run_started(raw_event["run_id"])
    if event_type == "run_completed" and isinstance(raw_event.get("run_id"), str):
        report_id = raw_event.get("report_id")
        return AnalysisEvent.run_completed(raw_event["run_id"], report_id if isinstance(report_id, str) else None)
    if event_type == "error":
        return AnalysisEvent.error("AGENT_RUN_FAILED")
    return None
