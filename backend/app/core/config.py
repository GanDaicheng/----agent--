from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core.exceptions import ConfigurationError
from app.core.paths import ENV_FILE

# 异步引擎只能配合 asyncpg 驱动，连接串必须以这个前缀开头
ASYNC_SCHEME = "postgresql+asyncpg://"


class Settings(BaseSettings):
    # 显式指向项目根目录的 .env，避免受启动时工作目录影响
    model_config = SettingsConfigDict(env_file=ENV_FILE, extra="ignore")

    openai_api_key: str = ""
    openai_base_url: str = "https://api.deepseek.com/v1"
    model_name: str = "deepseek-chat"
    temperature: float = 0.0

    database_url: str = ""

    def require_database_url(self) -> str:
        """返回可用的异步连接串；缺失或驱动不对时抛出说明清楚的配置错误。

        故意不把连接串本身放进报错信息里，避免密码被打进日志或接口响应。
        """
        if not self.database_url:
            raise ConfigurationError(
                "缺少 DATABASE_URL。请在 .env 中按以下格式配置："
                f"{ASYNC_SCHEME}用户名:密码@localhost:5432/数据库名"
            )

        actual_scheme = self.database_url.split("://", 1)[0] + "://"
        if not self.database_url.startswith(ASYNC_SCHEME):
            # 常见错误：写成 postgresql://，SQLAlchemy 会去找并未安装的 psycopg2
            raise ConfigurationError(
                f"DATABASE_URL 的驱动不对：当前是 {actual_scheme}，"
                f"本项目的异步引擎要求改成 {ASYNC_SCHEME}"
            )
        return self.database_url


@lru_cache
def get_settings() -> Settings:
    return Settings()
