from __future__ import annotations

import json
import re
from collections.abc import Mapping
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

SQL_TOKEN = re.compile(r"\b(?:SELECT|INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|TRUNCATE)\b[^\n]*", re.IGNORECASE)


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex}"


def _sanitize_json(value: object) -> object:
    if isinstance(value, str):
        return SQL_TOKEN.sub("[redacted]", value)
    if isinstance(value, Mapping):
        return {str(key): _sanitize_json(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_sanitize_json(item) for item in value]
    if isinstance(value, tuple):
        return [_sanitize_json(item) for item in value]
    return value


async def create_run(
    connection: AsyncConnection,
    *,
    thread_id: str,
    user_id: str | None = None,
) -> str:
    run_id = _new_id("run")
    await connection.execute(
        text(
            """
            INSERT INTO business_analysis_runs (id, thread_id, user_id, status)
            VALUES (:id, :thread_id, :user_id, 'running')
            """
        ),
        {"id": run_id, "thread_id": thread_id, "user_id": user_id},
    )
    return run_id


async def append_artifact(
    connection: AsyncConnection,
    *,
    run_id: str,
    kind: str,
    payload: object,
) -> str:
    artifact_id = _new_id("art")
    safe_payload = _sanitize_json(payload)
    await connection.execute(
        text(
            """
            INSERT INTO business_analysis_artifacts (id, run_id, kind, payload)
            VALUES (:id, :run_id, :kind, CAST(:payload AS JSONB))
            """
        ),
        {
            "id": artifact_id,
            "run_id": run_id,
            "kind": kind[:64],
            "payload": json.dumps(safe_payload, ensure_ascii=False),
        },
    )
    return artifact_id


async def save_report(
    connection: AsyncConnection,
    *,
    run_id: str,
    report: Mapping[str, object],
) -> str:
    report_id = _new_id("report")
    safe_report = _sanitize_json(report)
    await connection.execute(
        text(
            """
            INSERT INTO business_analysis_reports (id, run_id, report)
            VALUES (:id, :run_id, CAST(:report AS JSONB))
            """
        ),
        {
            "id": report_id,
            "run_id": run_id,
            "report": json.dumps(safe_report, ensure_ascii=False),
        },
    )
    return report_id
