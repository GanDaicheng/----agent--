from app.agent.business_analysis.context import compact_tool_result, summarize_history


def test_compact_tool_result_keeps_summary_and_artifact_id():
    compacted = compact_tool_result(
        {
            "status": "ok",
            "summary": "下降最大品类是家电",
            "data": {"rows": list(range(1000))},
            "artifact_id": "art_1",
        },
        char_limit=200,
    )

    assert compacted["summary"] == "下降最大品类是家电"
    assert compacted["artifact_id"] == "art_1"
    assert len(str(compacted["data"])) <= 200


def test_summarize_history_keeps_recent_messages():
    messages = [
        {"role": "user", "content": "旧问题"},
        {"role": "assistant", "content": "旧回答"},
        {"role": "user", "content": "最新问题"},
    ]

    summarized = summarize_history(messages, limit=2)

    assert summarized[-1] == {"role": "user", "content": "最新问题"}
    assert summarized[0]["role"] == "system"
    assert "旧问题" in summarized[0]["content"]
