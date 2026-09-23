"""知识文档入库的测试。

**本文件不连接 PostgreSQL，也不调用真实 embedding 接口。**
两个外部依赖都被替身换掉：
- `FakeStore` 顶替 `PostgresKnowledgeStore`——幂等逻辑是纯业务规则，
  用内存里的字典就能验证，不必为它起一个真库；
- `FakeEmbedder` 顶替 `embed_texts`——它记录每次收到的文本，
  于是「第二次运行到底有没有再调 embedding」这件事可以被直接断言。

另有一组测试用 `RecordingConnection` 接住 `PostgresKnowledgeStore` 发出的 SQL，
断言它只碰 knowledge_documents / knowledge_chunks——这是「不写业务表」最硬的证据，
比读源码找关键词可靠。

保持项目约定：pytest 不需要 PostgreSQL。
"""

import ast
import asyncio
import importlib.util
import pathlib
import textwrap

import pytest

from app.core.config import EmbeddingSettings
from app.services import knowledge_ingestion
from app.services.document_normalization import (
    EmptyDocumentError,
    UnsupportedDocumentTypeError,
)
from app.services.knowledge_chunking import load_knowledge_chunks
from app.services.knowledge_ingestion import (
    ExistingChunk,
    ExistingDocument,
    PostgresKnowledgeStore,
    build_plans,
    document_content_hash,
    group_chunks_by_source_file,
    ingest_knowledge,
    ingest_knowledge_document_from_content,
    pending_embedding_texts,
    plan_document,
)

BACKEND_DIR = pathlib.Path(__file__).resolve().parents[1]
REAL_DOCS_DIR = BACKEND_DIR / "knowledge_seed" / "retail"
INGEST_SCRIPT = BACKEND_DIR / "scripts" / "ingest_knowledge.py"

DIMENSION = 1024
MODEL = "text-embedding-v4"
FAKE_KEY = "sk-fake-embedding-key-for-tests-0123456789"

# 业务表名：任何一条语句碰到它们都说明越界了
BUSINESS_TABLES = {"customers", "products", "regions", "date_dim", "orders", "alembic_version"}
KNOWLEDGE_TABLES = {"knowledge_documents", "knowledge_chunks"}


# --------------------------------------------------------------------------
# 替身
# --------------------------------------------------------------------------


def make_embedding_settings(**overrides) -> EmbeddingSettings:
    values = {
        "provider": "dashscope",
        "model": MODEL,
        "dimension": DIMENSION,
        "base_url": "https://example.invalid/v1",
        "api_key": FAKE_KEY,
    }
    values.update(overrides)
    return EmbeddingSettings(**values)


class FakeEmbedder:
    """记录每次收到的文本批次，返回固定维度的可辨识向量。"""

    def __init__(self, dimension: int = DIMENSION) -> None:
        self.dimension = dimension
        self.calls: list[list[str]] = []

    @property
    def total_texts(self) -> int:
        return sum(len(batch) for batch in self.calls)

    async def __call__(self, texts):
        batch = list(texts)
        self.calls.append(batch)
        return (
            [[0.25] * self.dimension for _ in batch],
            make_embedding_settings(dimension=self.dimension),
        )


class FakeStore:
    """内存版存储，行为对齐 PostgreSQL 实现：insert 分配新 id，update 覆盖切片。"""

    def __init__(self) -> None:
        self.documents: dict[str, ExistingDocument] = {}
        self.applied: list[tuple[str, bool]] = []
        self._next_id = 1

    async def load_existing(self, source_files):
        return {
            name: self.documents[name] for name in source_files if name in self.documents
        }

    async def apply(self, writes):
        for write in writes:
            if write.is_update:
                document_id = write.document_id
            else:
                document_id = self._next_id
                self._next_id += 1

            self.applied.append((write.source_file, write.is_update))
            self.documents[write.source_file] = ExistingDocument(
                id=document_id,
                content_hash=write.content_hash,
                chunks=tuple(
                    ExistingChunk(
                        chunk_index=record.chunk.chunk_index,
                        content_hash=record.chunk.content_hash,
                        embedding=record.embedding,
                        embedding_model=record.embedding_model,
                    )
                    for record in write.records
                ),
            )

    def chunk_count(self, source_file: str) -> int:
        return len(self.documents[source_file].chunks)


def write_doc(directory: pathlib.Path, name: str, text: str) -> pathlib.Path:
    path = directory / name
    path.write_text(textwrap.dedent(text).lstrip("\n"), encoding="utf-8")
    return path


