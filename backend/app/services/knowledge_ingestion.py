"""知识文档入库：Markdown → 切片 → 向量 → 两张知识库表。

## 幂等是怎么做到的

每次运行都重新切片、重新和库里的状态比对，再决定每个文档要做什么：

| 库里的情况 | 动作 | 是否调 embedding |
| --- | --- | --- |
| 没有这份文档 | insert | 全部切片都要算 |
| 有，且整篇 hash 没变 | skip | **一次都不调** |
| 有，但整篇 hash 变了 | update | **只算变了的切片** |

「整篇 hash」是把该文档所有切片的 content_hash 按顺序拼起来再取 sha256
（见 document_content_hash）。**为什么不用文件文本的 sha256？** 在文件里
多加一个空行、调一下缩进，文本 hash 就变了，但切片内容一模一样。
用文本 hash 会把这种改动判成「文档变了」，于是删掉 44 行再原样插回 44 行
（旧向量的 id 和 created_at 全被冲掉），而实际什么都没变。
判定的对象应该是「要写进去的东西到底变没变」——那才是这张表关心的事。

「只算变了的切片」靠 content_hash 反查：库里如果存在一条 content_hash 相同、
且是**同一个 embedding 模型**算出来的向量，就直接复用它。
同一个模型的判断不能省——换了模型之后，旧向量和新向量不在同一个语义空间里，
拿旧向量去比是错的，必须重算。

## 事务边界

整个流程（读现状 → 定计划 → 算向量 → 写库）在**一个事务**里，
所以要么全部成功，要么全部回滚，不会留下「文档写进去了、切片没有」的半截状态。

代价要说清楚：embedding 是网络调用，而这个事务在调用期间一直开着。
当前语料只有 5 个文档、44 个切片、5 次批量请求（约 3 秒），完全没问题。
但如果语料涨到几百个文档、需要几十次请求，就该改成
「先全部算完向量、再开事务写入」——那时要额外处理读与写之间别人改了库的情况。
现在没这个复杂度，就不提前引入。

## 写库方式

用 SQLAlchemy Core 语句（`insert` / `delete` / `select`），不用 ORM Session：
项目里没有 async session 工厂，而 repositories/database.py 不在本次允许改动的范围内。
Core 语句同样是全参数化的，不存在把文本拼进 SQL 的问题。
唯一的差别是 ORM 层的 `onupdate` 不会触发，所以更新 `updated_at` 时显式写 `func.now()`。

本模块不建向量索引、不做检索、不碰 retail 五张业务表。
"""

import hashlib
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal, Protocol

from sqlalchemy import delete, func, insert, select
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.config import EmbeddingSettings, get_settings
from app.models.knowledge import KnowledgeChunk as KnowledgeChunkRow
from app.models.knowledge import KnowledgeDocument
from app.services.embedding import embed_texts
from app.services.knowledge_chunking import KnowledgeChunk, load_knowledge_chunks

# 单次批量请求的切片条数。百炼 text-embedding-v4 的 input 数组有上限，
# 取 10 是保守值：比逐条调用少 90% 的请求数，又不会因为超出上限被拒。
# 44 个切片 → 5 次请求。
EMBEDDING_BATCH_SIZE = 10

# 向量列的长度。写入前校验，避免把一个 1024 维以外的向量送进数据库。
EXPECTED_DIMENSION = 1024

Action = Literal["insert", "skip", "update"]

# embedding 服务的调用签名：一批文本 → (一批向量, 配置)
Embedder = Callable[[Sequence[str]], Awaitable[tuple[list[list[float]], EmbeddingSettings]]]


# --------------------------------------------------------------------------
# 数据结构
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class ExistingChunk:
    """库里已有的一条切片（只为比对而读，不需要 content 这些大字段）。"""

    chunk_index: int
    content_hash: str
    embedding: list[float] | None
    embedding_model: str | None


@dataclass(frozen=True)
class ExistingDocument:
    id: int
    content_hash: str
    chunks: tuple[ExistingChunk, ...]


@dataclass(frozen=True)
class PlannedChunk:
    """计划里的一个切片：要么复用库里已有的向量，要么待算。"""

    chunk: KnowledgeChunk
    embedding: list[float] | None


@dataclass(frozen=True)
class DocumentPlan:
    """一个文档要做什么。skip 的文档 chunks 为空——不写任何东西。"""

    source_file: str
    document_title: str
    content_hash: str
    action: Action
    document_id: int | None
    chunks: tuple[PlannedChunk, ...]

    @property
    def chunks_to_embed(self) -> tuple[KnowledgeChunk, ...]:
        return tuple(item.chunk for item in self.chunks if item.embedding is None)


@dataclass(frozen=True)
class ChunkRecord:
    """真正要写进 knowledge_chunks 的一行。"""

    chunk: KnowledgeChunk
    embedding: list[float]
    embedding_model: str


