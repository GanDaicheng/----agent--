"""关键词召回的测试。

**本文件不连接 PostgreSQL、不调 embedding、不调模型。**
数据库连接注入 `FakeSearchConnection`（记录 SQL 与绑定参数、返回预设行），
所以「发了什么语句」「绑定了哪些参数」都能被直接断言。

这里守三件最要紧的事：

1. **用户输入永远只是参数值，不进 SQL 文本**——`%`、`_`、反斜杠必须被转义，
   否则用户输入一个 `%` 就变成「匹配全库」；
2. **不能只靠 pg_trgm**——中文短词不足 3 个字符时三元组几乎失效，
   必须有精确匹配和 ILIKE 包含匹配兜底；
3. **评分优先级必须严格**——更强的命中规则不能被更弱的规则压过去。

保持项目约定：pytest 不需要 PostgreSQL。
"""

import asyncio
import contextlib
import pathlib
import re

import pytest

from app.services import knowledge_keyword_search, knowledge_search
from app.services.knowledge_keyword_search import (
    DEFAULT_KEYWORD_LIMIT,
    KEYWORD_SEARCH_SQL,
    LIKE_ESCAPE,
    MATCH_RULE_ORDER,
    MATCH_RULE_WEIGHTS,
    MAX_KEYWORD_LIMIT,
    MIN_KEYWORD_LIMIT,
    TRIGRAM_MIN_SIMILARITY,
    WEIGHT_SEARCH_TEXT_TRIGRAM,
    KeywordSearchResult,
    build_keyword_parameters,
    escape_like_pattern,
    normalize_term,
    search_knowledge_keywords,
    select_matched_rules,
    validate_keyword_limit,
)
from app.services.knowledge_search import ChunkContent, KnowledgeSearchError

MODULE_PATH = pathlib.Path(knowledge_keyword_search.__file__)

# 禁止出现在生产代码里的具体业务领域词
FORBIDDEN_DOMAIN_TERMS = (
    "客单价",
    "销售额",
    "会员",
    "复购率",
    "华东",
    "黑金会员",
    "年底旺季",
)

# 一条完整命中的行（所有信号都为真），各测试按需覆盖其中几个键
ALL_SIGNALS = dict.fromkeys(MATCH_RULE_ORDER, False)


# --------------------------------------------------------------------------
# 替身
# --------------------------------------------------------------------------


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
    """记录发出去的语句与参数；execute 返回预设行。"""

    def __init__(self, rows=()) -> None:
        self.rows = list(rows)
        self.calls: list[tuple[str, dict]] = []

    async def execute(self, statement, parameters=None):
        self.calls.append((str(statement), dict(parameters or {})))
        return _FakeResult(self.rows)


def make_row(
    *,
    chunk_id: int,
    keyword_score: float = 100.0,
    source_file: str = "文档.md",
    document_title: str = "文档标题",
    section_title: str = "小节标题",
    chunk_index: int = 0,
    content: str = "切片正文。",
    document_id: int = 1,
    embedding_model: str | None = "text-embedding-v4",
    **signals,
) -> dict:
    flags = dict(ALL_SIGNALS)
    flags.update(signals)
    return {
        "chunk_id": chunk_id,
        "document_id": document_id,
        "source_file": source_file,
        "document_title": document_title,
        "section_title": section_title,
        "chunk_index": chunk_index,
        "content": content,
        "embedding_model": embedding_model,
        "keyword_score": keyword_score,
        **flags,
    }


def normalized_sql() -> str:
    """把 SQL 压成单行空白，避免断言被换行和缩进干扰。"""
    return re.sub(r"\s+", " ", str(KEYWORD_SEARCH_SQL))


async def run_search(term, *, rows=(), **kwargs):
    connection = kwargs.pop("connection", None) or FakeSearchConnection(rows)
    results = await search_knowledge_keywords(term, connection=connection, **kwargs)
    return results, connection


