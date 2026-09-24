"""知识检索的测试。

**本文件不连接 PostgreSQL，也不调用真实 embedding 接口。**
两个外部依赖都注入替身：
- `FakeQueryEmbedder` 顶替 `embed_text`，并记录收到的问题文本；
- `FakeSearchConnection` 顶替数据库连接，记录发出去的 SQL 与参数、返回预设行。

`search_knowledge` 的 embedder 与 connection 都是显式参数，就是为了这个——
不必 monkeypatch 内部实现，也不必起一个真库。

保持项目约定：pytest 不需要 PostgreSQL，也不需要模型 API Key。

不做「真实模型 + 真实库」的集成测试：这类测试要花钱、要联网、
结果还会随模型版本漂移，不适合放在每次都要跑的套件里。
真实召回质量由 scripts/smoke_knowledge_search.py 人工核对。
"""

import ast
import asyncio
import importlib.util
import pathlib

import pytest

from app.core.config import EmbeddingSettings
from app.services import knowledge_search
from app.services.knowledge_search import (
    DEFAULT_TOP_K,
    EXPECTED_DIMENSION,
    MAX_TOP_K,
    MIN_TOP_K,
    SEARCH_SQL,
    ChunkContent,
    KnowledgeSearchError,
    build_chunk_content,
    build_search_result,
    connection_scope,
    count_searchable_chunks,
    normalize_query,
    search_knowledge,
    similarity_from_distance,
    to_pgvector_literal,
    validate_top_k,
)

BACKEND_DIR = pathlib.Path(__file__).resolve().parents[1]
SEARCH_SCRIPT = BACKEND_DIR / "scripts" / "smoke_knowledge_search.py"

FAKE_KEY = "sk-fake-search-key-for-tests-0123456789"

# 禁止出现在生产代码里的具体业务领域词（测试数据里可以用）
FORBIDDEN_DOMAIN_TERMS = (
    "客单价",
    "销售额",
    "会员",
    "复购率",
    "华东",
    "黑金会员",
    "年底旺季",
)


# --------------------------------------------------------------------------
# 替身
# --------------------------------------------------------------------------


def make_embedding_settings(**overrides) -> EmbeddingSettings:
    values = {
        "provider": "dashscope",
        "model": "text-embedding-v4",
        "dimension": EXPECTED_DIMENSION,
        "base_url": "https://example.invalid/v1",
        "api_key": FAKE_KEY,
    }
    values.update(overrides)
    return EmbeddingSettings(**values)


class FakeQueryEmbedder:
    """记录被问到的问题，返回固定长度的可辨识向量。"""

    def __init__(self, dimension: int = EXPECTED_DIMENSION) -> None:
        self.dimension = dimension
        self.queries: list[str] = []

    async def __call__(self, query: str):
        self.queries.append(query)
        # 首个分量固定，便于断言参数里确实是这个向量
        vector = [0.5] * self.dimension
        vector[0] = -0.25
        return vector, make_embedding_settings(dimension=self.dimension)


class _FakeMappings:
    def __init__(self, rows) -> None:
        self._rows = rows

    def all(self):
        return list(self._rows)


class _FakeResult:
    def __init__(self, rows) -> None:
        self._rows = rows

    def mappings(self):
        return _FakeMappings(self._rows)


class FakeSearchConnection:
    """记录发出去的语句与参数；execute 返回预设行，scalar 返回预设计数。"""

    def __init__(self, rows=(), count: int = 0) -> None:
        self.rows = list(rows)
        self.count = count
        self.calls: list[tuple[str, dict]] = []

    async def execute(self, statement, parameters=None):
        self.calls.append((str(statement), dict(parameters or {})))
        return _FakeResult(self.rows)

    async def scalar(self, statement, parameters=None):
        self.calls.append((str(statement), dict(parameters or {})))
        return self.count


def make_row(
    *,
    chunk_id: int,
    distance: float,
    source_file: str = "retail_metrics.md",
    section_title: str = "客单价",
    chunk_index: int = 0,
    content: str = "客单价 = 销售额 / 订单数",
    document_id: int = 1,
    document_title: str = "零售核心指标口径说明",
    embedding_model: str | None = "text-embedding-v4",
) -> dict:
    return {
        "chunk_id": chunk_id,
        "document_id": document_id,
        "source_file": source_file,
        "document_title": document_title,
        "section_title": section_title,
        "chunk_index": chunk_index,
        "content": content,
        "embedding_model": embedding_model,
        "distance": distance,
    }