@pytest.fixture
def docs(tmp_path) -> pathlib.Path:
    """两份合成文档：a.md 两个小节，b.md 一个小节。共 3 个切片。"""
    write_doc(tmp_path, "a.md", """
        # 指标口径

        ## 1. 销售额

        销售额取 `orders.net_amount`。

        ## 2. 订单数

        订单数用 `COUNT(DISTINCT orders.order_no)`。
    """)
    write_doc(tmp_path, "b.md", """
        # 会员规则

        ## 1. 复购率

        复购率按客户在周期内是否多次下单计算。
    """)
    return tmp_path


async def run_ingest(directory, store, embedder, **kwargs):
    return await ingest_knowledge(
        directory,
        store=store,
        embedder=embedder,
        embedding_model=MODEL,
        **kwargs,
    )


# --------------------------------------------------------------------------
# 第一次运行：全新入库
# --------------------------------------------------------------------------


def test_first_run_inserts_every_document_and_chunk(docs):
    store, embedder = FakeStore(), FakeEmbedder()

    summary = asyncio.run(run_ingest(docs, store, embedder))

    assert summary.scanned_documents == 2
    assert summary.scanned_chunks == 3
    assert summary.inserted_documents == 2
    assert summary.updated_documents == 0
    assert summary.skipped_documents == 0
    assert summary.inserted_chunks == 3
    assert summary.embedded_chunks == 3
    assert summary.status == "ok"

    assert set(store.documents) == {"a.md", "b.md"}
    assert store.chunk_count("a.md") == 2
    assert store.chunk_count("b.md") == 1


def test_first_run_writes_embeddings_and_model_name(docs):
    store, embedder = FakeStore(), FakeEmbedder()

    asyncio.run(run_ingest(docs, store, embedder))

    for document in store.documents.values():
        for chunk in document.chunks:
            assert chunk.embedding is not None
            assert len(chunk.embedding) == DIMENSION
            assert chunk.embedding_model == MODEL


def test_embedding_is_requested_for_content_for_embedding(docs):
    """送进 embedding 的必须是带标题上下文的那个字段，不是裸正文。"""
    store, embedder = FakeStore(), FakeEmbedder()

    asyncio.run(run_ingest(docs, store, embedder))

    sent = [text for batch in embedder.calls for text in batch]
    assert len(sent) == 3
    assert all(text.startswith("文档：") for text in sent)
    assert any("小节：销售额" in text for text in sent)


def test_embedding_calls_are_batched(docs):
    """批量调用：3 个切片、批大小 2，应当是 2 次请求而不是 3 次。"""
    store, embedder = FakeStore(), FakeEmbedder()

    asyncio.run(run_ingest(docs, store, embedder, batch_size=2))

    assert len(embedder.calls) == 2
    assert [len(batch) for batch in embedder.calls] == [2, 1]


# --------------------------------------------------------------------------
# 第二次运行：幂等
# --------------------------------------------------------------------------


def test_second_run_skips_everything_and_never_calls_embedding(docs):
    store, first_embedder = FakeStore(), FakeEmbedder()
    asyncio.run(run_ingest(docs, store, first_embedder))

    second_embedder = FakeEmbedder()
    summary = asyncio.run(run_ingest(docs, store, second_embedder))

    assert summary.skipped_documents == 2
    assert summary.inserted_documents == 0
    assert summary.updated_documents == 0
    assert summary.inserted_chunks == 0
    assert summary.embedded_chunks == 0

    # 这是整个脚本最值钱的一条断言：第二次运行一次 API 都没调
    assert second_embedder.calls == []
    assert store.applied.count(("a.md", False)) == 1  # 仍然只有第一次那一次写入


def test_second_run_keeps_the_same_document_ids(docs):
    store = FakeStore()
    asyncio.run(run_ingest(docs, store, FakeEmbedder()))
    ids_after_first = {name: doc.id for name, doc in store.documents.items()}

    asyncio.run(run_ingest(docs, store, FakeEmbedder()))

    assert {name: doc.id for name, doc in store.documents.items()} == ids_after_first


def test_dry_run_writes_nothing_and_calls_no_api(docs):
    store, embedder = FakeStore(), FakeEmbedder()

    summary = asyncio.run(run_ingest(docs, store, embedder, dry_run=True))

    assert summary.status == "dry-run"
    assert summary.inserted_documents == 2
    assert summary.embedded_chunks == 3  # 报告「将要算 3 条」，但没有真的算
    assert embedder.calls == []
    assert store.documents == {}


