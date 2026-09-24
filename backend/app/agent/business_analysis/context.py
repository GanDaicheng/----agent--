from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any


def compact_tool_result(result: Mapping[str, Any], *, char_limit: int) -> dict[str, Any]:
    """Keep a bounded tool result in model context."""

    compacted = {
        "status": result.get("status", "error"),
        "summary": str(result.get("summary", ""))[:2000],
        "artifact_id": result.get("artifact_id"),
        "data": result.get("data", {}),
        "sources": result.get("sources", [])[:10]
        if isinstance(result.get("sources", []), list)
        else [],
    }
    encoded = json.dumps(compacted["data"], ensure_ascii=False, default=str)
    if len(encoded) > char_limit:
        compacted["data"] = {
            "truncated": True,
            "preview": encoded[: max(0, char_limit - 40)],
        }
    return compacted


def summarize_history(
    messages: Sequence[Mapping[str, str]],
    *,
    limit: int,
) -> list[dict[str, str]]:
    """Retain recent messages and summarize older messages into one system note."""

    if limit < 1:
        raise ValueError("历史消息保留数量必须大于0。")
    normalized = [
        {"role": str(message.get("role", "user")), "content": str(message.get("content", ""))}
        for message in messages
    ]
    if len(normalized) <= limit:
        return normalized

    older = normalized[:-limit]
    recent = normalized[-limit:]
    summary = "\n".join(f"{item['role']}: {item['content'][:500]}" for item in older)
    return [{"role": "system", "content": f"历史分析摘要：\n{summary}"}, *recent]