async def run_search(query, *, rows=(), count=0, **kwargs):
    embedder = kwargs.pop("embedder", None) or FakeQueryEmbedder()
    connection = FakeSearchConnection(rows, count=count)
    results = await search_knowledge(
        query, embedder=embedder, connection=connection, **kwargs
    )
    return results, embedder, connection


# --------------------------------------------------------------------------
# 问题文本校验
# --------------------------------------------------------------------------


def test_query_is_stripped_before_being_sent():
    _, embedder, _ = asyncio.run(run_search("  客单价怎么算？  "))

    assert embedder.queries == ["客单价怎么算？"]


@pytest.mark.parametrize("blank", ["", "   ", "\n\t ", "　"])
def test_blank_query_is_rejected_before_any_embedding_call(blank):
    embedder = FakeQueryEmbedder()
    connection = FakeSearchConnection()

    with pytest.raises(KnowledgeSearchError):
        asyncio.run(
            search_knowledge(blank, embedder=embedder, connection=connection)
        )

    # 关键：空白问题一次 API 都不该发出去
    assert embedder.queries == []
    assert connection.calls == []


def test_none_query_is_rejected():
    with pytest.raises(KnowledgeSearchError):
        normalize_query(None)


def test_query_error_message_is_about_the_input_not_the_config():
    """报错只谈问题文本本身，不该顺手带出任何配置内容。"""
    with pytest.raises(KnowledgeSearchError) as error:
        normalize_query("   ")

    message = str(error.value)
    assert FAKE_KEY not in message
    assert "sk-" not in message


# --------------------------------------------------------------------------
# top_k 校验：选择「报错」而不是静默截断
# --------------------------------------------------------------------------


@pytest.mark.parametrize("top_k", [MIN_TOP_K, 3, DEFAULT_TOP_K, MAX_TOP_K])
def test_valid_top_k_is_accepted(top_k):
    assert validate_top_k(top_k) == top_k


@pytest.mark.parametrize("bad_top_k", [0, -1, -100, MAX_TOP_K + 1, 50, 10_000])
def test_out_of_range_top_k_is_rejected(bad_top_k):
    """静默截断会让调用方以为「相关知识就只有这么多」，是安静的错。
    这里选择当场失败，并把合法区间写进错误信息。"""
    with pytest.raises(KnowledgeSearchError) as error:
        validate_top_k(bad_top_k)

    assert str(MIN_TOP_K) in str(error.value)
    assert str(MAX_TOP_K) in str(error.value)


@pytest.mark.parametrize("bad_type", [3.5, "5", None, True])
def test_non_integer_top_k_is_rejected(bad_type):
    with pytest.raises(KnowledgeSearchError):
        validate_top_k(bad_type)


def test_invalid_top_k_short_circuits_before_embedding():
    embedder = FakeQueryEmbedder()

    with pytest.raises(KnowledgeSearchError):
        asyncio.run(
            search_knowledge(
                "客单价",
                top_k=99,
                embedder=embedder,
                connection=FakeSearchConnection(),
            )
        )

    assert embedder.queries == []


# --------------------------------------------------------------------------
# 向量格式化
# --------------------------------------------------------------------------


def test_full_dimension_vector_round_trips_through_the_literal():
    vector = [0.125] * EXPECTED_DIMENSION
    vector[0] = -1.5

    literal = to_pgvector_literal(vector)

    assert literal.count(",") == EXPECTED_DIMENSION - 1
    assert literal.startswith("[-1.5,")
    assert literal.endswith("0.125]")


def test_integer_elements_are_accepted():
    vector = [1] * EXPECTED_DIMENSION

    literal = to_pgvector_literal(vector)

    assert literal.startswith("[1.0,")


@pytest.mark.parametrize(
    "bad_vector",
    [
        [],
        [0.1, 0.2, 0.3],  # 维度不足
        [0.1] * (EXPECTED_DIMENSION + 1),  # 维度超出
        ["not-a-number"] * EXPECTED_DIMENSION,
        [None] * EXPECTED_DIMENSION,
    ],
)
def test_malformed_vectors_are_rejected(bad_vector):
    with pytest.raises(KnowledgeSearchError):
        to_pgvector_literal(bad_vector)


def test_literal_never_contains_sql_syntax():
    """格式化出来的是纯数字数组，不可能夹带 SQL 片段。"""
    literal = to_pgvector_literal([0.5] * EXPECTED_DIMENSION)

    for token in (";", "--", "/*", "'", '"', "SELECT", "DROP"):
        assert token not in literal