# --------------------------------------------------------------------------
# 输入校验：空、空白、非法 limit
# --------------------------------------------------------------------------


@pytest.mark.parametrize("blank", ["", "   ", "\n\t ", "　"])
def test_blank_term_is_rejected_before_any_query(blank):
    connection = FakeSearchConnection()

    with pytest.raises(KnowledgeSearchError):
        asyncio.run(run_search(blank, connection=connection))

    assert connection.calls == []  # 一次 SQL 都不该发出去


def test_none_term_is_rejected():
    with pytest.raises(KnowledgeSearchError):
        normalize_term(None)


def test_term_is_stripped_before_matching():
    assert normalize_term("  术语甲  ") == "术语甲"


def test_term_error_message_is_about_the_input_not_the_config():
    with pytest.raises(KnowledgeSearchError) as error:
        normalize_term("   ")

    assert "sk-" not in str(error.value)
    assert "postgresql" not in str(error.value).lower()


@pytest.mark.parametrize("value", [MIN_KEYWORD_LIMIT, 5, DEFAULT_KEYWORD_LIMIT, MAX_KEYWORD_LIMIT])
def test_valid_limit_is_accepted(value):
    assert validate_keyword_limit(value) == value


@pytest.mark.parametrize(
    "bad_limit", [0, -1, -100, MAX_KEYWORD_LIMIT + 1, 1000]
)
def test_out_of_range_limit_is_rejected(bad_limit):
    with pytest.raises(KnowledgeSearchError) as error:
        validate_keyword_limit(bad_limit)

    assert str(MIN_KEYWORD_LIMIT) in str(error.value)
    assert str(MAX_KEYWORD_LIMIT) in str(error.value)


@pytest.mark.parametrize("bad_type", [3.5, "5", None, True])
def test_non_integer_limit_is_rejected(bad_type):
    with pytest.raises(KnowledgeSearchError):
        validate_keyword_limit(bad_type)


def test_invalid_limit_short_circuits_before_any_query():
    connection = FakeSearchConnection()

    with pytest.raises(KnowledgeSearchError):
        asyncio.run(run_search("术语", limit=999, connection=connection))

    assert connection.calls == []


# --------------------------------------------------------------------------
# LIKE 通配符转义
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("术语甲", "术语甲"),
        ("100%", "100\\%"),
        ("a_b", "a\\_b"),
        ("a\\b", "a\\\\b"),
        ("%_\\", "\\%\\_\\\\"),
        ("%", "\\%"),
        ("_", "\\_"),
    ],
)
def test_like_wildcards_are_escaped(raw, expected):
    assert escape_like_pattern(raw) == expected


def test_the_escape_character_is_escaped_first():
    """★ 顺序不能反。

    先转 % 再转反斜杠的话，刚给 % 加上的那个反斜杠会被再转一遍，
    变成 `\\\\%`——模式里就成了「一个反斜杠 + 一个通配符」，又变回通配符了。
    """
    assert escape_like_pattern("\\%") == "\\\\\\%"


def test_a_percent_sign_cannot_become_a_match_everything_pattern():
    """★ 用户输入一个 % 时，它必须被当成字面量。"""
    parameters = build_keyword_parameters("%", limit=DEFAULT_KEYWORD_LIMIT)

    assert parameters["contains"] == "%\\%%"
    assert parameters["contains"] != "%%%"


def test_the_escape_character_matches_the_sql_clause():
    assert LIKE_ESCAPE == "\\"
    assert "ESCAPE '\\'" in normalized_sql()


# --------------------------------------------------------------------------
# SQL 参数化
# --------------------------------------------------------------------------


def test_every_placeholder_has_a_bound_parameter():
    """★ SQL 里出现的每个 :name 都必须有对应参数。

    漏一个要等运行期才报错，而那时已经离改动很远了。
    """
    placeholders = set(re.findall(r":(\w+)", normalized_sql()))

    assert placeholders == set(build_keyword_parameters("术语", limit=DEFAULT_KEYWORD_LIMIT))


