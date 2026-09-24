from app.agent.business_analysis.prompts import BUSINESS_ANALYSIS_SYSTEM_PROMPT


def test_agent_exposes_only_business_tools(monkeypatch):
    captured = {}

    def fake_create_deep_agent(**kwargs):
        captured.update(kwargs)
        return object()

    monkeypatch.setattr(
        "app.agent.business_analysis.agent.create_deep_agent",
        fake_create_deep_agent,
    )
    monkeypatch.setattr(
        "app.agent.business_analysis.agent.get_llm",
        lambda: "fake-model",
    )
    from app.agent.business_analysis.agent import get_business_analysis_agent

    get_business_analysis_agent(force_rebuild=True)

    names = {tool.name for tool in captured["tools"]}
    assert names == {
        "analyze_business_data",
        "search_business_knowledge",
        "get_metric_definition",
    }


def test_prompt_requires_evidence_and_rejects_unsupported_claims():
    assert "不得编造" in BUSINESS_ANALYSIS_SYSTEM_PROMPT
    assert "数据证据" in BUSINESS_ANALYSIS_SYSTEM_PROMPT
    assert "SQL" in BUSINESS_ANALYSIS_SYSTEM_PROMPT
    assert "同一任务内最多调用一次 analyze_business_data" in BUSINESS_ANALYSIS_SYSTEM_PROMPT
    assert "不得通过改写问法重复调用" in BUSINESS_ANALYSIS_SYSTEM_PROMPT


def test_agent_uses_supplied_model_and_persistence(monkeypatch):
    captured = {}

    def fake_create_deep_agent(**kwargs):
        captured.update(kwargs)
        return "compiled-agent"

    monkeypatch.setattr(
        "app.agent.business_analysis.agent.create_deep_agent",
        fake_create_deep_agent,
    )
    from app.agent.business_analysis.agent import get_business_analysis_agent

    agent = get_business_analysis_agent(
        force_rebuild=True,
        model="fake-model",
        checkpointer="fake-checkpointer",
        store="fake-store",
    )

    assert agent == "compiled-agent"
    assert captured["model"] == "fake-model"
    assert captured["checkpointer"] == "fake-checkpointer"
    assert captured["store"] == "fake-store"