# --------------------------------------------------------------------------
# 检索行为
# --------------------------------------------------------------------------


def test_search_passes_vector_and_top_k_as_bound_parameters():
    results, _, connection = asyncio.run(
        run_search("客单价怎么算", rows=[make_row(chunk_id=1, distance=0.1)], top_k=3)
    )

    assert len(connection.calls) == 1
    sql, params = connection.calls[0]

    assert set(params) == {"query_embedding", "top_k"}
    assert params["top_k"] == 3
    assert isinstance(params["query_embedding"], str)
    assert params["query_embedding"].startswith("[-0.25,")

    assert "CAST(:query_embedding AS vector)" in sql
    assert "LIMIT :top_k" in sql


def test_the_user_question_never_reaches_the_sql_or_its_parameters():
    """用户文本只被送去算向量。SQL 与参数里都不该出现它。

    这既是防注入的根据，也解释了为什么这里不需要转义任何东西。
    """
    question = "'; DROP TABLE knowledge_chunks; --"
    _, embedder, connection = asyncio.run(
        run_search(question, rows=[make_row(chunk_id=1, distance=0.1)])
    )

    assert embedder.queries == [question]
    sql, params = connection.calls[0]
    assert "DROP" not in sql
    assert question not in sql
    assert all(question not in str(value) for value in params.values())


def test_search_result_fields_are_mapped_completely():
    row = make_row(
        chunk_id=42,
        document_id=7,
        distance=0.2345,
        source_file="member_rules.md",
        section_title="黑金会员",
        chunk_index=5,
        content="黑金会员复购率最高",
        embedding_model="text-embedding-v4",
    )

    results, _, _ = asyncio.run(run_search("黑金", rows=[row]))

    assert len(results) == 1
    result = results[0]
    assert result.chunk_id == 42
    assert result.document_id == 7
    assert result.source_file == "member_rules.md"
    assert result.document_title == "零售核心指标口径说明"
    assert result.section_title == "黑金会员"
    assert result.chunk_index == 5
    assert result.content == "黑金会员复购率最高"
    assert result.embedding_model == "text-embedding-v4"
    assert result.distance == pytest.approx(0.2345)
    assert result.similarity == pytest.approx(1 - 0.2345)


def test_results_keep_the_database_order():
    """结果是按数据库返回的顺序原样传出的，Python 侧不重排。

    排序由 SQL 的 ORDER BY 完成——而且那一句不是可选的：
    没有它，LIMIT 取到的就是任意几行而不是最相似的几行。
    所以这里断言的是「没有打乱」，而不是「我替你排好了」。
    """
    rows = [
        make_row(chunk_id=1, distance=0.05),
        make_row(chunk_id=2, distance=0.31),
        make_row(chunk_id=3, distance=0.77),
    ]

    results, _, _ = asyncio.run(run_search("客单价", rows=rows))

    assert [r.chunk_id for r in results] == [1, 2, 3]
    assert [r.distance for r in results] == [0.05, 0.31, 0.77]
    assert [r.similarity for r in results] == pytest.approx([0.95, 0.69, 0.23])


def test_search_sql_orders_by_cosine_distance():
    """排序列必须是 `<=>`，不是 `<->`（欧氏）也不是 `<#>`（内积）。"""
    sql = str(SEARCH_SQL)

    assert "ORDER BY" in sql
    assert "<=>" in sql
    assert "<->" not in sql
    assert "<#>" not in sql


def test_search_sql_only_reads_and_filters_null_embeddings():
    sql = str(SEARCH_SQL).upper()

    assert sql.strip().startswith("SELECT")
    for keyword in ("INSERT", "UPDATE", "DELETE", "DROP", "ALTER", "TRUNCATE"):
        assert keyword not in sql
    # 没有向量的切片不能参与距离计算
    assert "EMBEDDING IS NOT NULL" in sql


def test_search_sql_joins_documents_for_source_info():
    sql = str(SEARCH_SQL)

    assert "JOIN knowledge_documents" in sql
    assert "source_file" in sql
    assert "document_title" in sql


def test_empty_knowledge_base_returns_no_results():
    results, _, _ = asyncio.run(run_search("客单价", rows=[]))

    assert results == []


def test_default_top_k_is_five():
    assert DEFAULT_TOP_K == 5