def test_weights_are_bound_parameters_not_literals():
    """★ 权重只有一个来源：Python 常量，通过绑定参数进入 SQL。

    写成 SQL 字面量的话，两处数值迟早会漂开，而漂开之后
    「哪条规则更强」这件事就只能靠读 SQL 才知道。
    """
    sql = normalized_sql()
    parameters = build_keyword_parameters("术语", limit=DEFAULT_KEYWORD_LIMIT)

    for label in MATCH_RULE_ORDER:
        assert f":w_{label}" in sql, label
        assert parameters[f"w_{label}"] == MATCH_RULE_WEIGHTS[label]
        # 权重值本身不该以字面量出现在 SQL 里
        assert f" {MATCH_RULE_WEIGHTS[label]} " not in sql


def test_the_search_term_never_appears_in_the_sql_text():
    term = "'; DROP TABLE knowledge_chunks; --"

    parameters = build_keyword_parameters(term, limit=DEFAULT_KEYWORD_LIMIT)
    sql = normalized_sql()

    assert term not in sql
    assert "DROP" not in sql.upper()
    # 它是参数值：原文保留，通配符按字面量转义后进 LIKE 模式
    assert parameters["term"] == term
    assert parameters["contains"] == f"%{escape_like_pattern(term)}%"


def test_the_user_term_is_passed_through_as_a_bound_value():
    _, connection = asyncio.run(run_search("术语甲", rows=[make_row(chunk_id=1)]))

    _, parameters = connection.calls[0]
    assert parameters["term"] == "术语甲"
    assert parameters["limit"] == DEFAULT_KEYWORD_LIMIT


def test_sql_is_read_only():
    sql = normalized_sql().upper()

    for keyword in ("INSERT", "UPDATE", "DELETE", "DROP", "ALTER", "TRUNCATE", "CREATE"):
        assert keyword not in sql


# --------------------------------------------------------------------------
# 搜了哪些字段
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "column",
    ["kd.document_title", "kc.section_title", "kc.keywords", "kc.aliases", "kc.search_text"],
)
def test_every_searchable_column_is_used(column):
    assert column in normalized_sql()


def test_short_terms_do_not_rely_on_trigram_alone():
    """★ 中文两个字不足 3 个字符，三元组几乎帮不上忙。

    所以 SQL 必须同时有精确匹配和 ILIKE 包含匹配，
    trigram 只能作为最后一层补充。
    """
    sql = normalized_sql()

    assert "= :term" in sql  # 精确匹配
    assert "ILIKE :contains" in sql  # 包含匹配
    assert "similarity(" in sql  # 模糊补充
    # 主体是 ILIKE 与等值判断，trigram 只出现在最后一层
    assert sql.count("ILIKE :contains") >= 3
    assert sql.count("similarity(") >= 1


def test_a_two_character_term_produces_a_literal_contains_pattern():
    parameters = build_keyword_parameters("术语", limit=DEFAULT_KEYWORD_LIMIT)

    assert parameters["contains"] == "%术语%"
    assert parameters["term"] == "术语"


def test_trigram_threshold_is_applied_and_below_the_contains_weight():
    sql = normalized_sql()

    assert ":trigram_min_similarity" in sql
    assert TRIGRAM_MIN_SIMILARITY > 0
    # 纯模糊命中的最高分仍然低于「正文包含」这一层
    assert WEIGHT_SEARCH_TEXT_TRIGRAM * 1.0 < MATCH_RULE_WEIGHTS["search_text_contains"]


# --------------------------------------------------------------------------
# 评分规则
# --------------------------------------------------------------------------


def test_scoring_tiers_are_strictly_ordered():
    """★ 分层权重必须严格递减，否则强者会被弱者压过去。"""
    weights = [MATCH_RULE_WEIGHTS[label] for label in MATCH_RULE_ORDER]

    assert weights == sorted(weights, reverse=True)
    assert len(set(weights)) == len(weights), "同一层不能有两个权重"


