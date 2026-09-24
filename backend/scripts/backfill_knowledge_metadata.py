"""回填知识切片的检索元数据：为已有切片生成 keywords / aliases / enriched search_text。

用法（在 backend/ 或项目根目录下执行都可以）：

    python backend/scripts/backfill_knowledge_metadata.py --dry-run
    cd backend && python scripts/backfill_knowledge_metadata.py --dry-run

    # 只看某一批（控制模型费用）
    python backend/scripts/backfill_knowledge_metadata.py --limit 5

    # 只处理一份文档
    python backend/scripts/backfill_knowledge_metadata.py --source-file retail_metrics.md

    # 已有元数据的也重新提取一遍
    python backend/scripts/backfill_knowledge_metadata.py --refresh

## 怎么判断「这条切片还没处理过」

**不看 keywords 和 aliases 是否为空**。模型完全可能合法地返回两个空数组
（这段正文确实没有值得收录的概念），那种切片也是处理过的——用空数组判断
会让它们每次都被重复处理，白花钱。

判据是 search_text 本身：只要它还等于

    build_base_search_text(文档标题, 小节标题, 正文)

就说明元数据提取还没成功跑过。提取成功后写进去的 search_text 一定带
「关键词：」「同义表达：」两个标记（哪怕标记后面是空的），因此**不可能**
等于基础版本。这也正是那两个标记必须始终保留的原因。

## 幂等

第二次运行没有待处理项，因为第一次写进去的 search_text 已经是 enriched 版本。
--refresh 会绕过这个判断，重新提取全部（或指定范围内的）切片。

## 失败怎么办

单条提取失败时**保持该行原值**，不写入。这样下次运行它仍然是待处理状态，
可以重试；反过来把「失败」写成一份空元数据，下次运行就再也认不出它了。

- 提取器返回 extraction_succeeded=False（模型超时、限流、输出畸形）→ 记为 failed，不写；
- 提取器直接抛异常（输入为空等）→ 记为 failed，不写，并且只记异常类名。

## 事务与网络调用

**先全部提取，再开事务写**：一个批次一次事务，事务里只有 UPDATE 语句，
没有网络调用。这和入库流程（embedding 在事务里）相反，是有意的——
批量回填可能跑几十次模型调用，把事务开着等它们会把锁持有多长时间完全不可控。

输出只含计数、耗时和文件名，不含正文、不含向量、不含密钥。
"""

import argparse
import asyncio
import logging
import sys
import time
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

# 直接以 `python scripts/backfill_knowledge_metadata.py` 运行时，sys.path[0] 是 scripts/
# 而不是 backend/，会导致 `import app` 失败。与 seed / ingest 脚本同一处理方式。
BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from sqlalchemy import select, update  # noqa: E402

from app.core.config import get_settings  # noqa: E402
from app.core.exceptions import AppError  # noqa: E402
from app.models.knowledge import KnowledgeChunk as KnowledgeChunkRow  # noqa: E402
from app.models.knowledge import KnowledgeDocument  # noqa: E402
from app.repositories.database import dispose_engine, get_connection, get_engine  # noqa: E402
from app.services.embedding import redact_secret  # noqa: E402
from app.services.knowledge_metadata import (  # noqa: E402
    KnowledgeSearchMetadata,
    build_base_search_text,
    extract_search_metadata,
)

# 每批处理多少条。一个批次一次事务，批太大锁持有时长上去了，
# 批太小事务开销和往返次数都浪费。10 条与入库的 embedding 批大小一致。
BATCH_SIZE = 10

logger = logging.getLogger(__name__)

# 提取器的调用签名：三个字符串 → 元数据。默认是生产实现，
# 测试注入替身来断掉网络。
Extractor = Callable[[str, str, str], Awaitable[KnowledgeSearchMetadata]]


@dataclass(frozen=True)
class PendingChunk:
    """一条候选切片。只带提取需要的字段和判断待处理所需的 search_text。"""

    chunk_id: int
    source_file: str
    document_title: str
    section_title: str
    content: str
    search_text: str

    @property
    def base_search_text(self) -> str:
        return build_base_search_text(self.document_title, self.section_title, self.content)

    @property
    def is_pending(self) -> bool:
        """这条切片是否还没处理过。判据见模块说明。"""
        return self.search_text == self.base_search_text


@dataclass(frozen=True)
class BackfillSummary:
    scanned: int
    updated: int
    skipped: int
    failed: int
    elapsed_seconds: float
    dry_run: bool
    pending: int
    pending_documents: int
    pending_by_source_file: tuple[tuple[str, int], ...]

    def as_lines(self) -> list[tuple[str, str]]:
        """给脚本打印用的 (字段名, 值) 列表，字段顺序稳定便于对比两次运行。"""
        return [
            ("scanned", str(self.scanned)),
            ("updated", str(self.updated)),
            ("skipped", str(self.skipped)),
            ("failed", str(self.failed)),
            ("elapsed_seconds", f"{self.elapsed_seconds:.2f}"),
        ]


