from __future__ import annotations

from typing import Any

from deepagents import create_deep_agent

from app.agent.business_analysis.prompts import BUSINESS_ANALYSIS_SYSTEM_PROMPT
from app.agent.business_analysis.tools import BUSINESS_ANALYSIS_TOOLS
from app.core.llm import get_llm

_agent: Any | None = None


def get_business_analysis_agent(
    *,
    force_rebuild: bool = False,
    model: Any | None = None,
    checkpointer: Any | None = None,
    store: Any | None = None,
) -> Any:
    """Build and cache the supervisor graph with a fixed tool allow-list."""

    global _agent
    if _agent is None or force_rebuild:
        _agent = create_deep_agent(
            model=model if model is not None else get_llm(),
            tools=BUSINESS_ANALYSIS_TOOLS,
            system_prompt=BUSINESS_ANALYSIS_SYSTEM_PROMPT,
            checkpointer=checkpointer,
            store=store,
            name="business-analysis-supervisor",
        )
    return _agent