def test_match_rule_order_starts_with_the_title_tiers():
    assert MATCH_RULE_ORDER[:2] == ("section_title_exact", "document_title_exact")


def test_title_and_term_tiers_outrank_text_matching():
    assert MATCH_RULE_WEIGHTS["section_title_exact"] > MATCH_RULE_WEIGHTS["search_text_contains"]
    assert MATCH_RULE_WEIGHTS["document_title_exact"] > MATCH_RULE_WEIGHTS["search_text_contains"]
    assert MATCH_RULE_WEIGHTS["keywords_exact"] > MATCH_RULE_WEIGHTS["search_text_contains"]
    assert MATCH_RULE_WEIGHTS["aliases_exact"] > MATCH_RULE_WEIGHTS["search_text_contains"]


def test_section_title_outranks_document_title():
    """小节标题更具体：命中它说明这一段就是在讲这个东西。"""
    assert MATCH_RULE_WEIGHTS["section_title_exact"] > MATCH_RULE_WEIGHTS["document_title_exact"]
    assert (
        MATCH_RULE_WEIGHTS["section_title_contains"]
        > MATCH_RULE_WEIGHTS["document_title_contains"]
    )


@pytest.mark.parametrize("label", MATCH_RULE_ORDER)
def test_each_rule_is_selected_during_scoring(label):
    sql = normalized_sql()

    assert label in sql, label


@pytest.mark.parametrize("label", MATCH_RULE_ORDER)
def test_each_rule_maps_to_its_own_label(label):
    assert select_matched_rules({label: True}) == (label,)


def test_matched_terms_follow_the_priority_order_not_the_row_order():
    """★ matched_terms 的顺序由优先级决定，不受 SQL 返回列的顺序影响。"""
    flags = {label: True for label in reversed(MATCH_RULE_ORDER)}

    assert select_matched_rules(flags) == MATCH_RULE_ORDER


def test_matched_terms_are_deduplicated():
    """每个标签最多出现一次，即使映射里给了重复信号。"""
    labels = select_matched_rules(dict.fromkeys(MATCH_RULE_ORDER, True))

    assert len(labels) == len(set(labels)) == len(MATCH_RULE_ORDER)


def test_no_signal_means_no_matched_terms():
    assert select_matched_rules(dict(ALL_SIGNALS)) == ()


def test_missing_signals_are_treated_as_not_matched():
    """行里少一个列不该炸，只该少一个标签。"""
    assert select_matched_rules({"section_title_exact": True}) == ("section_title_exact",)


def test_sql_computes_the_score_with_greatest_of_tiers():
    """分数是「命中的最强那一层」，不是各层相加。

    相加会让「正文包含 + 模糊」压过「标题包含」，
    与分层的本意正好相反。
    """
    sql = normalized_sql().upper()

    assert "GREATEST(" in sql
    assert " AS KEYWORD_SCORE" in sql
    assert "ORDER BY KEYWORD_SCORE DESC, CHUNK_ID ASC" in sql


# --------------------------------------------------------------------------
# 检索行为
# --------------------------------------------------------------------------


def test_results_are_mapped_completely():
    row = make_row(
        chunk_id=42,
        document_id=7,
        source_file="规范.md",
        document_title="文档标题甲",
        section_title="小节标题乙",
        chunk_index=5,
        content="切片正文丙。",
        embedding_model="text-embedding-v4",
        keyword_score=80.0,
        keywords_exact=True,
    )

    results, _ = asyncio.run(run_search("术语", rows=[row]))

    assert len(results) == 1
    result = results[0]
    assert isinstance(result, KeywordSearchResult)
    assert isinstance(result.chunk, ChunkContent)
    assert result.chunk.chunk_id == 42
    assert result.chunk.document_id == 7
    assert result.chunk.source_file == "规范.md"
    assert result.chunk.document_title == "文档标题甲"
    assert result.chunk.section_title == "小节标题乙"
    assert result.chunk.chunk_index == 5
    assert result.chunk.content == "切片正文丙。"
    assert result.chunk.embedding_model == "text-embedding-v4"
    assert result.keyword_score == pytest.approx(80.0)
    assert result.matched_terms == ("keywords_exact",)


