from dataclasses import dataclass, field
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core.exceptions import ConfigurationError
from app.core.paths import ENV_FILE

# 异步引擎只能配合 asyncpg 驱动，连接串必须以这个前缀开头
ASYNC_SCHEME = "postgresql+asyncpg://"

# embedding 的默认值：百炼（DashScope）OpenAI 兼容模式。
# text-embedding-v4 支持 1024 维，与 pgvector 的 vector(1024) 对齐。
# 换厂商只改 .env，不用动代码。
DEFAULT_EMBEDDING_PROVIDER = "dashscope"
DEFAULT_EMBEDDING_MODEL = "text-embedding-v4"
DEFAULT_EMBEDDING_DIMENSION = 1024
DEFAULT_EMBEDDING_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"


@dataclass(frozen=True)
class EmbeddingSettings:
    """校验通过的 embedding 配置。

    api_key 特意标了 repr=False：这个对象可能被顺手打进日志或异常上下文，
    而 dataclass 的默认 repr 会把每个字段原样打出来。屏蔽掉之后，
    即使有人 print(settings)，密钥也不会出现在输出里。
    """

    provider: str
    model: str
    dimension: int
    base_url: str
    api_key: str = field(repr=False)


class Settings(BaseSettings):
    # 显式指向项目根目录的 .env，避免受启动时工作目录影响
    model_config = SettingsConfigDict(env_file=ENV_FILE, extra="ignore")

    openai_api_key: str = ""
    openai_base_url: str = "https://api.deepseek.com/v1"
    model_name: str = "deepseek-chat"
    temperature: float = 0.0

    database_url: str = ""

    embedding_provider: str = DEFAULT_EMBEDDING_PROVIDER
    embedding_model: str = DEFAULT_EMBEDDING_MODEL
    embedding_dimension: int = DEFAULT_EMBEDDING_DIMENSION
    embedding_api_key: str = ""
    embedding_base_url: str = DEFAULT_EMBEDDING_BASE_URL

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

    def require_embedding_settings(self) -> EmbeddingSettings:
        """返回校验通过的 embedding 配置；缺失或非法时抛出说明清楚的配置错误。

        报错只说明「哪个变量有问题」，绝不带上变量值——API Key 一旦进了异常消息，
        就会顺着日志、接口响应、错误上报一路扩散出去，而这正是最难回收的一类泄露。
        所以这里连 api_key 的长度、前后缀都不提。
        """
        missing: list[str] = []
        if not self.embedding_api_key.strip():
            missing.append("EMBEDDING_API_KEY")
        if not self.embedding_base_url.strip():
            missing.append("EMBEDDING_BASE_URL")
        if not self.embedding_model.strip():
            missing.append("EMBEDDING_MODEL")
        if missing:
            raise ConfigurationError(
                "缺少 embedding 配置：" + "、".join(missing)
                + "。请复制 .env.example 为 .env 并填入对应值。"
            )

        # 维度必须是正整数。写 0 或负数时下游建表、算距离都会得出没有意义的结论，
        # 在这里拦住比等 pgvector 报错更早也更好懂。
        if not isinstance(self.embedding_dimension, int) or self.embedding_dimension <= 0:
            raise ConfigurationError(
                f"EMBEDDING_DIMENSION 必须是正整数，当前为 {self.embedding_dimension!r}。"
            )

        return EmbeddingSettings(
            provider=self.embedding_provider.strip() or DEFAULT_EMBEDDING_PROVIDER,
            model=self.embedding_model.strip(),
            dimension=self.embedding_dimension,
            base_url=self.embedding_base_url.strip(),
            api_key=self.embedding_api_key.strip(),
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
