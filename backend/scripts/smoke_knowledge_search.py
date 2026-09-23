"""知识检索验证：用固定问题跑一遍 top-3，人工核对召回质量。

用法（在 backend/ 或项目根目录下执行都可以）：

    python backend/scripts/smoke_knowledge_search.py
    cd backend && python scripts/smoke_knowledge_search.py

它做两件事：
1. 对每个固定问题调一次 embedding（**每个问题一次请求，共 5 次**）；
2. 用 pgvector 检索 top-3 并打印来源、距离、相似度和正文预览。

每个问题都标了「预期来源」——那是人工判断的正确答案所在文件。
脚本会标出预期文件有没有进前 3，这样召回对不对一眼就能看出来，
不用你自己记住哪个问题该命中哪个文件。

**不调用 LLM、不生成回答**：这一步只验证「找得到」，不验证「答得好」。
两者要分开看——检索不准的时候，再强的模型也答不对；
检索准了而回答不好，才轮到调 prompt。

输出不含 API Key，也不打印任何完整向量。
"""

import asyncio
import re
import sys
from dataclasses import dataclass
from pathlib import Path

# 直接以 `python scripts/smoke_knowledge_search.py` 运行时，sys.path[0] 是 scripts/
# 而不是 backend/，会导致 `import app` 失败。与其它脚本同一处理方式。
BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.core.config import get_settings  # noqa: E402
from app.core.exceptions import AppError  # noqa: E402
from app.repositories.database import dispose_engine  # noqa: E402
from app.services.embedding import redact_secret  # noqa: E402
from app.services.knowledge_search import (  # noqa: E402
    count_searchable_chunks,
    search_knowledge,
)

TOP_K = 3
PREVIEW_CHARS = 120


@dataclass(frozen=True)
class ProbeQuestion:
    """一个验证问题，外加「正确答案应该在哪个文件里」这个人工标注。"""

    question: str
    expected_source_file: str


# 5 个固定问题，覆盖知识库的 5 个文件各一次。
# 期望来源不是脚本猜的，是按文档内容人工指定的：
# 哪个问题该命中哪份文档是明确的，所以命中与否可以直接判定。
PROBE_QUESTIONS: tuple[ProbeQuestion, ...] = (
    ProbeQuestion("客单价怎么算？", "retail_metrics.md"),
    ProbeQuestion("为什么高等级会员复购率更高？", "member_rules.md"),
    ProbeQuestion("为什么 12 月销售额通常更高？", "promotion_calendar.md"),
    ProbeQuestion("订单分析要关联哪些表？", "retail_data_dictionary.md"),
    ProbeQuestion("华东销售额为什么通常更高？", "regional_sales_rules.md"),
)


def known_secret() -> str:
    """尽力取出密钥用于输出清洗。取不到就返回空串，绝不因为清洗再抛异常。"""
    try:
        return get_settings().embedding_api_key or ""
    except Exception:
        return ""


def preview(content: str, limit: int = PREVIEW_CHARS) -> str:
    """压成一行短预览：换行和连续空白收成一个空格。"""
    flattened = re.sub(r"\s+", " ", content).strip()
    return flattened if len(flattened) <= limit else flattened[:limit] + "…"


async def run_probes() -> int:
    total = await count_searchable_chunks()
    print("知识检索验证")
    print("=" * 78)
    print(f"可检索切片数  {total}")

    if total == 0:
        print()
        print("知识库为空（knowledge_chunks 里没有 embedding 非空的切片）。")
        print("请先运行入库脚本：python backend/scripts/ingest_knowledge.py")
        return 1

    print(f"每个问题取 top-{TOP_K}，共 {len(PROBE_QUESTIONS)} 个问题")
    print()

    misses = 0

    for index, probe in enumerate(PROBE_QUESTIONS, start=1):
        print("-" * 78)
        print(f"[{index}] {probe.question}")
        print(f"    预期来源  {probe.expected_source_file}")

        results = await search_knowledge(probe.question, top_k=TOP_K)

        if not results:
            print("    ！没有召回任何切片。")
            misses += 1
            continue

        for rank, result in enumerate(results, start=1):
            marker = "★" if result.source_file == probe.expected_source_file else " "
            print(
                f"  {marker} #{rank}  {result.source_file} / {result.section_title}"
            )
            print(
                f"        distance {result.distance:.4f}"
                f"   similarity {result.similarity:.4f}"
                f"   chunk #{result.chunk_index}"
            )
            print(f"        {preview(result.content)}")

        hit_ranks = [
            rank
            for rank, result in enumerate(results, start=1)
            if result.source_file == probe.expected_source_file
        ]
        if hit_ranks:
            print(f"    ✅ 预期来源命中，最佳排名 第 {hit_ranks[0]} 位")
        else:
            print("    ❌ 预期来源没进前 3 —— 需要检查切片或 embedding")
            misses += 1
        print()

    print("=" * 78)
    print(f"命中 {len(PROBE_QUESTIONS) - misses} / {len(PROBE_QUESTIONS)} 个问题")
    if misses == 0:
        print("全部命中前 3 —— 检索层可用。")
    else:
        print("有未命中的问题：先看该小节的切片是否完整、标题前缀是否有区分度，")
        print("再考虑是不是问题措辞与文档用词差得太远（例如简称对全称）。")
    return 0


async def main() -> int:
    try:
        return await run_probes()
    except AppError as error:
        print("知识检索验证失败（配置问题）")
        print(f"  {redact_secret(str(error), known_secret())}")
        return 1
    except Exception as error:
        # 第三方异常原文不一定干净，先清洗再打印
        print("知识检索验证失败")
        print(f"  {type(error).__name__}: {redact_secret(str(error), known_secret())}")
        return 1
    finally:
        await dispose_engine()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
