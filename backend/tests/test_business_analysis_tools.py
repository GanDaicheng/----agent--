from pathlib import Path

import pytest


@pytest.mark.anyio
async def test_analyze_business_data_calls_existing_graph(monkeypatch):
    from app.agent.business_analysis.tools import analyze_business_data

    calls = []

    class FakeGraph:
        async def ainvoke(self, state):
            calls.append(state)
            return {
                "answer": "华东销售额下降",
                "query_result": {
                    "columns": ["month"],
                    "rows": [],
                    "row_count": 0,
                    "source": "postgres",
                },
                "chart_suggestion": None,
                "knowledge_sources": [],
            }

    monkeypatch.setattr(
        "app.agent.business_analysis.tools.get_data_query_graph",
        lambda: FakeGraph(),
    )
    result = await analyze_business_data.ainvoke({"question": "分析华东销售额"})

    assert calls == [{"question": "分析华东销售额"}]
    assert result["status"] == "ok"
    assert result["summary"] == "华东销售额下降"
    assert result["data"]["query_result"]["source"] == "postgres"


def test_business_analysis_tools_do_not_import_database_drivers():
    source = Path("backend/app/agent/business_analysis/tools.py").read_text(
        encoding="utf-8"
    )

    assert "sqlalchemy" not in source
    assert "asyncpg" not in source
    assert "get_engine" not in source