# --------------------------------------------------------------------------
# 纯函数
# --------------------------------------------------------------------------


def positive_int(value: str) -> int:
    """argparse 用的正整数校验。非法时以退出码 2 结束，不会带着错值往下跑。"""
    try:
        number = int(value)
    except (TypeError, ValueError):
        raise argparse.ArgumentTypeError(f"必须是正整数，当前是 {value!r}") from None
    if number <= 0:
        raise argparse.ArgumentTypeError(f"必须是正整数，当前是 {number}")
    return number


def select_targets(
    rows: Sequence[PendingChunk],
    *,
    refresh: bool,
    limit: int | None,
) -> list[PendingChunk]:
    """挑出这次要处理的切片。

    默认只挑 search_text 仍是基础版本的那些（= 还没处理过）；
    refresh=True 时全部都要，用于显式重刷已有元数据。

    限流放在**筛选之后**：--limit 5 的语义是「处理 5 条待处理的」，
    而不是「在前 5 条里找待处理的」——后者在跳过很多条时可能一条也不处理。
    """
    candidates = list(rows) if refresh else [row for row in rows if row.is_pending]
    if limit is not None:
        candidates = candidates[:limit]
    return candidates


def summarize_pending(rows: Sequence[PendingChunk]) -> tuple[int, tuple[tuple[str, int], ...]]:
    """按 source_file 汇总待处理切片数，返回 (文档数, ((文件名, 切片数), ...))。

    文件名按字典序输出，两次运行的输出才可比。
    """
    counts: dict[str, int] = {}
    for row in rows:
        counts[row.source_file] = counts.get(row.source_file, 0) + 1
    return len(counts), tuple(sorted(counts.items()))


def _batches(rows: Sequence[PendingChunk], size: int) -> list[list[PendingChunk]]:
    return [list(rows[start : start + size]) for start in range(0, len(rows), size)]


def _update_statement(chunk_id: int, metadata: KnowledgeSearchMetadata):
    """按主键更新三列检索元数据。

    用 SQLAlchemy 的 Core 语句而不是手拼 SQL：语句是参数化的，
    JSONB 列的序列化也交给列类型处理（keywords / aliases 传 list，
    由 JSONB 类型自己转成 JSON 数组）。
    只写这三列，content / content_hash / embedding 等一律不碰。
    """
    table = KnowledgeChunkRow.__table__
    return (
        update(table)
        .where(table.c.id == chunk_id)
        .values(
            keywords=list(metadata.keywords),
            aliases=list(metadata.aliases),
            search_text=metadata.search_text,
        )
    )


# --------------------------------------------------------------------------
# 数据库读写
# --------------------------------------------------------------------------


def _chunk_query(*, source_file: str | None):
    """按文件名筛选用两条固定的语句，不做字符串拼接。

    不写成 `WHERE (:source_file IS NULL OR kd.source_file = :source_file)`：
    那样在传 None 时 PostgreSQL 无法推断参数类型，会直接报错。
    两条语句各自参数化，谁都拼不出注入面。
    """
    table = KnowledgeChunkRow.__table__
    document_table = KnowledgeDocument.__table__

    statement = (
        select(
            table.c.id,
            document_table.c.source_file,
            document_table.c.document_title,
            table.c.section_title,
            table.c.content,
            table.c.search_text,
        )
        .select_from(table.join(document_table, document_table.c.id == table.c.document_id))
        .order_by(table.c.id)
    )
    if source_file is not None:
        # 精确匹配文件名。不做 LIKE / 前缀匹配：--source-file 的语义是
        # 「只动这一份文档」，模糊匹配有可能顺手动到别的文档。
        statement = statement.where(document_table.c.source_file == source_file)
    return statement


async def fetch_chunks(*, source_file: str | None = None) -> list[PendingChunk]:
    """读出候选切片。只读，不开事务。"""
    statement = _chunk_query(source_file=source_file)

    async with get_connection() as connection:
        rows = (await connection.execute(statement)).mappings().all()

    return [
        PendingChunk(
            chunk_id=row["id"],
            source_file=row["source_file"],
            document_title=row["document_title"],
            section_title=row["section_title"],
            content=row["content"],
            search_text=row["search_text"],
        )
        for row in rows
    ]


async def write_batch(entries: Sequence[tuple[int, KnowledgeSearchMetadata]]) -> None:
    """一个批次一个事务。事务里只有 UPDATE，没有网络调用（理由见模块说明）。"""
    async with get_engine().begin() as connection:
        for chunk_id, metadata in entries:
            await connection.execute(_update_statement(chunk_id, metadata))


# --------------------------------------------------------------------------
# 主流程
# --------------------------------------------------------------------------