def test_results_carry_no_vector_distance():
    """★ 关键词命中没有向量距离，就不能伪装成有。

    KnowledgeSearchResult 上的 distance / similarity 是向量召回专有的量；
    关键词结果用自己的类型，从类型上就不给下游拿错数的机会。
    """
    results, _ = asyncio.run(run_search("术语", rows=[make_row(chunk_id=1)]))

    result = results[0]
    assert not hasattr(result, "distance")
    assert not hasattr(result, "similarity")
    assert not hasattr(result.chunk, "distance")


def test_results_keep_the_database_order():
    """排序由 SQL 的 ORDER BY 完成（分数降序、chunk_id 升序），Python 侧不重排。"""
    rows = [
        make_row(chunk_id=1, keyword_score=100.0),
        make_row(chunk_id=2, keyword_score=50.0),
        make_row(chunk_id=3, keyword_score=50.0),
    ]

    results, _ = asyncio.run(run_search("术语", rows=rows))

    assert [result.chunk.chunk_id for result in results] == [1, 2, 3]


def test_empty_result_is_returned_as_empty_list():
    results, _ = asyncio.run(run_search("术语", rows=[]))

    assert results == []


def test_the_limit_is_forwarded_as_a_bound_parameter():
    _, connection = asyncio.run(run_search("术语", rows=[], limit=3))

    assert connection.calls[0][1]["limit"] == 3


def test_connection_is_injectable_and_no_real_database_is_touched(monkeypatch):
    """★ 注入 connection 后一次都不该去连真库。

    把 get_connection 换成一调用就炸的桩——真去连就会当场失败。
    """

    def explode():
        raise AssertionError("注入 connection 之后不该再自己去连数据库")

    monkeypatch.setattr(knowledge_search, "get_connection", explode)

    results, connection = asyncio.run(run_search("术语", rows=[make_row(chunk_id=1)]))

    assert len(results) == 1
    assert len(connection.calls) == 1


def test_without_an_injected_connection_it_borrows_one(monkeypatch):
    """不注入时要走公共的借连接路径，而不是自己另起一套。"""
    borrowed = FakeSearchConnection([make_row(chunk_id=1)])
    used = []

    @contextlib.asynccontextmanager
    async def fake_scope(connection):
        used.append(connection)
        yield borrowed

    monkeypatch.setattr(knowledge_keyword_search, "connection_scope", fake_scope)

    asyncio.run(search_knowledge_keywords("术语"))

    assert used == [None]


def test_the_module_does_not_import_any_model_or_embedding():
    """关键词召回不该够得着模型和 embedding——那是召回之外的事。"""
    import ast

    tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)

    forbidden = ("app.core.llm", "app.services.embedding", "langchain", "openai")
    assert not [module for module in modules if module.startswith(forbidden)]


@pytest.mark.parametrize("term", FORBIDDEN_DOMAIN_TERMS)
def test_module_has_no_hardcoded_domain_vocabulary(term):
    assert term not in MODULE_PATH.read_text(encoding="utf-8")


def test_sql_prefers_exact_then_contains_then_fuzzy():
    """三层在 SQL 里的出现顺序要与优先级一致，便于人工核对。

    评分本身由 GREATEST 的权重决定，这里只确认三层都真实存在。
    """
    sql = normalized_sql()

    exact_position = sql.index("= :term")
    contains_position = sql.index("ILIKE :contains")
    fuzzy_position = sql.index("similarity(")

    assert exact_position < contains_position < fuzzy_position