@dataclass(frozen=True)
class DocumentWrite:
    """真正要落库的一个文档：文档行 + 它的全部切片行。"""

    source_file: str
    document_title: str
    content_hash: str
    is_update: bool
    document_id: int | None
    records: tuple[ChunkRecord, ...]


@dataclass(frozen=True)
class IngestSummary:
    scanned_documents: int
    scanned_chunks: int
    inserted_documents: int
    updated_documents: int
    skipped_documents: int
    inserted_chunks: int
    embedded_chunks: int
    elapsed_seconds: float
    status: str

    def as_lines(self) -> list[tuple[str, str]]:
        """给脚本打印用的 (字段名, 值) 列表，字段顺序稳定便于对比两次运行。"""
        return [
            ("scanned_documents", str(self.scanned_documents)),
            ("scanned_chunks", str(self.scanned_chunks)),
            ("inserted_documents", str(self.inserted_documents)),
            ("updated_documents", str(self.updated_documents)),
            ("skipped_documents", str(self.skipped_documents)),
            ("inserted_chunks", str(self.inserted_chunks)),
            ("embedded_chunks", str(self.embedded_chunks)),
            ("elapsed_seconds", f"{self.elapsed_seconds:.2f}"),
            ("status", self.status),
        ]


# --------------------------------------------------------------------------
# 纯函数：切片的整篇 hash 与入库计划
# --------------------------------------------------------------------------


def document_content_hash(chunks: Sequence[KnowledgeChunk]) -> str:
    """把一份文档所有切片的 hash 按顺序组合成整篇的 hash。

    顺序参与计算：切片顺序变了（比如文档里调整了小节位置），整篇 hash 就该变。
    这里用 '\n' 分隔而不是直接首尾相接，避免[hash('ab'), hash('c')] 和
    [hash('a'), hash('bc')] 撞成同一个值。
    """
    joined = "\n".join(chunk.content_hash for chunk in chunks)
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()


def group_chunks_by_source_file(
    chunks: Sequence[KnowledgeChunk],
) -> dict[str, list[KnowledgeChunk]]:
    """按 source_file 分组。顺序沿用 load_knowledge_chunks 给的文件顺序。"""
    grouped: dict[str, list[KnowledgeChunk]] = {}
    for chunk in chunks:
        grouped.setdefault(chunk.source_file, []).append(chunk)
    return grouped


def plan_document(
    *,
    source_file: str,
    chunks: Sequence[KnowledgeChunk],
    existing: ExistingDocument | None,
    embedding_model: str,
) -> DocumentPlan:
    """决定一个文档该 insert / skip / update，以及哪些切片的向量可以复用。"""
    if not chunks:
        raise ValueError(f"{source_file} 没有切片，不该进入入库流程。")

    document_title = chunks[0].document_title
    new_hash = document_content_hash(chunks)

    if existing is None:
        # 全新文档：每个切片都要算向量
        return DocumentPlan(
            source_file=source_file,
            document_title=document_title,
            content_hash=new_hash,
            action="insert",
            document_id=None,
            chunks=tuple(PlannedChunk(chunk=chunk, embedding=None) for chunk in chunks),
        )

    if existing.content_hash == new_hash:
        # 整篇一个字都没变：不写库、不算向量
        return DocumentPlan(
            source_file=source_file,
            document_title=document_title,
            content_hash=new_hash,
            action="skip",
            document_id=existing.id,
            chunks=(),
        )

    # 变了。按 content_hash 找回可以复用的旧向量。
    # 必须同时满足「有向量」和「是当前模型算的」——换模型后旧向量不在同一语义空间，
    # 复用它会得到一个和查询向量不可比的库。
    reusable: dict[str, list[float]] = {
        item.content_hash: item.embedding
        for item in existing.chunks
        if item.embedding is not None and item.embedding_model == embedding_model
    }

    return DocumentPlan(
        source_file=source_file,
        document_title=document_title,
        content_hash=new_hash,
        action="update",
        document_id=existing.id,
        chunks=tuple(
            PlannedChunk(chunk=chunk, embedding=reusable.get(chunk.content_hash))
            for chunk in chunks
        ),
    )


def build_plans(
    *,
    grouped_chunks: dict[str, list[KnowledgeChunk]],
    existing_documents: dict[str, ExistingDocument],
    embedding_model: str,
) -> list[DocumentPlan]:
    """为每个文档生成计划，顺序与 grouped_chunks 的插入顺序一致。"""
    return [
        plan_document(
            source_file=source_file,
            chunks=chunks,
            existing=existing_documents.get(source_file),
            embedding_model=embedding_model,
        )
        for source_file, chunks in grouped_chunks.items()
    ]


