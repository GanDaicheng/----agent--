from langchain.agents import create_agent
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from app.agent.prompts import SYSTEM_PROMPT
from app.agent.tools import TOOLS
from app.core.llm import get_llm

_agent = None


def get_agent():
    """懒加载并缓存 agent。首次调用时才构建，避免无 key 时导入即失败。"""
    global _agent
    if _agent is None:
        _agent = create_agent(
            model=get_llm(),
            tools=TOOLS,
            system_prompt=SYSTEM_PROMPT,
        )
    return _agent


SUPPORTED_ROLES = {"user", "assistant", "system"}


def _to_message(role: str, content: str):
    try:
        cls = {
            "user": HumanMessage,
            "assistant": AIMessage,
            "system": SystemMessage,
        }[role]
    except KeyError:
        raise ValueError(f"不支持的消息角色：{role}") from None
    return cls(content=content)


def run_agent(messages: list[dict]) -> str:
    """接收 [{role, content}] 历史消息，返回最终文本回复。"""
    unknown = {m["role"] for m in messages} - SUPPORTED_ROLES
    if unknown:
        raise ValueError(f"不支持的消息角色：{', '.join(sorted(unknown))}")

    lc_messages = [_to_message(m["role"], m["content"]) for m in messages]
    result = get_agent().invoke({"messages": lc_messages})
    final = result["messages"][-1]
    content = final.content
    if isinstance(content, list):
        # 部分厂商返回结构化 content 块，这里拼接出纯文本
        content = "".join(
            part.get("text", "") if isinstance(part, dict) else str(part)
            for part in content
        )
    return content
