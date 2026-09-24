from app.agent.business_analysis.events import to_public_event


def test_event_mapper_drops_sql_and_exception_details():
    event = to_public_event(
        {
            "type": "tool_completed",
            "tool": "analyze_business_data",
            "sql": "SELECT * FROM orders",
            "error": "password=secret",
        }
    )

    payload = event.to_sse_payload()

    assert "SELECT" not in payload
    assert "secret" not in payload
    assert event.tool == "analyze_business_data"


def test_event_mapper_rejects_unknown_tools():
    assert to_public_event({"type": "tool_started", "tool": "run_shell"}) is None