# --------------------------------------------------------------------------
# 文档变化：只重算变化的部分
# --------------------------------------------------------------------------


def test_changed_document_is_updated_not_reinserted(docs):
    store = FakeStore()
    asyncio.run(run_ingest(docs, store, FakeEmbedder()))
    original_id = store.documents["a.md"].id

    # 只改 a.md 的第二个小节
    write_doc(docs, "a.md", """
        # 指标口径

        ## 1. 销售额

        销售额取 `orders.net_amount`。

        ## 2. 订单数

        订单数改用 `COUNT(DISTINCT orders.order_no)`，并明确去重口径。
    """)

    embedder = FakeEmbedder()
    summary = asyncio.run(run_ingest(docs, store, embedder))

    assert summary.updated_documents == 1
    assert summary.skipped_documents == 1  # b.md 没动
    assert summary.inserted_documents == 0
    assert store.documents["a.md"].id == original_id  # 是更新，不是新建
    assert store.chunk_count("a.md") == 2


def test_only_the_changed_chunk_is_reembedded(docs):
    """这是省钱的关键：改一节不该把整个文档重算一遍。"""
    store = FakeStore()
    asyncio.run(run_ingest(docs, store, FakeEmbedder()))

    write_doc(docs, "a.md", """
        # 指标口径

        ## 1. 销售额

        销售额取 `orders.net_amount`。

        ## 2. 订单数

        官网口径：订单数用 `COUNT(DISTINCT orders.order_no)`。
    """)

    embedder = FakeEmbedder()
    summary = asyncio.run(run_ingest(docs, store, embedder))

    # a.md 只有「订单数」那一节变了 → 只算 1 条，而不是 2 条
    assert summary.embedded_chunks == 1
    assert embedder.total_texts == 1
    assert "小节：订单数" in embedder.calls[0][0]


def test_unchanged_chunks_keep_their_reused_embedding(docs):
    store = FakeStore()
    asyncio.run(run_ingest(docs, store, FakeEmbedder()))

    write_doc(docs, "a.md", """
        # 指标口径

        ## 1. 销售额

        销售额取 `orders.net_amount`。

        ## 2. 订单数

        补充一句说明。订单数用 `COUNT(DISTINCT orders.order_no)`。
    """)
    asyncio.run(run_ingest(docs, store, FakeEmbedder()))

    # 「销售额」那一节的 hash 没变，仍然拿得到向量
    sales_chunk = next(c for c in store.documents["a.md"].chunks if c.chunk_index == 0)
    assert sales_chunk.embedding is not None
    assert sales_chunk.embedding_model == MODEL


def test_embedding_is_recomputed_when_the_model_changed(docs):
    """换 embedding 模型后旧向量不可比，必须重算——同一模型是复用的前提。"""
    store = FakeStore()
    asyncio.run(run_ingest(docs, store, FakeEmbedder()))
    # 手工把库里记录的模型改成别的，模拟「上次是另一个模型算的」
    store.documents["a.md"] = ExistingDocument(
        id=store.documents["a.md"].id,
        content_hash=store.documents["a.md"].content_hash,
        chunks=tuple(
            ExistingChunk(
                chunk_index=c.chunk_index,
                content_hash=c.content_hash,
                embedding=c.embedding,
                embedding_model="some-old-model",
            )
            for c in store.documents["a.md"].chunks
        ),
    )
    # 让整篇 hash 变化，才会走到「按切片找可复用向量」那一步
    store.documents["a.md"] = ExistingDocument(
        id=store.documents["a.md"].id,
        content_hash="stale-hash-forces-update",
        chunks=store.documents["a.md"].chunks,
    )

    embedder = FakeEmbedder()
    summary = asyncio.run(run_ingest(docs, store, embedder))

    assert summary.updated_documents == 1
    # 两个切片都要重算，因为库里那份不是当前模型算的
    assert summary.embedded_chunks == 2


def test_removed_section_shrinks_the_document(docs):
    store = FakeStore()
    asyncio.run(run_ingest(docs, store, FakeEmbedder()))

    write_doc(docs, "a.md", """
        # 指标口径

        ## 1. 销售额

        销售额取 `orders.net_amount`。
    """)
    summary = asyncio.run(run_ingest(docs, store, FakeEmbedder()))

    assert summary.updated_documents == 1
    assert store.chunk_count("a.md") == 1


