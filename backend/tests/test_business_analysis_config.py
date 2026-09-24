def test_deepagents_package_is_importable():
    import deepagents

    assert getattr(deepagents, "__version__", None) in {None, "0.7.18"}
    assert callable(deepagents.create_deep_agent)


def test_business_analysis_limits_have_safe_defaults():
    from app.core.config import get_settings

    settings = get_settings()

    assert settings.business_analysis_max_steps == 12
    assert settings.business_analysis_max_tool_calls == 8
    assert settings.business_analysis_run_timeout_seconds == 90
    assert settings.business_analysis_context_char_limit == 12000
