from langchain_openai import ChatOpenAI

from app.config import get_settings


def get_llm() -> ChatOpenAI:
    """构建 LLM 实例。切换模型厂商只需改 .env，不用动代码。"""
    settings = get_settings()
    if not settings.openai_api_key:
        raise RuntimeError(
            "缺少 OPENAI_API_KEY。请复制 .env.example 为 .env 并填入真实密钥。"
        )
    return ChatOpenAI(
        model=settings.model_name,
        api_key=settings.openai_api_key,
        base_url=settings.openai_base_url,
        temperature=settings.temperature,
    )