# --------------------------------------------------------------------------
# 纯函数
# --------------------------------------------------------------------------


def test_document_hash_is_stable_and_order_sensitive():
    grouped = group_chunks_by_source_file(load_knowledge_chunks(REAL_DOCS_DIR))
    only_one_file = next(iter(grouped.values()))

    assert document_content_hash(only_one_file) == document_content_hash(only_one_file)
    # 顺序变了（这里用反转模拟），hash 就该变
    assert document_content_hash(only_one_file) != document_content_hash(
        list(reversed(only_one_file))
    )


def test_separator_prevents_concatenation_collisions():
    """用 '\\n' 分隔而不是首尾相接，避免 ('ab','c') 和 ('a','bc') 算出同一个值。"""

    class FakeChunk:
        def __init__(self, content_hash):
            self.content_hash = content_hash

    left = document_content_hash([FakeChunk("ab"), FakeChunk("c")])
    right = document_content_hash([FakeChunk("a"), FakeChunk("bc")])

    assert left != right


def test_plan_for_missing_document_is_insert(docs):
    chunks = group_chunks_by_source_file(load_knowledge_chunks(docs))["a.md"]

    plan = plan_document(
        source_file="a.md", chunks=chunks, existing=None, embedding_model=MODEL
    )

    assert plan.action == "insert"
    assert len(plan.chunks_to_embed) == 2
    assert pending_embedding_texts([plan]) == [c.content_for_embedding for c in chunks]


def test_plan_for_unchanged_document_is_skip(docs):
    chunks = group_chunks_by_source_file(load_knowledge_chunks(docs))["a.md"]
    existing = ExistingDocument(
        id=1,
        content_hash=document_content_hash(chunks),
        chunks=tuple(
            ExistingChunk(
                chunk_index=c.chunk_index,
                content_hash=c.content_hash,
                embedding=[0.5] * DIMENSION,
                embedding_model=MODEL,
            )
            for c in chunks
        ),
    )

    plan = plan_document(
        source_file="a.md", chunks=chunks, existing=existing, embedding_model=MODEL
    )

    assert plan.action == "skip"
    assert plan.chunks == ()
    assert pending_embedding_texts([plan]) == []


def test_empty_document_is_rejected():
    with pytest.raises(ValueError):
        plan_document(source_file="x.md", chunks=[], existing=None, embedding_model=MODEL)


def test_build_plans_preserves_file_order(docs):
    grouped = group_chunks_by_source_file(load_knowledge_chunks(docs))

    plans = build_plans(grouped_chunks=grouped, existing_documents={}, embedding_model=MODEL)

    assert [plan.source_file for plan in plans] == list(grouped)


# --------------------------------------------------------------------------
# 只写知识库表：用假连接接住真实 SQL
# --------------------------------------------------------------------------


class _EmptyResult:
    def mappings(self):
        return self

    def all(self):
        return []

    def scalar_one(self):
        return 1


class RecordingConnection:
    """不连库，只把 PostgresKnowledgeStore 发出的语句记下来。"""

    def __init__(self) -> None:
        self.statements: list[str] = []

    async def execute(self, statement, parameters=None):
        self.statements.append(str(statement))
        return _EmptyResult()


def _tables_touched(statements: list[str]) -> set[str]:
    mentioned: set[str] = set()
    for statement in statements:
        for table in BUSINESS_TABLES | KNOWLEDGE_TABLES:
            # 用带边界的匹配，避免 "orders" 命中 "knowledge_chunks_orders" 之类
            if f" {table}" in statement or f'"{table}"' in statement:
                mentioned.add(table)
    return mentioned


def test_load_existing_only_reads_knowledge_tables():
    connection = RecordingConnection()
    store = PostgresKnowledgeStore(connection)

    asyncio.run(store.load_existing(["a.md"]))
    asyncio.run(store.load_existing([]))  # 空输入不应发任何语句

    touched = _tables_touched(connection.statements)
    assert touched <= KNOWLEDGE_TABLES
    assert not touched & BUSINESS_TABLES
    assert all("SELECT" in statement.upper() for statement in connection.statements)


