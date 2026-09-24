"""精排真实冒烟：拿三条中性文本，真的调一次百炼 /reranks，看排序对不对。

用法（在 backend/ 或项目根目录下执行都可以）：

    python backend/scripts/smoke_reranker.py
    cd backend && python scripts/smoke_reranker.py

**这个脚本会真的调用一次百炼**（本阶段唯一允许的真实网络请求）。
它不连数据库、不算向量、不问回答模型——只验证「精排这一条链路通不通」。

## 三条探测文本为什么是这种内容

三条都是通用常识句，互不相关，其中第二条才是问题的答案：

    问题：水的沸点是多少度？
    0 号：苹果……（不相关）
    1 号：水的沸点是一百摄氏度……（答案）
    2 号：地球公转……（不相关）

这样「1 号排第一」就是一次**有意义的**验证，而不是「接口返回了 200」。
用真实业务文档做探测会把内容带进输出，而脚本的输出经常被贴进 issue。

## 输出里有什么、没有什么

只打印：provider、model、candidate_count、returned_count、
index、relevance_score、elapsed_seconds、status。

不打印：API Key、Authorization 头、完整 URL（里面带着业务空间 ID）、
候选正文、供应商响应原文。

失败时也不重试、不换模型——冒烟脚本的职责是报告现状，
自动重试会把「配置错在哪」这件事掩盖掉。
"""

import asyncio
import sys
import time
from dataclasses import dataclass
from pathlib import Path

# 直接以 `python scripts/smoke_reranker.py` 运行时，sys.path[0] 是 scripts/
# 而不是 backend/，会导致 `import app` 失败。与其余脚本同一处理方式。
BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.core.config import get_settings  # noqa: E402
from app.core.exceptions import ConfigurationError  # noqa: E402
from app.services.reranker import (  # noqa: E402
    DashScopeReranker,
    RerankItem,
    Reranker,
    RerankerProviderError,
)

# 探测数据。中性、无隐私、无业务数据，且第二条才是问题的答案。
SMOKE_QUERY = "水的沸点是多少度？"
SMOKE_DOCUMENTS = (
    "苹果是一种常见的水果，多生长在温带地区，品种繁多，可以直接食用。",
    "在标准大气压下，水的沸点是一百摄氏度；气压降低时沸点会随之下降。",
    "地球绕太阳公转一周大约需要三百六十五天，这就是一年的长度。",
)
SMOKE_TOP_N = 2


@dataclass(frozen=True)
class SmokeResult:
    provider: str
    model: str
    candidate_count: int
    returned_count: int
    items: tuple[RerankItem, ...]
    elapsed_seconds: float
    status: str


async def run(*, reranker: Reranker | None = None, top_n: int = SMOKE_TOP_N) -> SmokeResult:
    """发一次精排请求并汇总结果。

    reranker 不传时才按配置建生产适配器——测试注入替身之后，
    这个脚本的整条逻辑都能离线跑。
    """
    started = time.perf_counter()

    settings = get_settings().require_rerank_settings()
    provider = reranker if reranker is not None else DashScopeReranker(settings)

    items = await provider.rerank(SMOKE_QUERY, list(SMOKE_DOCUMENTS), top_n=top_n)

    return SmokeResult(
        provider=settings.provider,
        model=settings.model,
        candidate_count=len(SMOKE_DOCUMENTS),
        returned_count=len(items),
        items=tuple(items),
        elapsed_seconds=time.perf_counter() - started,
        status="ok",
    )


def print_result(result: SmokeResult) -> None:
    print("精排冒烟验证")
    print("=" * 52)
    print(f"  provider          {result.provider}")
    print(f"  model             {result.model}")
    print(f"  candidate_count   {result.candidate_count}")
    print(f"  returned_count    {result.returned_count}")
    print(f"  elapsed_seconds   {result.elapsed_seconds:.2f}")
    print(f"  status            {result.status}")
    print("-" * 52)
    print("  index  relevance_score")
    for item in result.items:
        print(f"  {item.index:<6} {item.relevance_score:.6f}")


async def main() -> int:
    try:
        result = await run()
    except ConfigurationError as error:
        # 配置错误是我们自己抛的，消息按约定只点名变量、不带值
        print("精排冒烟验证失败（配置问题）")
        print(f"  {type(error).__name__}: {error}")
        return 1
    except RerankerProviderError as error:
        # 供应商错误也是我们自己抛的：消息里只有错误类别和状态码
        print("精排冒烟验证失败（供应商侧）")
        print(f"  {type(error).__name__}: {error}")
        print("  本次不重试；请检查网络与配置，或把 RAG_RERANK_ENABLED 设为 false。")
        return 1
    except Exception as error:  # noqa: BLE001
        # 第三方异常：只给类名。它的原文可能带着请求头、完整 URL 和响应内容，
        # 而这个脚本的输出经常被原样贴出去。
        print("精排冒烟验证失败")
        print(f"  {type(error).__name__}")
        print("  详细原因未打印（第三方异常正文可能含敏感信息）。")
        return 1

    print_result(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
