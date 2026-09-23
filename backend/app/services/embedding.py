"""Embedding 服务：把文本转成向量。

走 OpenAI 兼容协议，所以换厂商（百炼 / OpenAI / 其他兼容服务）只需要改 .env 里的
EMBEDDING_BASE_URL 与 EMBEDDING_MODEL，不用动这个文件。

三条设计约束，都是踩过才会想到的：

1. **不在模块 import 时创建客户端。**
   模块级客户端会在 import 阶段就把配置读死，任何一次 `import app.services.embedding`
   （测试收集、Alembic env、脚本导入）都会被牵连；配置缺失时连导入都失败，
   报错点离真正的原因很远。这里改成懒加载，只在真的要发请求时才建。

2. **不在异常消息里带 api_key。**
   SDK 抛出的异常原文可能包含请求细节。对外抛出的错误只说「维度不符」「模型不对」，
   需要清洗第三方异常文本时用 redact_secret()。

3. **不打印向量。**
   1024 个浮点数打进日志既没用又占地方。调用方要观测就打印维度和前几个值。

本模块不连数据库、不建表、不做检索——那是后续阶段的事。
"""

import time
from collections.abc import Sequence
from functools import lru_cache

from openai import AsyncOpenAI

from app.core.config import EmbeddingSettings, get_settings
from app.core.exceptions import ConfigurationError

# 密钥在输出里的替代文本。写成常量而不是散落的字面量，方便测试断言。
REDACTED = "***REDACTED***"


class EmbeddingError(ConfigurationError):
    """embedding 调用相关的可预期错误。"""


class EmbeddingDimensionError(EmbeddingError):
    """返回向量的维度与 EMBEDDING_DIMENSION 不一致。"""


def redact_secret(text: str, secret: str) -> str:
    """把文本里出现的密钥替换掉。

    第三方 SDK 的异常原文不一定干净——它可能把请求头、URL 参数原样带出来。
    任何要打印或要向上抛出的第三方错误文本，都先过这一层再出去。
    """
    if not secret:
        return text
    return text.replace(secret, REDACTED)


@lru_cache
def _get_client() -> tuple[AsyncOpenAI, EmbeddingSettings]:
    """懒加载客户端与配置，返回 (client, settings)。

    这是唯一的「外部依赖注入缝」：测试 monkeypatch 本函数就能塞进假客户端，
    不必碰网络，也不用把 api_key 当成缓存键传进来。
    """
    settings = get_settings().require_embedding_settings()
    client = AsyncOpenAI(api_key=settings.api_key, base_url=settings.base_url)
    return client, settings


async def embed_texts(
    texts: Sequence[str],
) -> tuple[list[list[float]], EmbeddingSettings]:
    """把多条文本转成向量，返回 (vectors, settings)。

    向量顺序与入参顺序严格一致。同时把 settings 一并返回，方便调用方打印
    model / 维度做观测，而不必再读一次配置。

    一次请求发多条，比循环单条调用省额度也省时间；但不要用它做无上限的批量——
    输入越长越容易被服务端截断或拒绝，批量大小由调用方控制。
    """
    if not texts:
        raise EmbeddingError("texts 不能为空。")

    blanks = [index for index, text in enumerate(texts) if not (text or "").strip()]
    if blanks:
        # 空文本换回来的是无意义的向量，发出去只是白花额度
        raise EmbeddingError(f"第 {blanks} 条文本为空，已取消本次请求。")

    client, settings = _get_client()

    response = await client.embeddings.create(
        model=settings.model,
        input=list(texts),
        dimensions=settings.dimension,
    )

    # 按 index 排序再取，别依赖返回顺序恰好等于入参顺序
    vectors = [list(item.embedding) for item in sorted(response.data, key=lambda item: item.index)]

    if len(vectors) != len(texts):
        raise EmbeddingError(
            f"返回条数与请求条数不符：请求 {len(texts)} 条，返回 {len(vectors)} 条。"
        )

    for position, vector in enumerate(vectors):
        if len(vector) != settings.dimension:
            raise EmbeddingDimensionError(
                f"第 {position} 条向量维度不符：期望 {settings.dimension}，实际 {len(vector)}。"
                f"请检查 EMBEDDING_MODEL（当前 {settings.model}）"
                f"与 EMBEDDING_DIMENSION（当前 {settings.dimension}）是否匹配。"
            )

    return vectors, settings


async def embed_text(text: str) -> tuple[list[float], EmbeddingSettings]:
    """把单条文本转成向量，返回 (vector, settings)。"""
    vectors, settings = await embed_texts([text])
    return vectors[0], settings


def summarize_vector(vector: Sequence[float], *, preview: int = 3) -> str:
    """生成向量的简短摘要——只含维度和前几个值，不打印整个向量。"""
    head = ", ".join(f"{value:.6f}" for value in list(vector)[:preview])
    return f"[{head}, ...] 共 {len(vector)} 维"


async def measure_embedding_latency(text: str) -> tuple[list[float], float]:
    """为冒烟测试准备：返回向量与实际耗时（秒）。"""
    started = time.perf_counter()
    vector, _ = await embed_text(text)
    return vector, time.perf_counter() - started