def test_apply_only_writes_knowledge_tables(tmp_path):
    from app.services.knowledge_ingestion import ChunkRecord, DocumentWrite

    chunks = group_chunks_by_source_file(load_knowledge_chunks(REAL_DOCS_DIR))[
        "retail_metrics.md"
    ]
    write = DocumentWrite(
        source_file="retail_metrics.md",
        document_title=chunks[0].document_title,
        content_hash="hash",
        is_update=False,
        document_id=None,
        records=tuple(
            ChunkRecord(chunk=c, embedding=[0.1] * DIMENSION, embedding_model=MODEL)
            for c in chunks[:2]
        ),
    )

    connection = RecordingConnection()
    asyncio.run(PostgresKnowledgeStore(connection).apply([write]))

    touched = _tables_touched(connection.statements)
    assert touched <= KNOWLEDGE_TABLES
    assert not touched & BUSINESS_TABLES

    joined = " ".join(connection.statements).upper()
    assert "INSERT" in joined
    assert all(
        keyword not in joined
        for keyword in ("DROP TABLE", "TRUNCATE", "ALTER TABLE", "CREATE INDEX")
    )


def test_apply_for_update_deletes_chunks_before_reinserting():
    from app.services.knowledge_ingestion import ChunkRecord, DocumentWrite

    chunks = group_chunks_by_source_file(load_knowledge_chunks(REAL_DOCS_DIR))[
        "retail_metrics.md"
    ]
    write = DocumentWrite(
        source_file="retail_metrics.md",
        document_title=chunks[0].document_title,
        content_hash="hash",
        is_update=True,
        document_id=7,
        records=tuple(
            ChunkRecord(chunk=c, embedding=[0.1] * DIMENSION, embedding_model=MODEL)
            for c in chunks[:1]
        ),
    )

    connection = RecordingConnection()
    asyncio.run(PostgresKnowledgeStore(connection).apply([write]))

    joined = " ".join(connection.statements).upper()
    assert "DELETE" in joined
    assert "UPDATE" in joined
    assert "INSERT" in joined
    # 删除必须发生在插入之前，否则新切片会被自己刚插的内容顶掉
    assert joined.index("DELETE") < joined.index("INSERT")


# --------------------------------------------------------------------------
# 不引入 embedding 之外的外部系统 / 不泄漏密钥
# --------------------------------------------------------------------------


def test_ingestion_module_does_not_import_retail_models():
    """入库模块只该碰知识库两张表，连 import 都不该碰零售模型。"""
    tree = ast.parse(
        pathlib.Path(knowledge_ingestion.__file__).read_text(encoding="utf-8")
    )
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.update(f"{node.module}.{alias.name}" for alias in node.names)

    assert not [module for module in modules if module.startswith("app.models.retail")]
    assert "app.models.knowledge.KnowledgeDocument" in modules
    assert "app.models.knowledge.KnowledgeChunk" in modules


