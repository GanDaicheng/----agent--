"""百炼 embedding 配置冒烟测试：确认 API 能真正调通。

用法（在 backend/ 或项目根目录下执行都可以）：

    python backend/scripts/smoke_embedding.py
    cd backend && python scripts/smoke_embedding.py

它只做一件事：对一段固定中文文本发**一次** embedding 请求，然后打印
模型名、期望维度、实际维度和状态。脚本不接受参数、不循环、不重试，
避免误用产生意料之外的调用费用。

输出里不含 API Key，也不打印完整向量（只给维度和前 3 个值的摘要）。
配置缺失或调用失败时以非 0 退出码结束，方便后续接 CI。
"""

import asyncio
import sys
from pathlib import Path

# 直接以 `python scripts/smoke_embedding.py` 运行时，sys.path[0] 是 scripts/ 而不是
# backend/，会导致 `import app` 失败。这里显式把 backend/ 加进搜索路径。
BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.core.config import get_settings  # noqa: E402
from app.core.exceptions import AppError  # noqa: E402
from app.services.embedding import (  # noqa: E402
    EmbeddingDimensionError,
    redact_secret,
    summarize_vector,
)

# 固定文本，取自 RAG 知识库的指标口径。用真实业务语句而不是 "hello"，
# 这样连中文、标点、数字混合输入这条路径也一起验证到了。
SAMPLE_TEXT = "客单价等于销售额除以订单数，用于衡量单笔订单的平均消费金额。"


def _known_secret() -> str:
    """尽力取出密钥用于输出清洗。取不到就返回空串，绝不因为它再抛一次异常。"""
    try:
        return get_settings().embedding_api_key or ""
    except Exception:
        return ""


def _print_failure(reason: str, *, hint: str = "") -> int:
    print("embedding 冒烟测试")
    print("-" * 52)
    print(f"  status             failed")
    print(f"  reason             {redact_secret(reason, _known_secret())}")
    if hint:
        print(f"  hint               {hint}")
    return 1


async def main() -> int:
    # 先单独校验配置，这样「配置没填好」和「接口调不通」能给出不同的提示，
    # 而不是混成一个笼统的失败。
    try:
        get_settings().require_embedding_settings()
    except AppError as error:
        return _print_failure(str(error), hint="检查项目根目录 .env 里的 EMBEDDING_* 配置。")

    # 建客户端也要放在 try 里：base_url 写错时异常在这一步就会抛出来
    from app.services.embedding import embed_text

    started = asyncio.get_event_loop().time()
    try:
        vector, settings = await embed_text(SAMPLE_TEXT)
    except EmbeddingDimensionError as error:
        return _print_failure(
            str(error), hint="EMBEDDING_MODEL 与 EMBEDDING_DIMENSION 不匹配。"
        )
    except Exception as error:  # 第三方 SDK 的异常类型很多，统一收口
        return _print_failure(
            f"{type(error).__name__}: {error}",
            hint="检查网络、EMBEDDING_BASE_URL、EMBEDDING_API_KEY 是否有效。",
        )
    elapsed = asyncio.get_event_loop().time() - started

    print("embedding 冒烟测试")
    print("-" * 52)
    print(f"  provider           {settings.provider}")
    print(f"  model              {settings.model}")
    print(f"  base_url           {settings.base_url}")
    print(f"  expected_dimension {settings.dimension}")
    print(f"  actual_dimension   {len(vector)}")
    print(f"  vector_preview     {summarize_vector(vector)}")
    print(f"  elapsed_seconds    {elapsed:.2f}")
    print(f"  status             ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
