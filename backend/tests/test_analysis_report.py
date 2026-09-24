from __future__ import annotations

import json

import pytest

from app.services.analysis_report import (
    append_artifact,
    create_run,
    load_thread_runs,
    save_report,
)


class FakeConnection:
    def __init__(self, rows=None):
        self.statements: list[tuple[object, dict]] = []
        self.rows = rows or []

    async def execute(self, statement, params):
        self.statements.append((statement, params))
        class Result:
            def __init__(self, rows):
                self._rows = rows

            def mappings(self):
                return self

            def all(self):
                return self._rows

        return Result(self.rows)


@pytest.mark.anyio
async def test_create_run_returns_prefixed_id_and_inserts_record():
    connection = FakeConnection()

    run_id = await create_run(connection, thread_id="thread-1", user_id="user-1")

    assert run_id.startswith("run_")
    assert len(connection.statements) == 1
    statement, params = connection.statements[0]
    assert "business_analysis_runs" in str(statement)
    assert params["thread_id"] == "thread-1"


@pytest.mark.anyio
async def test_append_artifact_serializes_json_and_returns_id():
    connection = FakeConnection()

    artifact_id = await append_artifact(
        connection,
        run_id="run-1",
        kind="query_result",
        payload={"rows": [{"value": 1}]},
    )

    assert artifact_id.startswith("art_")
    _, params = connection.statements[0]
    assert json.loads(params["payload"]) == {"rows": [{"value": 1}]}


@pytest.mark.anyio
async def test_save_report_rejects_raw_sql_from_report_payload():
    connection = FakeConnection()

    report_id = await save_report(
        connection,
        run_id="run-1",
        report={
            "summary": "销售额下降",
            "evidence": ["SQL: SELECT * FROM orders"],
        },
    )

    assert report_id.startswith("report_")
    _, params = connection.statements[0]
    serialized = json.loads(params["report"])
    assert "SELECT" not in json.dumps(serialized, ensure_ascii=False)


@pytest.mark.anyio
async def test_load_thread_runs_returns_public_history():
    connection = FakeConnection(
        rows=[
            {
                "id": "run-1",
                "thread_id": "thread-1",
                "status": "completed",
                "created_at": "2026-09-24T10:00:00+08:00",
                "updated_at": "2026-09-24T10:01:00+08:00",
            }
        ]
    )

    runs = await load_thread_runs(connection, thread_id="thread-1")

    assert runs == [
        {
            "id": "run-1",
            "thread_id": "thread-1",
            "status": "completed",
            "created_at": "2026-09-24T10:00:00+08:00",
            "updated_at": "2026-09-24T10:01:00+08:00",
        }
    ]
