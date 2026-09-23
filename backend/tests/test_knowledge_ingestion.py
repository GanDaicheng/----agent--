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
from app.services.knowledge_ingestion import (
    ExistingChunk,
    ExistingDocument,
    PostgresKnowledgeStore,
    build_plans,
    document_content_hash,
    group_chunks_by_source_file,
    ingest_knowledge,
    pending_embedding_texts,
    plan_document,
)
from app.services.knowledge_chunking import load_knowledge_chunks

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