async def backfill(
    *,
    source_file: str | None = None,
    refresh: bool = False,
    limit: int | None = None,
    batch_size: int = BATCH_SIZE,
    dry_run: bool = False,
    extractor: Extractor = extract_search_metadata,
) -> BackfillSummary:
    """回填主流程。extractor 可注入，测试因此不必调真实模型。"""
    started = time.monotonic()

    rows = await fetch_chunks(source_file=source_file)
    targets = select_targets(rows, refresh=refresh, limit=limit)
    pending_documents, by_source_file = summarize_pending(targets)

    scanned = len(rows)
    updated = 0
    failed = 0

    if not dry_run:
        for batch in _batches(targets, batch_size):
            # 先把这一批的模型调用全部做完，再开事务写。
            extracted: list[tuple[int, KnowledgeSearchMetadata]] = []
            for row in batch:
                try:
                    metadata = await extractor(
                        row.document_title, row.section_title, row.content
                    )
                except Exception as error:  # noqa: BLE001
                    # 只记异常类名：异常正文可能带着请求头、密钥和正文片段。
                    # 也不记文件名——文件名属于用户数据。
                    logger.warning("元数据提取失败，保留原值：%s", type(error).__name__)
                    failed += 1
                    continue

                if not metadata.extraction_succeeded:
                    # 模型没给出可用结果。同样保留原值：写进去也等于什么都没写，
                    # 却会让下一次运行以为这条已经处理完了。
                    failed += 1
                    continue

                extracted.append((row.chunk_id, metadata))

            if extracted:
                await write_batch(extracted)
                updated += len(extracted)

    elapsed = time.monotonic() - started

    return BackfillSummary(
        scanned=scanned,
        updated=updated,
        skipped=scanned - len(targets),
        failed=failed,
        elapsed_seconds=elapsed,
        dry_run=dry_run,
        pending=len(targets),
        pending_documents=pending_documents,
        pending_by_source_file=by_source_file,
    )


# --------------------------------------------------------------------------
# 命令行
# --------------------------------------------------------------------------


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="为已有知识切片回填检索元数据（keywords / aliases / search_text）。",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="只统计待处理的数量，不调用模型、不写数据库",
    )
    parser.add_argument(
        "--limit",
        type=positive_int,
        default=None,
        help="最多处理 N 个切片（正整数），用于控制模型费用",
    )
    parser.add_argument(
        "--source-file",
        default=None,
        help="只处理这一份文档（精确匹配文件名）",
    )
    parser.add_argument(
        "--refresh",
        action="store_true",
        help="已有元数据的切片也重新提取",
    )
    parser.add_argument(
        "--batch-size",
        type=positive_int,
        default=BATCH_SIZE,
        help=f"每批处理多少条，每批一个事务（默认 {BATCH_SIZE}）",
    )
    return parser.parse_args(argv)


def print_summary(summary: BackfillSummary, *, args: argparse.Namespace) -> None:
    print("知识切片元数据回填" + ("（dry-run，未写入）" if summary.dry_run else ""))
    print("=" * 52)
    if args.source_file:
        print(f"  只处理文件  {args.source_file}")
    if args.limit:
        print(f"  本次上限    {args.limit}")
    if args.refresh:
        print("  模式        重刷已有元数据")
    print("-" * 52)
    for name, value in summary.as_lines():
        print(f"  {name:<20} {value}")
    print("-" * 52)

    if summary.dry_run:
        print(f"待处理切片 {summary.pending} 条，分布在 {summary.pending_documents} 份文档：")
        for source_file, count in summary.pending_by_source_file:
            print(f"  {source_file:<32} {count}")
        print("dry-run 结束：没有调用模型，也没有写数据库。")
        return

    if summary.pending == 0:
        print("没有待处理项 —— 幂等生效，所有切片的元数据都已就绪。")
    else:
        print(
            f"本次处理 {summary.pending} 条，写入 {summary.updated} 条，"
            f"失败 {summary.failed} 条。"
        )
        if summary.failed:
            print("失败的行保持原值，下次运行会重试。")


async def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    try:
        summary = await backfill(
            source_file=args.source_file,
            refresh=args.refresh,
            limit=args.limit,
            batch_size=args.batch_size,
            dry_run=args.dry_run,
        )
    except AppError as error:
        # 配置类错误：消息本身已经不含密钥，但仍统一过一遍清洗
        print("知识切片元数据回填失败（配置问题）")
        print(f"  {redact_secret(str(error), known_secret())}")
        return 1
    except Exception as error:
        # 第三方 SDK 的异常原文不一定干净，先清洗再打印
        print("知识切片元数据回填失败")
        print(f"  {type(error).__name__}: {redact_secret(str(error), known_secret())}")
        return 1
    finally:
        await dispose_engine()

    print_summary(summary, args=args)
    return 0


def known_secret() -> str:
    """尽力取出密钥用于输出清洗。取不到就返回空串，绝不因为清洗再抛一次异常。"""
    try:
        return get_settings().openai_api_key or ""
    except Exception:
        return ""


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
