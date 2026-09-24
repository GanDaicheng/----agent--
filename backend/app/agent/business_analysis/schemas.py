from __future__ import annotations

import json
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class BusinessAnalysisRequest(BaseModel):
    """Public input for one business-analysis run."""

    thread_id: str = Field(min_length=1, max_length=128)
    message: str = Field(min_length=1, max_length=5000)
    user_id: str | None = Field(default=None, max_length=128)

    @field_validator("thread_id", "message", "user_id", mode="before")
    @classmethod
    def strip_text(cls, value: Any) -> Any:
        if isinstance(value, str):
            return value.strip()
        return value

    @field_validator("message")
    @classmethod
    def reject_blank_message(cls, value: str) -> str:
        if not value:
            raise ValueError("分析问题不能为空白。")
        return value


class ToolResult(BaseModel):
    """A bounded, JSON-safe result returned from a business tool."""

    status: Literal["ok", "degraded", "not_found", "error"]
    summary: str = Field(max_length=2000)
    data: dict[str, Any] = Field(default_factory=dict)
    sources: list[dict[str, Any]] = Field(default_factory=list)
    artifact_id: str | None = Field(default=None, max_length=128)

    model_config = ConfigDict(extra="ignore")


EventType = Literal[
    "run_started",
    "status",
    "tool_started",
    "tool_completed",
    "report_delta",
    "run_completed",
    "error",
]


class AnalysisEvent(BaseModel):
    """Safe event contract shared by the runner and the SSE API."""

    type: EventType
    run_id: str | None = None
    tool: str | None = None
    label: str | None = None
    summary: str | None = None
    content: str | None = None
    report_id: str | None = None
    error_code: str | None = None

    model_config = ConfigDict(extra="ignore")

    @classmethod
    def run_started(cls, run_id: str) -> "AnalysisEvent":
        return cls(type="run_started", run_id=run_id)

    @classmethod
    def status(cls, label: str) -> "AnalysisEvent":
        return cls(type="status", label=label)

    @classmethod
    def tool_started(cls, tool: str) -> "AnalysisEvent":
        return cls(type="tool_started", tool=tool)

    @classmethod
    def tool_completed(
        cls,
        tool: str,
        summary: str,
        metadata: dict[str, Any] | None = None,
    ) -> "AnalysisEvent":
        # metadata is accepted for internal callers but intentionally discarded.
        del metadata
        return cls(type="tool_completed", tool=tool, summary=summary)

    @classmethod
    def report_delta(cls, content: str) -> "AnalysisEvent":
        return cls(type="report_delta", content=content)

    @classmethod
    def run_completed(cls, run_id: str, report_id: str | None = None) -> "AnalysisEvent":
        return cls(type="run_completed", run_id=run_id, report_id=report_id)

    @classmethod
    def error(cls, error_code: str) -> "AnalysisEvent":
        return cls(type="error", error_code=error_code)

    def to_sse_payload(self) -> str:
        """Serialize only the public event fields as one JSON object."""

        return json.dumps(
            self.model_dump(exclude_none=True),
            ensure_ascii=False,
            separators=(",", ":"),
        )


class AnalysisReport(BaseModel):
    summary: str = ""
    evidence: list[str] = Field(default_factory=list)
    causes: list[str] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    sources: list[dict[str, Any]] = Field(default_factory=list)
    chart_configs: list[dict[str, Any]] = Field(default_factory=list)


class BusinessAnalysisResponse(BaseModel):
    status: Literal["ok", "error"]
    run_id: str
    report_id: str | None = None
    report: AnalysisReport | None = None