def load_ingest_script():
    spec = importlib.util.spec_from_file_location("ingest_knowledge_script", INGEST_SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_script_failure_message_redacts_the_api_key(tmp_path, monkeypatch, capsys):
    script = load_ingest_script()
    secret = "sk-canary-leak-check-0123456789abcdef"

    monkeypatch.setattr(script, "known_secret", lambda: secret)

    async def explode(*args, **kwargs):
        raise RuntimeError(f"upstream rejected api_key={secret} with 401")

    async def noop():
        return None

    monkeypatch.setattr(script, "run", explode)
    monkeypatch.setattr(script, "dispose_engine", noop)

    exit_code = asyncio.run(script.main([str(tmp_path)]))

    output = capsys.readouterr().out
    assert exit_code == 1
    assert secret not in output
    assert "sk-" not in output
    assert "知识文档入库失败" in output


def test_script_reports_missing_directory(tmp_path, capsys):
    script = load_ingest_script()

    exit_code = asyncio.run(script.main([str(tmp_path / "not-here")]))

    assert exit_code == 1
    assert "目录不存在" in capsys.readouterr().out


def test_script_accepts_relative_and_absolute_paths():
    script = load_ingest_script()

    assert script.parse_args([]).directory == str(script.DEFAULT_DIRECTORY)
    assert script.parse_args(["--dry-run"]).dry_run is True
    assert script.parse_args(["some/dir"]).directory == "some/dir"


# --------------------------------------------------------------------------
# 对真实知识库文档跑一遍（仍然不碰数据库、不碰网络）
# --------------------------------------------------------------------------


def test_real_documents_ingest_then_skip():
    """真实 5 份文档：第一次全部插入，第二次全部跳过且不调 embedding。"""
    store = FakeStore()

    first_embedder = FakeEmbedder()
    first = asyncio.run(run_ingest(REAL_DOCS_DIR, store, first_embedder))

    real_chunks = load_knowledge_chunks(REAL_DOCS_DIR)
    assert first.scanned_documents == 5
    assert first.scanned_chunks == len(real_chunks)
    assert first.inserted_documents == 5
    assert first.inserted_chunks == len(real_chunks)
    assert first.embedded_chunks == len(real_chunks)
    assert first_embedder.total_texts == len(real_chunks)

    second_embedder = FakeEmbedder()
    second = asyncio.run(run_ingest(REAL_DOCS_DIR, store, second_embedder))

    assert second.skipped_documents == 5
    assert second.inserted_documents == 0
    assert second.inserted_chunks == 0
    assert second.embedded_chunks == 0
    assert second_embedder.calls == []


# ==========================================================================
# 从「内容」入库（上传那条路）
#
# 和上面「扫目录」共用同一段内核，所以幂等、向量复用这些行为应当完全一致。
# 这一节主要盯两件目录那条路没有的事：
# 1. 类型与内容的归一化会不会被正确执行（BOM、CRLF、file_type）；
# 2. 返回的是**单份文档**的结果（action / document_id），不是整批汇总。
# ==========================================================================


class RecordingStore(FakeStore):
    """在 FakeStore 基础上记下每次写入的 DocumentWrite。

    FakeStore 只留了 id 和 hash，断言不了 document_title / content 这些语义字段。
    这里把原始写入对象存下来，让「标题覆盖生效了没有」这类断言成为可能。
    """

    def __init__(self) -> None:
        super().__init__()
        self.writes: list = []

    async def apply(self, writes):
        self.writes.extend(writes)
        await super().apply(writes)


async def ingest_content(
    *,
    source_file: str,
    content: str,
    file_type: str = "md",
    store,
    embedder,
    **kwargs,
):
    return await ingest_knowledge_document_from_content(
        source_file=source_file,
        content=content,
        file_type=file_type,
        store=store,
        embedder=embedder,
        embedding_model=MODEL,
        **kwargs,
    )


MARKDOWN_DOC = """# 订单口径

## 1. 订单数

订单数用 COUNT(DISTINCT order_no)。

## 2. 客单价

客单价 = 销售额 / 订单数。
"""


def test_content_ingestion_inserts_a_new_document():
    store, embedder = RecordingStore(), FakeEmbedder()

    result = asyncio.run(
        ingest_content(
            source_file="orders.md", content=MARKDOWN_DOC, store=store, embedder=embedder
        )
    )

    assert result.action == "insert"
    assert result.source_file == "orders.md"
    assert result.chunk_count == 2
    assert result.embedded_chunks == 2
    assert result.document_id is not None
    assert result.content_hash
    assert result.dry_run is False
    assert result.written is True


def test_content_ingestion_reports_update_on_change():
    store = RecordingStore()
    asyncio.run(
        ingest_content(
            source_file="orders.md", content=MARKDOWN_DOC, store=store, embedder=FakeEmbedder()
        )
    )
    original_id = store.documents["orders.md"].id

    result = asyncio.run(
        ingest_content(
            source_file="orders.md",
            content=MARKDOWN_DOC.replace("订单数用", "订单数统一用"),
            store=store,
            embedder=FakeEmbedder(),
        )
    )

    assert result.action == "update"
    assert result.document_id == original_id  # 是更新，不是新建
    assert store.chunk_count("orders.md") == 2


def test_content_ingestion_is_idempotent_across_formatting_differences():
    """★ 归一化的意义所在：同一份内容换种换行符上传，不该被当成「变了」。

    不做归一化的话，Windows 上传（CRLF）与 Linux 上传（LF）算出的
    content_hash 不同，于是每次都判 update、每次都重算向量——真花钱，
    而且内容一个字都没改。
    """
    store = RecordingStore()
    asyncio.run(
        ingest_content(
            source_file="orders.md", content=MARKDOWN_DOC, store=store, embedder=FakeEmbedder()
        )
    )

    crlf_version = "﻿" + MARKDOWN_DOC.replace("\n", "\r\n")
    second_embedder = FakeEmbedder()

    result = asyncio.run(
        ingest_content(
            source_file="orders.md",
            content=crlf_version,
            file_type=".MD",  # 类型写法也不同
            store=store,
            embedder=second_embedder,
        )
    )

    assert result.action == "skip"
    assert result.written is False
    # 最要紧的一条：一次 embedding 都没调
    assert second_embedder.calls == []


def test_content_ingestion_respects_the_explicit_title():
    store = RecordingStore()

    asyncio.run(
        ingest_content(
            source_file="orders.md",
            content=MARKDOWN_DOC,
            store=store,
            embedder=FakeEmbedder(),
            title="订单指标口径（2025 修订版）",
        )
    )

    document = store.writes[-1]
    assert document.document_title == "订单指标口径（2025 修订版）"
    # 标题变了，进 embedding 的文本也跟着变——这正是「标题必须能覆盖」的理由
    assert "订单指标口径（2025 修订版）" in store.writes[-1].records[0].chunk.content_for_embedding


def test_changing_only_the_title_reembeds():
    """标题覆盖进 content_for_embedding，所以只改标题也该重算向量。"""
    store = RecordingStore()
    asyncio.run(
        ingest_content(
            source_file="orders.md", content=MARKDOWN_DOC, store=store, embedder=FakeEmbedder()
        )
    )

    result = asyncio.run(
        ingest_content(
            source_file="orders.md",
            content=MARKDOWN_DOC,
            title="换个标题",
            store=store,
            embedder=FakeEmbedder(),
        )
    )

    assert result.action == "update"
    assert result.embedded_chunks == 2


def test_content_ingestion_accepts_plain_text():
    store = RecordingStore()

    result = asyncio.run(
        ingest_content(
            source_file="docs/盘点规范.txt",
            content="第一条 每周一盘点。\n\n第二条 差异超过 1% 需要复核。",
            file_type="txt",
            store=store,
            embedder=FakeEmbedder(),
        )
    )

    assert result.action == "insert"
    assert result.chunk_count == 1
    record = store.writes[-1].records[0]
    assert record.chunk.section_title == "正文"
    assert record.chunk.document_title == "盘点规范"


def test_source_file_is_the_identity_not_the_content():
    """同名不同内容是更新；同内容不同名是两份文档。

    source_file 是这份文档的业务主键——上传场景里它就是文件名，
    所以「两份都叫 说明.txt 的文件」会被视为同一份的后一次覆盖，
    这是有意的（改名了就是另一份文档）。
    """
    store = RecordingStore()
    asyncio.run(
        ingest_content(
            source_file="a.md", content="# 甲\n\n## 1. 小节\n\n同样的正文。",
            store=store, embedder=FakeEmbedder(),
        )
    )
    asyncio.run(
        ingest_content(
            source_file="b.md", content="# 甲\n\n## 1. 小节\n\n同样的正文。",
            store=store, embedder=FakeEmbedder(),
        )
    )

    assert set(store.documents) == {"a.md", "b.md"}
    assert store.documents["a.md"].id != store.documents["b.md"].id


def test_content_ingestion_dry_run_writes_nothing():
    store, embedder = RecordingStore(), FakeEmbedder()

    result = asyncio.run(
        ingest_content(
            source_file="orders.md",
            content=MARKDOWN_DOC,
            store=store,
            embedder=embedder,
            dry_run=True,
        )
    )

    # action 说的是**内容层面**该做什么，dry_run 说的是**这次有没有真写**
    assert result.action == "insert"
    assert result.dry_run is True
    assert result.written is False
    assert result.document_id is None  # 没写，自然没有 id
    assert store.documents == {}
    assert store.writes == []
    assert embedder.calls == []


def test_content_ingestion_rejects_empty_content_without_touching_the_store():
    """空文档报错，而不是「成功入库 0 个切片」。

    后者会让调用方以为上传成功了，而知识库里什么都没有——
    等检索不到才发现，那时离现场已经很远。
    """
    for blank in ("", "   ", "\n\n\t\n"):
        store, embedder = RecordingStore(), FakeEmbedder()

        with pytest.raises(EmptyDocumentError):
            asyncio.run(
                ingest_content(
                    source_file="empty.md", content=blank, store=store, embedder=embedder
                )
            )

        assert store.documents == {}
        assert embedder.calls == []


def test_content_ingestion_rejects_unsupported_types_before_any_work():
    store, embedder = RecordingStore(), FakeEmbedder()

    with pytest.raises(UnsupportedDocumentTypeError):
        asyncio.run(
            ingest_content(
                source_file="report.docx",
                content="随便什么内容",
                file_type="docx",
                store=store,
                embedder=embedder,
            )
        )

    # 类型不对就该在第一步失败，不该先切出一堆东西再发现
    assert store.documents == {}
    assert embedder.calls == []


def test_content_ingestion_never_calls_embedding_for_unchanged_content():
    """再钉一次幂等的核心：第二次上传同一份文档，一次 API 都不该调。"""
    store = RecordingStore()
    asyncio.run(
        ingest_content(
            source_file="orders.md", content=MARKDOWN_DOC, store=store, embedder=FakeEmbedder()
        )
    )

    embedder = FakeEmbedder()
    asyncio.run(
        ingest_content(
            source_file="orders.md", content=MARKDOWN_DOC, store=store, embedder=embedder
        )
    )

    assert embedder.calls == []
    assert embedder.total_texts == 0


def test_content_ingestion_only_reembeds_changed_chunks():
    """改一节就只重算一节——和目录那条路一样。"""
    store = RecordingStore()
    asyncio.run(
        ingest_content(
            source_file="orders.md", content=MARKDOWN_DOC, store=store, embedder=FakeEmbedder()
        )
    )

    embedder = FakeEmbedder()
    result = asyncio.run(
        ingest_content(
            source_file="orders.md",
            content=MARKDOWN_DOC.replace(
                "客单价 = 销售额 / 订单数。", "客单价 = 销售额 / 订单数，按去重订单数计算。"
            ),
            store=store,
            embedder=embedder,
        )
    )

    assert result.embedded_chunks == 1
    assert embedder.total_texts == 1


def test_content_ingestion_rejects_non_string_content():
    store = RecordingStore()

    with pytest.raises(EmptyDocumentError):
        asyncio.run(
            ingest_content(
                source_file="a.md", content=b"\xe4\xba\x8c\xe8\xbf\x9b\xe5\x88\xb6",
                store=store, embedder=FakeEmbedder(),
            )
        )


def test_content_and_directory_paths_agree_on_the_same_document(tmp_path):
    """★ 两条入口对同一份内容必须得出同样的切片结果。

    否则「目录同步进来的文档」和「上传进来的同一份文档」会被判成
    两份不同的内容，互相覆盖、反复重算向量。
    """
    write_doc(tmp_path, "orders.md", MARKDOWN_DOC)

    directory_store = RecordingStore()
    asyncio.run(run_ingest(tmp_path, directory_store, FakeEmbedder()))

    content_store = RecordingStore()
    asyncio.run(
        ingest_content(
            source_file="orders.md",
            content=MARKDOWN_DOC,
            store=content_store,
            embedder=FakeEmbedder(),
        )
    )

    from_directory = directory_store.writes[-1]
    from_content = content_store.writes[-1]

    assert from_directory.document_title == from_content.document_title
    assert from_directory.content_hash == from_content.content_hash
    assert [r.chunk.content for r in from_directory.records] == [
        r.chunk.content for r in from_content.records
    ]


def test_injected_store_means_no_database_is_touched(monkeypatch):
    """注入 store 时**一次都不该去连数据库**。

    这条不是「间接看得出来」而已：本机数据库是开着的，测试光跑过不能证明
    它没连。这里把 get_engine 换成一调用就炸的桩——真去连就会当场失败。
    整套单元测试因此可以完全不依赖 PostgreSQL 运行。
    """

    def explode():
        raise AssertionError("注入 store 之后不该再自己去连数据库")

    monkeypatch.setattr(knowledge_ingestion, "get_engine", explode)

    store, embedder = RecordingStore(), FakeEmbedder()
    result = asyncio.run(
        ingest_content(
            source_file="orders.md", content=MARKDOWN_DOC, store=store, embedder=embedder
        )
    )

    assert result.action == "insert"


def test_content_entry_point_signature_matches_the_agreed_contract():
    """公开入口的签名就是约定的那份——四个业务参数，title 可省。"""
    import inspect

    parameters = inspect.signature(ingest_knowledge_document_from_content).parameters

    for name in ("source_file", "content", "file_type", "title"):
        assert name in parameters, name
    assert parameters["title"].default is None
    # 全部关键字传入：位置参数容易把 source_file 和 content 传反，而它们都是 str，
    # 传反了不会报错，只会安静地把正文当文件名
    assert all(
        parameters[name].kind is inspect.Parameter.KEYWORD_ONLY
        for name in ("source_file", "content", "file_type", "title")
    )


def test_directory_entry_point_still_has_its_original_signature():
    """回归：老的目录入口签名没被这次重构改掉。"""
    import inspect

    parameters = inspect.signature(ingest_knowledge).parameters

    assert "directory" in parameters
    assert all(
        parameters[name].kind is inspect.Parameter.KEYWORD_ONLY
        for name in ("store", "embedder", "embedding_model", "batch_size", "dry_run")
    )