def pending_embedding_texts(plans: Sequence[DocumentPlan]) -> list[str]:
    """所有待算向量的文本，按文档顺序、切片顺序排列。

    单独抽出来是为了让「这一次到底要花多少次调用」在写库之前就能算清楚——
    也方便 dry-run 直接报告这个数字。
    """
    return [
        chunk.content_for_embedding
        for plan in plans
        for chunk in plan.chunks_to_embed
    ]


def attach_embeddings(
    plans: Sequence[DocumentPlan],
    fresh_vectors: Sequence[list[float]],
    embedding_model: str,
) -> list[DocumentWrite]:
    """把新旧向量合并成待写入的记录。

    fresh_vectors 的顺序必须与 pending_embedding_texts(plans) 一致——
    调用方按同一个顺序喂进去，这里按同样的顺序取出来。
    """
    expected = sum(len(plan.chunks_to_embed) for plan in plans)
    if len(fresh_vectors) != expected:
        raise ValueError(
            f"新算的向量条数对不上：期望 {expected} 条，实际 {len(fresh_vectors)} 条。"
        )

    writes: list[DocumentWrite] = []
    cursor = 0

    for plan in plans:
        if plan.action == "skip":
            continue

        records: list[ChunkRecord] = []
        for item in plan.chunks:
            embedding = item.embedding
            if embedding is None:
                embedding = fresh_vectors[cursor]
                cursor += 1

            if len(embedding) != EXPECTED_DIMENSION:
                raise ValueError(
                    f"{plan.source_file} 第 {item.chunk.chunk_index} 个切片维度不符："
                    f"期望 {EXPECTED_DIMENSION}，实际 {len(embedding)}。"
                )

            records.append(
                ChunkRecord(
                    chunk=item.chunk,
                    embedding=embedding,
                    embedding_model=embedding_model,
                )
            )

        writes.append(
            DocumentWrite(
                source_file=plan.source_file,
                document_title=plan.document_title,
                content_hash=plan.content_hash,
                is_update=plan.action == "update",
                document_id=plan.document_id,
                records=tuple(records),
            )
        )

    return writes


def summarize(
    *,
    plans: Sequence[DocumentPlan],
    scanned_documents: int,
    scanned_chunks: int,
    elapsed_seconds: float,
    dry_run: bool,
) -> IngestSummary:
    """把计划汇总成摘要。dry_run 时 status 明确标注，避免误读成真的写入了。"""
    inserted_documents = sum(1 for plan in plans if plan.action == "insert")
    updated_documents = sum(1 for plan in plans if plan.action == "update")
    skipped_documents = sum(1 for plan in plans if plan.action == "skip")
    inserted_chunks = sum(len(plan.chunks) for plan in plans if plan.action != "skip")
    embedded_chunks = len(pending_embedding_texts(plans))

    return IngestSummary(
        scanned_documents=scanned_documents,
        scanned_chunks=scanned_chunks,
        inserted_documents=inserted_documents,
        updated_documents=updated_documents,
        skipped_documents=skipped_documents,
        inserted_chunks=inserted_chunks,
        embedded_chunks=embedded_chunks,
        elapsed_seconds=elapsed_seconds,
        status="dry-run" if dry_run else "ok",
    )


# --------------------------------------------------------------------------
# 存储：抽象 + PostgreSQL 实现
# --------------------------------------------------------------------------


class KnowledgeStore(Protocol):
    """入库需要的两个动作。抽成协议是为了让测试能塞一个内存替身进来，
    不必为了验证「幂等」而必须有一个真 PostgreSQL。"""

    async def load_existing(
        self, source_files: Sequence[str]
    ) -> dict[str, ExistingDocument]: ...

    async def apply(self, writes: Sequence[DocumentWrite]) -> None: ...