def test_default_top_k_is_used_when_not_specified():
    _, _, connection = asyncio.run(
        run_search("客单价", rows=[make_row(chunk_id=1, distance=0.1)])
    )

    assert connection.calls[0][1]["top_k"] == DEFAULT_TOP_K


# --------------------------------------------------------------------------
# similarity 换算
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("distance", "expected"),
    [(0.0, 1.0), (1.0, 0.0), (0.5, 0.5), (2.0, -1.0)],
)
def test_similarity_is_the_complement_of_cosine_distance(distance, expected):
    assert similarity_from_distance(distance) == pytest.approx(expected)


def test_build_search_result_accepts_decimal_like_values():
    """驱动返回的可能是 Decimal 而不是 float，构造结果时要能收下。"""
    from decimal import Decimal

    result = build_search_result(make_row(chunk_id=1, distance=Decimal("0.25")))

    assert isinstance(result.distance, float)
    assert result.distance == pytest.approx(0.25)


# --------------------------------------------------------------------------
# 可检索切片计数
# --------------------------------------------------------------------------


def test_count_searchable_chunks_reports_the_count():
    connection = FakeSearchConnection(count=44)

    assert asyncio.run(count_searchable_chunks(connection=connection)) == 44


def test_count_searchable_chunks_filters_by_embedding_presence():
    connection = FakeSearchConnection(count=0)

    asyncio.run(count_searchable_chunks(connection=connection))

    assert "EMBEDDING IS NOT NULL" in connection.calls[0][0].upper()


# --------------------------------------------------------------------------
# 不调用 LLM / 不写数据
# --------------------------------------------------------------------------


