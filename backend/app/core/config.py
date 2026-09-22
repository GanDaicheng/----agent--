from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    openai_api_key: str = ""
    openai_base_url: str = "https://api.deepseek.com/v1"
    model_name: str = "deepseek-chat"
    temperature: float = 0.0

    system_prompt: str = (
        "你是一个数据中台智能助手。你可以调用工具来获取信息，"
        "在需要时主动使用工具，并用中文简洁地回答用户。"
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
