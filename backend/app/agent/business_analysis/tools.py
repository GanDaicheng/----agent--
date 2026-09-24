from __future__ import annotations

from typing import Any

from langchain_core.tools import tool

from app.agent.data_query.graph import get_data_query_graph
from app.agent.business_analysis.schemas import ToolResult


def _public_query_result(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None

    columns = value.get("columns")
    rows = value.get("rows")
    row_count = value.get("row_count")
    source = value.get("source")
    if not isinstance(columns, list) or not isinstance(rows, list):
        return None
    if not isinstance(row_count, int) or row_count != len(rows):
        return None
    if source not in {"postgres", "mock"}:
        return None

    # The supervisor only needs a bounded sample. The full result can be
    # persisted as an Artifact by the runner in a later task.
    return {
        "columns": [str(column) for column in columns[:50]],
        "rows": [row for row in rows[:20] if isinstance(row, dict)],
        "row_count": row_count,
        "source": source,
    }


@tool
async def analyze_business_data(question: str) -> dict[str, Any]:
    """分析业务数据，返回受控的结论、表格摘要和图表建议。

    这个工具复用现有的安全问数 LangGraph；它不会直接生成 SQL、连接数据库
    或执行任意用户提供的查询。
    """

    normalized_question = question.strip()
    if not normalized_question:
        return ToolResult(
            status="error",
            summary="分析问题不能为空白。",
        ).model_dump()

    state = await get_data_query_graph().ainvoke({"question": normalized_question})
    answer = state.get("answer") if isinstance(state, dict) else None
    query_result = _public_query_result(state.get("query_result")) if isinstance(state, dict) else None
    chart_suggestion = state.get("chart_suggestion") if isinstance(state, dict) else None
    sources = state.get("knowledge_sources", []) if isinstance(state, dict) else []
    if not isinstance(sources, list):
        sources = []

    if not isinstance(answer, str) or not answer.strip():
        return ToolResult(
            status="error",
            summary="数据分析未生成可展示的结论。",
        ).model_dump()

    return ToolResult(
        status="ok",
        summary=answer[:2000],
        data={
            "query_result": query_result,
            "chart_suggestion": chart_suggestion,
        },
        sources=sources[:10],
    ).model_dump()


BUSINESS_ANALYSIS_TOOLS = (analyze_business_data,)