def _imported_modules(path: pathlib.Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
            modules.update(f"{node.module}.{alias.name}" for alias in node.names)
    return modules


def test_search_module_does_not_import_any_llm():
    """检索层不该够得着模型——生成回答是下一步的事，混在一起就分不清
    「没找到」和「找到了但答歪了」。"""
    modules = _imported_modules(pathlib.Path(knowledge_search.__file__))

    forbidden = ("app.core.llm", "langchain", "openai", "anthropic", "langgraph")
    offenders = [
        module for module in modules if module.startswith(forbidden)
    ]
    assert not offenders, f"检索模块不该引入模型相关依赖：{offenders}"


def test_search_module_only_uses_dml_safe_helpers():
    """确认模块里没有任何写入型 SQLAlchemy 构造器被导入。"""
    modules = _imported_modules(pathlib.Path(knowledge_search.__file__))

    assert "sqlalchemy.text" in modules
    for writer in ("sqlalchemy.insert", "sqlalchemy.update", "sqlalchemy.delete"):
        assert writer not in modules


# --------------------------------------------------------------------------
# 脚本
# --------------------------------------------------------------------------


def load_search_script():
    spec = importlib.util.spec_from_file_location("smoke_knowledge_search_script", SEARCH_SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_script_has_five_probe_questions_with_distinct_expected_sources():
    script = load_search_script()

    probes = script.PROBE_QUESTIONS
    assert len(probes) == 5
    # 5 个问题覆盖 5 个文件各一次，没有一个文件被重复期望
    assert len({probe.expected_source_file for probe in probes}) == 5
    assert all(probe.question.strip() for probe in probes)


def test_script_failure_message_redacts_the_api_key(tmp_path, monkeypatch, capsys):
    script = load_search_script()
    secret = "sk-canary-search-leak-0123456789abcdef"

    monkeypatch.setattr(script, "known_secret", lambda: secret)

    async def explode():
        raise RuntimeError(f"embedding rejected api_key={secret} with 401")

    async def noop():
        return None

    monkeypatch.setattr(script, "run_probes", explode)
    monkeypatch.setattr(script, "dispose_engine", noop)

    exit_code = asyncio.run(script.main())

    output = capsys.readouterr().out
    assert exit_code == 1
    assert secret not in output
    assert "sk-" not in output
    assert "知识检索验证失败" in output


def test_script_preview_truncates_long_content():
    script = load_search_script()

    preview = script.preview("正文。" * 200)

    assert len(preview) <= script.PREVIEW_CHARS + 1
    assert preview.endswith("…")


def test_script_preview_flattens_newlines():
    script = load_search_script()

    assert "\n" not in script.preview("第一行\n\n第二行")


# ==========================================================================
# 召回链路的公共底座（RAG-13.4）
#
# 这一节守住两件事：
# 1. 向量召回这一路的行为**一点没变**——它已经被 RAG 回答服务和大量测试依赖；
# 2. 新抽出来的共享类型只做加法，不往里面塞任何不属于它的分数。
# ==========================================================================


def test_chunk_property_mirrors_the_flat_fields():
    result = build_search_result(make_row(chunk_id=42, document_id=7, distance=0.25))

    chunk = result.chunk

    assert isinstance(chunk, ChunkContent)
    assert chunk.chunk_id == result.chunk_id
    assert chunk.document_id == result.document_id
    assert chunk.source_file == result.source_file
    assert chunk.document_title == result.document_title
    assert chunk.section_title == result.section_title
    assert chunk.chunk_index == result.chunk_index
    assert chunk.content == result.content
    assert chunk.embedding_model == result.embedding_model


def test_chunk_content_carries_no_scores():
    """★ 公共内容里不该有任何分数。

    带上 distance 的话，关键词召回就得为它编一个值——
    而那正是这次特意分开两种结果类型要避免的事。
    """
    chunk = build_search_result(make_row(chunk_id=1, distance=0.25)).chunk

    for forbidden in ("distance", "similarity", "keyword_score", "rrf_score"):
        assert not hasattr(chunk, forbidden), f"公共内容里不该有 {forbidden}"


def test_build_chunk_content_maps_every_column():
    row = make_row(
        chunk_id=42,
        document_id=7,
        source_file="规范.md",
        section_title="小节甲",
        chunk_index=5,
        content="正文乙。",
        embedding_model="text-embedding-v4",
        distance=0.1,
    )

    chunk = build_chunk_content(row)

    assert chunk.chunk_id == 42
    assert chunk.document_id == 7
    assert chunk.source_file == "规范.md"
    assert chunk.document_title == "零售核心指标口径说明"
    assert chunk.section_title == "小节甲"
    assert chunk.chunk_index == 5
    assert chunk.content == "正文乙。"
    assert chunk.embedding_model == "text-embedding-v4"


def test_chunk_content_is_frozen_and_hashable():
    """不可变：融合层会把它放进字典当键，可变对象做键会出问题。"""
    chunk = build_search_result(make_row(chunk_id=1, distance=0.1)).chunk

    assert hash(chunk) is not None
    with pytest.raises(Exception):
        chunk.chunk_id = 999


def test_build_search_result_keeps_deriving_similarity_from_distance():
    """回归：抽出公共映射之后，distance / similarity 的语义没变。"""
    result = build_search_result(make_row(chunk_id=1, distance=0.25))

    assert result.distance == pytest.approx(0.25)
    assert result.similarity == pytest.approx(0.75)
    assert "distance" not in result.chunk.__dataclass_fields__


def test_search_knowledge_result_shape_is_unchanged():
    """★ 向量召回的对外结果一个字段都不能少。

    RAG 回答服务和它的测试都按这些字段名取值，少一个就是线上事故。
    """
    results, _, _ = asyncio.run(run_search("客单价", rows=[make_row(chunk_id=1, distance=0.2)]))

    result = results[0]
    for field in (
        "chunk_id",
        "document_id",
        "source_file",
        "document_title",
        "section_title",
        "chunk_index",
        "content",
        "embedding_model",
        "distance",
        "similarity",
    ):
        assert hasattr(result, field), field


def test_search_knowledge_still_validates_its_arguments():
    """回归：原有校验没有被这次重构绕过。"""
    with pytest.raises(KnowledgeSearchError):
        asyncio.run(search_knowledge("   ", connection=FakeSearchConnection()))

    with pytest.raises(KnowledgeSearchError):
        asyncio.run(search_knowledge("问题", top_k=0, connection=FakeSearchConnection()))


def test_connection_scope_hands_back_the_injected_connection():
    """公共的借连接规则：注入什么就给什么，不偷偷去连真库。"""
    injected = FakeSearchConnection()

    async def use():
        async with connection_scope(injected) as active:
            return active

    assert asyncio.run(use()) is injected


def test_connection_scope_is_shared_not_duplicated():
    """两个召回器必须用同一个借连接规则，否则测试注入只会对一路生效。"""
    source = pathlib.Path(knowledge_search.__file__).read_text(encoding="utf-8")

    assert "async def connection_scope" in source
    assert "_connection_scope" not in source  # 旧的私有名字不该留下副本


@pytest.mark.parametrize("term", FORBIDDEN_DOMAIN_TERMS)
def test_module_has_no_hardcoded_domain_vocabulary(term):
    source = pathlib.Path(knowledge_search.__file__).read_text(encoding="utf-8")

    assert term not in source