class PostgresKnowledgeStore:
    """基于一条已有连接的实现。事务由调用方（脚本）开启，这里只发语句。"""

    def __init__(self, connection: AsyncConnection) -> None:
        self._conn = connection

    async def load_existing(
        self, source_files: Sequence[str]
    ) -> dict[str, ExistingDocument]:
        if not source_files:
            return {}

        document_table = KnowledgeDocument.__table__
        chunk_table = KnowledgeChunkRow.__table__

        document_rows = (
            await self._conn.execute(
                select(
                    document_table.c.id,
                    document_table.c.source_file,
                    document_table.c.content_hash,
                ).where(document_table.c.source_file.in_(list(source_files)))
            )
        ).mappings().all()

        if not document_rows:
            return {}

        id_by_source_file = {row["source_file"]: row["id"] for row in document_rows}

        chunk_rows = (
            await self._conn.execute(
                select(
                    chunk_table.c.document_id,
                    chunk_table.c.chunk_index,
                    chunk_table.c.content_hash,
                    chunk_table.c.embedding,
                    chunk_table.c.embedding_model,
                ).where(chunk_table.c.document_id.in_(list(id_by_source_file.values())))
            )
        ).mappings().all()

        chunks_by_document: dict[int, list[ExistingChunk]] = {}
        for row in chunk_rows:
            chunks_by_document.setdefault(row["document_id"], []).append(
                ExistingChunk(
                    chunk_index=row["chunk_index"],
                    content_hash=row["content_hash"],
                    embedding=row["embedding"],
                    embedding_model=row["embedding_model"],
                )
            )

        return {
            row["source_file"]: ExistingDocument(
                id=row["id"],
                content_hash=row["content_hash"],
                chunks=tuple(
                    sorted(
                        chunks_by_document.get(row["id"], []),
                        key=lambda item: item.chunk_index,
                    )
                ),
            )
            for row in document_rows
        }

    async def apply(self, writes: Sequence[DocumentWrite]) -> None:
        document_table = KnowledgeDocument.__table__
        chunk_table = KnowledgeChunkRow.__table__

        for write in writes:
            if write.is_update:
                document_id = write.document_id
                if document_id is None:
                    raise ValueError(f"{write.source_file} 标记为更新，却没有 document_id。")

                # 先删旧切片，再改文档行，最后插新切片。
                # 删切片而不是逐条比对更新，是因为切片位置会整体位移
                # （文档中间插一节，后面所有 chunk_index 都会变），
                # 逐条比对反而更容易写错。
                await self._conn.execute(
                    delete(chunk_table).where(chunk_table.c.document_id == document_id)
                )
                await self._conn.execute(
                    document_table.update()
                    .where(document_table.c.id == document_id)
                    .values(
                        document_title=write.document_title,
                        content_hash=write.content_hash,
                        chunk_count=len(write.records),
                        updated_at=func.now(),
                    )
                )
            else:
                result = await self._conn.execute(
                    insert(document_table)
                    .values(
                        source_file=write.source_file,
                        document_title=write.document_title,
                        content_hash=write.content_hash,
                        chunk_count=len(write.records),
                    )
                    .returning(document_table.c.id)
                )
                document_id = result.scalar_one()

            await self._conn.execute(
                insert(chunk_table),
                [
                    {
                        "document_id": document_id,
                        "section_title": record.chunk.section_title,
                        "chunk_index": record.chunk.chunk_index,
                        "content": record.chunk.content,
                        "content_for_embedding": record.chunk.content_for_embedding,
                        "content_hash": record.chunk.content_hash,
                        "estimated_token_count": record.chunk.estimated_token_count,
                        "char_count": record.chunk.char_count,
                        "embedding": record.embedding,
                        "embedding_model": record.embedding_model,
                    }
                    for record in write.records
                ],
            )


# --------------------------------------------------------------------------
# 编排
# --------------------------------------------------------------------------


async def ingest_knowledge(
    directory: Path,
    *,
    store: KnowledgeStore,
    embedder: Embedder = embed_texts,
    embedding_model: str | None = None,
    batch_size: int = EMBEDDING_BATCH_SIZE,
    dry_run: bool = False,
) -> IngestSummary:
    """把一个目录下的 Markdown 文档同步进知识库。

    dry_run=True 时只算计划、不调 embedding、不写库——用来在真正花钱之前
    确认「这次会插几行、会重算几条向量」。
    """
    started = datetime.now(timezone.utc)

    chunks = load_knowledge_chunks(directory)
    grouped = group_chunks_by_source_file(chunks)

    if embedding_model is None:
        embedding_model = get_settings().require_embedding_settings().model

    existing = await store.load_existing(list(grouped))
    plans = build_plans(
        grouped_chunks=grouped,
        existing_documents=existing,
        embedding_model=embedding_model,
    )

    if not dry_run:
        fresh_vectors = await _embed_pending(plans, embedder=embedder, batch_size=batch_size)
        writes = attach_embeddings(plans, fresh_vectors, embedding_model)
        await store.apply(writes)

    elapsed = (datetime.now(timezone.utc) - started).total_seconds()
    return summarize(
        plans=plans,
        scanned_documents=len(grouped),
        scanned_chunks=len(chunks),
        elapsed_seconds=elapsed,
        dry_run=dry_run,
    )


async def _embed_pending(
    plans: Sequence[DocumentPlan],
    *,
    embedder: Embedder,
    batch_size: int,
) -> list[list[float]]:
    """把所有待算的文本分批送给 embedding 服务，按原顺序拼回一个列表。"""
    texts = pending_embedding_texts(plans)
    if not texts:
        return []

    vectors: list[list[float]] = []
    for start in range(0, len(texts), batch_size):
        batch = texts[start : start + batch_size]
        batch_vectors, _ = await embedder(batch)
        vectors.extend(batch_vectors)

    return vectors
