"""RRF 融合与混合召回的测试。

**本文件不连接 PostgreSQL、不调 embedding、不调模型、不发任何网络请求。**
两路召回都注入替身：
- `FakeVectorSearcher` / `FakeKeywordSearcher` 记录每次调用的查询与参数，
  按预设返回结果或抛异常；
- 数据库连接根本不存在（`hybrid_search` 把 connection 原样透传给替身）。

这里守四件事：
1. RRF 的公式、去重、累加和排名语义正确；
2. 不能给「只有一路命中」的候选伪造另一路的分数；
3. 一路失败不能拖垮另一路，两路全失败才报错；
4. 融合是纯函数：不连库、不调模型。

保持项目约定：pytest 不需要 PostgreSQL。
"""

import asyncio
import pathlib

import pytest

from app.services import retrieval_fusion
from app.services.knowledge_keyword_search import KeywordSearchResult
from app.services.knowledge_search import ChunkContent, KnowledgeSearchError, KnowledgeSearchResult
from app.services.query_rewrite import QueryRewriteResult
from app.services.retrieval_fusion import (
    DEFAULT_CANDIDATE_LIMIT,
    MAX_CANDIDATE_LIMIT,
    RRF_K,
    RankedResults,
    RetrievalCandidate,
    hybrid_search,
    reciprocal_rank_fusion,
)

MODULE_PATH = pathlib.Path(retrieval_fusion.__file__)

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
# 构造工具
# --------------------------------------------------------------------------


def make_chunk(chunk_id: int, **overrides) -> ChunkContent:
    values = {
        "chunk_id": chunk_id,
        "document_id": 1,
        "source_file": "文档.md",
        "document_title": "文档标题",
        "section_title": "小节标题",
        "chunk_index": chunk_id,
        "content": f"第 {chunk_id} 段正文。",
        "embedding_model": "text-embedding-v4",
    }
    values.update(overrides)
    return ChunkContent(**values)


def make_vector_result(chunk_id: int, *, distance: float = 0.2) -> KnowledgeSearchResult:
    return KnowledgeSearchResult(
        chunk_id=chunk_id,
        document_id=1,
        source_file="文档.md",
        document_title="文档标题",
        section_title="小节标题",
        chunk_index=chunk_id,
        content=f"第 {chunk_id} 段正文。",
        embedding_model="text-embedding-v4",
        distance=distance,
        similarity=1 - distance,
    )


def make_keyword_result(
    chunk_id: int,
    *,
    keyword_score: float = 100.0,
    matched_terms: tuple[str, ...] = ("keywords_exact",),
) -> KeywordSearchResult:
    return KeywordSearchResult(
        chunk=make_chunk(chunk_id),
        keyword_score=keyword_score,
        matched_terms=matched_terms,
    )


def ranked_vector(query: str, chunk_ids) -> RankedResults:
    return RankedResults(
        retrieval_type="vector",
        query=query,
        results=tuple(make_vector_result(chunk_id) for chunk_id in chunk_ids),
    )


def ranked_keyword(query: str, chunk_ids) -> RankedResults:
    return RankedResults(
        retrieval_type="keyword",
        query=query,
        results=tuple(make_keyword_result(chunk_id) for chunk_id in chunk_ids),
    )


def by_id(candidates) -> dict[int, RetrievalCandidate]:
    return {candidate.chunk.chunk_id: candidate for candidate in candidates}


class FakeVectorSearcher:
    """按查询返回预设向量结果，并记录调用参数。"""

    def __init__(self, results=None, *, errors=None) -> None:
        self.results = results or {}
        self.errors = errors or {}
        self.calls: list[tuple[str, int, object]] = []

    @property
    def queries(self) -> list[str]:
        return [query for query, _, _ in self.calls]

    async def __call__(self, query, *, top_k, connection=None):
        self.calls.append((query, top_k, connection))
        if query in self.errors:
            raise self.errors[query]
        return [
            make_vector_result(chunk_id, distance=distance)
            for chunk_id, distance in self.results.get(query, [])
        ]


class FakeKeywordSearcher:
    """按检索词返回预设关键词结果，并记录调用参数。"""

    def __init__(self, results=None, *, errors=None) -> None:
        self.results = results or {}
        self.errors = errors or {}
        self.calls: list[tuple[str, int, object]] = []

    @property
    def terms(self) -> list[str]:
        return [term for term, _, _ in self.calls]

    async def __call__(self, term, *, limit, connection=None):
        self.calls.append((term, limit, connection))
        if term in self.errors:
            raise self.errors[term]
        return [
            make_keyword_result(chunk_id, keyword_score=score)
            for chunk_id, score in self.results.get(term, [])
        ]


def make_plan(*, original="原问题", rewritten=(), keywords=()) -> QueryRewriteResult:
    return QueryRewriteResult(
        original_query=original,
        rewritten_queries=tuple(rewritten),
        keywords=tuple(keywords),
    )


def run_hybrid(plan, *, vector=None, keyword=None, **kwargs):
    vector = vector if vector is not None else FakeVectorSearcher()
    keyword = keyword if keyword is not None else FakeKeywordSearcher()
    candidates = asyncio.run(
        hybrid_search(plan, vector_searcher=vector, keyword_searcher=keyword, **kwargs)
    )
    return candidates, vector, keyword


# --------------------------------------------------------------------------
# RRF：公式与排名
# --------------------------------------------------------------------------


def test_rank_starts_at_one():
    """rank 从 1 开始：单个列表第一条的得分是 1/(k+1)。"""
    candidates = reciprocal_rank_fusion([ranked_vector("甲", [11])])

    assert len(candidates) == 1
    assert candidates[0].rrf_score == pytest.approx(1 / (RRF_K + 1))


def test_scores_follow_the_formula():
    """第二条的得分是 1/(k+2)。"""
    candidates = reciprocal_rank_fusion([ranked_vector("甲", [11, 22, 33])])
    scores = {candidate.chunk.chunk_id: candidate.rrf_score for candidate in candidates}

    assert scores[11] == pytest.approx(1 / (RRF_K + 1))
    assert scores[22] == pytest.approx(1 / (RRF_K + 2))
    assert scores[33] == pytest.approx(1 / (RRF_K + 3))


def test_the_same_chunk_in_several_lists_is_deduplicated():
    candidates = reciprocal_rank_fusion(
        [ranked_vector("甲", [11, 22]), ranked_keyword("甲", [11, 22])]
    )

    assert len(candidates) == 2
    assert [candidate.chunk.chunk_id for candidate in candidates] == [11, 22]


def test_scores_accumulate_across_lists():
    candidates = reciprocal_rank_fusion(
        [ranked_vector("甲", [11]), ranked_keyword("甲", [11])]
    )

    assert candidates[0].rrf_score == pytest.approx(1 / (RRF_K + 1) + 1 / (RRF_K + 1))


def test_accumulated_score_beats_a_single_list_hit():
    """★ 多路命中要真的加分：只被一路命中的切片排在后面。"""
    candidates = reciprocal_rank_fusion(
        [
            ranked_vector("甲", [11]),
            ranked_keyword("甲", [11]),
            ranked_keyword("乙", [22]),
        ]
    )

    assert [candidate.chunk.chunk_id for candidate in candidates] == [11, 22]


def test_k_is_configurable():
    candidates = reciprocal_rank_fusion([ranked_vector("甲", [11])], k=1)

    assert candidates[0].rrf_score == pytest.approx(1 / 2)


@pytest.mark.parametrize("bad_k", [0, -1, -60, 1.5, "60", None, True])
def test_invalid_k_is_rejected(bad_k):
    with pytest.raises(KnowledgeSearchError):
        reciprocal_rank_fusion([ranked_vector("甲", [11])], k=bad_k)


# --------------------------------------------------------------------------
# RRF：vector_rank / keyword_rank
# --------------------------------------------------------------------------


def test_vector_rank_is_the_best_rank_across_vector_lists():
    candidates = reciprocal_rank_fusion(
        [ranked_vector("甲", [77, 88, 11]), ranked_vector("乙", [11])]
    )

    assert by_id(candidates)[11].vector_rank == 1  # 第二个列表里的第 1 名
    assert by_id(candidates)[77].vector_rank == 1
    assert by_id(candidates)[88].vector_rank == 2


def test_keyword_rank_is_the_best_rank_across_keyword_lists():
    candidates = reciprocal_rank_fusion(
        [ranked_keyword("甲", [1, 2, 3]), ranked_keyword("乙", [3])]
    )

    assert by_id(candidates)[3].keyword_rank == 1
    assert by_id(candidates)[2].keyword_rank == 2


def test_ranks_do_not_leak_between_the_two_families():
    """向量列表的名次不能算进 keyword_rank，反之亦然。"""
    candidates = reciprocal_rank_fusion([ranked_vector("甲", [11, 22])])
    candidate = by_id(candidates)[22]

    assert candidate.vector_rank == 2
    assert candidate.keyword_rank is None


def test_a_vector_only_candidate_has_no_keyword_fields():
    """★ 只有向量命中时，关键词相关的字段必须是 None 或空，而不是 0。"""
    candidates = reciprocal_rank_fusion([ranked_vector("甲", [11])])
    candidate = candidates[0]

    assert candidate.vector_rank == 1
    assert candidate.keyword_rank is None
    assert candidate.keyword_score is None
    assert candidate.matched_terms == ()
    assert candidate.distance == pytest.approx(0.2)
    assert candidate.similarity == pytest.approx(0.8)


def test_a_keyword_only_candidate_has_no_vector_fields():
    """★ 只有关键词命中时，distance / similarity 必须是 None。

    关键词命中根本没算过向量距离；塞 0 或 1 进去会让下游以为
    「这条的相似度就是 0」，而它其实压根没有相似度可言。
    """
    candidates = reciprocal_rank_fusion([ranked_keyword("甲", [11])])
    candidate = candidates[0]

    assert candidate.keyword_rank == 1
    assert candidate.vector_rank is None
    assert candidate.distance is None
    assert candidate.similarity is None
    assert candidate.keyword_score == pytest.approx(100.0)
    assert candidate.matched_terms == ("keywords_exact",)


def test_a_two_way_candidate_carries_both_families():
    candidates = reciprocal_rank_fusion(
        [ranked_vector("甲", [11]), ranked_keyword("甲", [11])]
    )
    candidate = candidates[0]

    assert candidate.vector_rank == 1
    assert candidate.keyword_rank == 1
    assert candidate.distance == pytest.approx(0.2)
    assert candidate.keyword_score == pytest.approx(100.0)


def test_scores_come_from_the_best_ranked_hit_in_that_family():
    """同一路里出现多次时，取排名最好那一次附带的分数。"""
    first = RankedResults(
        retrieval_type="vector",
        query="甲",
        results=(make_vector_result(11, distance=0.9),),
    )
    second = RankedResults(
        retrieval_type="vector",
        query="乙",
        results=(make_vector_result(11, distance=0.1),),
    )

    candidates = reciprocal_rank_fusion([first, second])

    # 第二名那次（distance 0.1）排名更差，所以保留的是第 1 名的 0.9
    assert candidates[0].vector_rank == 1
    assert candidates[0].distance == pytest.approx(0.9)


def test_rerank_score_is_none_for_now():
    """本阶段还没到精排，占位字段必须是 None，不能是 0。"""
    candidates = reciprocal_rank_fusion([ranked_vector("甲", [11])])

    assert candidates[0].rerank_score is None


# --------------------------------------------------------------------------
# RRF：matched_queries 与稳定排序
# --------------------------------------------------------------------------


def test_matched_queries_keep_first_seen_order_and_are_deduplicated():
    candidates = reciprocal_rank_fusion(
        [
            ranked_vector("乙", [11]),
            ranked_keyword("甲", [11]),
            ranked_keyword("乙", [11]),
        ]
    )

    assert candidates[0].matched_queries == ("乙", "甲")


def test_matched_queries_only_include_the_lists_that_hit():
    candidates = reciprocal_rank_fusion(
        [ranked_vector("甲", [11]), ranked_vector("乙", [22])]
    )

    assert by_id(candidates)[11].matched_queries == ("甲",)
    assert by_id(candidates)[22].matched_queries == ("乙",)


def test_a_tie_is_broken_by_the_best_single_rank():
    """★ 平分时先看「最好的一次排到第几」。

    11 号在某一路排第 1，22 号排第 2，两者各命中一次、总分相同，
    但 11 号的最好名次更靠前，应该排在前面。
    """
    candidates = reciprocal_rank_fusion(
        [ranked_vector("甲", [11]), ranked_keyword("乙", [22])]
    )

    assert [c.chunk.chunk_id for c in candidates] == [11, 22]
    assert candidates[0].rrf_score == pytest.approx(candidates[1].rrf_score)


def test_a_tie_on_both_score_and_rank_is_broken_by_first_appearance():
    """总分相同、最好名次也相同时，先被召回的那条排前面。"""
    candidates = reciprocal_rank_fusion(
        [ranked_vector("甲", [55]), ranked_keyword("乙", [77])]
    )

    assert [c.chunk.chunk_id for c in candidates] == [55, 77]


def test_ordering_is_deterministic_across_repeated_runs():
    """★ 同样的输入必须得到完全一样的顺序。

    召回结果会直接决定回答依据，顺序抖动会让同一句话两次问出不同答案。
    """
    lists = [
        ranked_vector("甲", [3, 1, 2]),
        ranked_keyword("甲", [2, 3]),
        ranked_keyword("乙", [1, 4]),
    ]

    first = [c.chunk.chunk_id for c in reciprocal_rank_fusion(lists)]
    second = [c.chunk.chunk_id for c in reciprocal_rank_fusion(lists)]

    assert first == second


def test_limit_caps_the_candidate_count():
    candidates = reciprocal_rank_fusion(
        [ranked_vector("甲", list(range(1, 31)))], limit=5
    )

    assert len(candidates) == 5


def test_default_limit_is_twenty():
    candidates = reciprocal_rank_fusion([ranked_vector("甲", list(range(1, 41)))])

    assert len(candidates) == DEFAULT_CANDIDATE_LIMIT == 20


@pytest.mark.parametrize("bad_limit", [0, -1, MAX_CANDIDATE_LIMIT + 1, 100])
def test_out_of_range_limit_is_rejected(bad_limit):
    with pytest.raises(KnowledgeSearchError) as error:
        reciprocal_rank_fusion([ranked_vector("甲", [1])], limit=bad_limit)

    assert str(MAX_CANDIDATE_LIMIT) in str(error.value)


@pytest.mark.parametrize("bad_limit", [1.5, "5", None, True])
def test_non_integer_limit_is_rejected(bad_limit):
    with pytest.raises(KnowledgeSearchError):
        reciprocal_rank_fusion([ranked_vector("甲", [1])], limit=bad_limit)


def test_empty_input_returns_an_empty_list():
    assert reciprocal_rank_fusion([]) == []


def test_lists_with_no_results_are_harmless():
    assert reciprocal_rank_fusion([ranked_vector("甲", []), ranked_keyword("乙", [])]) == []


# --------------------------------------------------------------------------
# RRF：输入校验与纯函数性质
# --------------------------------------------------------------------------


def test_a_list_whose_type_disagrees_with_its_results_is_rejected():
    """★ retrieval_type 说向量、结果却是关键词结果 —— 必须在融合前就报错。

    否则名次会被记到错误的那一路上，而结果看起来完全正常。
    """
    inconsistent = RankedResults(
        retrieval_type="vector",
        query="甲",
        results=(make_keyword_result(11),),
    )

    with pytest.raises(KnowledgeSearchError) as error:
        reciprocal_rank_fusion([inconsistent])

    assert "vector" in str(error.value)


def test_an_unknown_retrieval_type_is_rejected():
    unknown = RankedResults(
        retrieval_type="hybrid",  # type: ignore[arg-type]
        query="甲",
        results=(make_keyword_result(11),),
    )

    with pytest.raises(KnowledgeSearchError):
        reciprocal_rank_fusion([unknown])


def test_fusion_is_a_pure_function():
    """★ 融合不连库、不调模型：模块源码里不该有这些东西的导入。"""
    import ast

    tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)

    forbidden = ("app.core.llm", "app.services.embedding", "langchain", "openai", "asyncpg")
    assert not [module for module in modules if module.startswith(forbidden)]


def test_fusion_does_not_mutate_its_inputs():
    lists = [ranked_vector("甲", [11, 22])]
    before = [list(ranked.results) for ranked in lists]

    reciprocal_rank_fusion(lists)

    assert [list(ranked.results) for ranked in lists] == before


# --------------------------------------------------------------------------
# hybrid_search：调用顺序与去重
# --------------------------------------------------------------------------


def test_the_original_question_is_searched_first():
    """★ 原问题代表用户的原意，必须第一个被召回。"""
    plan = make_plan(original="原问题", rewritten=["改写一", "改写二"])
    _, vector, _ = run_hybrid(plan)

    assert vector.queries[0] == "原问题"


def test_at_most_the_original_plus_two_rewrites_are_used():
    plan = make_plan(
        original="原问题", rewritten=["改写一", "改写二", "改写三", "改写四"]
    )
    _, vector, _ = run_hybrid(plan)

    assert vector.queries == ["原问题", "改写一", "改写二"]


def test_duplicate_queries_are_recalled_once():
    """★ 同一个检索表达不该把同一路召回跑两遍。"""
    plan = make_plan(original="原问题", rewritten=["原问题", "改写一"])
    _, vector, keyword = run_hybrid(plan)

    assert vector.queries == ["原问题", "改写一"]
    assert keyword.terms.count("原问题") == 1


def test_duplicate_queries_differing_only_in_case_are_recalled_once():
    plan = make_plan(original="Order Total", rewritten=["order total"])

    _, vector, _ = run_hybrid(plan)

    assert vector.queries == ["Order Total"]


def test_blank_queries_are_dropped():
    plan = make_plan(original="原问题", rewritten=["   ", ""])

    _, vector, _ = run_hybrid(plan)

    assert vector.queries == ["原问题"]


def test_keywords_are_recalled_through_the_keyword_searcher():
    plan = make_plan(original="原问题", keywords=["术语甲", "概念乙"])

    _, _, keyword = run_hybrid(plan)

    assert "术语甲" in keyword.terms
    assert "概念乙" in keyword.terms


def test_keywords_are_not_sent_to_the_vector_searcher():
    """关键词是用来做字面匹配的，不该再去算一次向量。"""
    plan = make_plan(original="原问题", keywords=["术语甲"])

    _, vector, _ = run_hybrid(plan)

    assert vector.queries == ["原问题"]


def test_the_search_queries_also_go_to_the_keyword_searcher():
    """改写后的整句也要走关键词召回：短句和标题型表达靠字面就能命中。"""
    plan = make_plan(original="原问题", rewritten=["改写一"], keywords=["术语甲"])

    _, _, keyword = run_hybrid(plan)

    assert keyword.terms == ["原问题", "改写一", "术语甲"]


def test_an_empty_query_plan_is_rejected():
    with pytest.raises(KnowledgeSearchError) as error:
        run_hybrid(make_plan(original="   "))

    assert "sk-" not in str(error.value)


def test_the_connection_is_forwarded_to_both_searchers():
    sentinel = object()
    plan = make_plan(original="原问题", keywords=["术语甲"])

    _, vector, keyword = run_hybrid(plan, connection=sentinel)

    assert {connection for _, _, connection in vector.calls} == {sentinel}
    assert {connection for _, _, connection in keyword.calls} == {sentinel}


def test_rewrite_query_is_never_called_here():
    """★ 改写是上一步的事，这一步不该再调一次模型。

    用源码检查而不是运行时打桩：这样连「不小心写了但没走到」也能拦住。
    """
    source = MODULE_PATH.read_text(encoding="utf-8")

    assert "rewrite_query" not in source
    assert "extract_search_metadata" not in source


# --------------------------------------------------------------------------
# hybrid_search：候选质量
# --------------------------------------------------------------------------


def test_candidates_are_deduplicated_by_chunk_id():
    plan = make_plan(original="原问题", rewritten=["改写一"])
    vector = FakeVectorSearcher({"原问题": [(1, 0.1), (2, 0.2)], "改写一": [(2, 0.3)]})

    candidates, _, _ = run_hybrid(plan, vector=vector)

    ids = [candidate.chunk.chunk_id for candidate in candidates]
    assert sorted(ids) == [1, 2]
    assert len(ids) == len(set(ids))
    # 2 号被两条查询各命中一次，是被融合累加过的
    assert by_id(candidates)[2].matched_queries == ("原问题", "改写一")


def test_candidate_count_is_capped_at_twenty():
    plan = make_plan(original="原问题")
    many = [(chunk_id, 0.1 * chunk_id) for chunk_id in range(1, 41)]
    vector = FakeVectorSearcher({"原问题": many})

    candidates, _, _ = run_hybrid(plan, vector=vector)

    assert len(candidates) == MAX_CANDIDATE_LIMIT == 20


def test_candidate_limit_is_configurable():
    plan = make_plan(original="原问题")
    vector = FakeVectorSearcher({"原问题": [(i, 0.1) for i in range(1, 11)]})

    candidates, _, _ = run_hybrid(plan, vector=vector, candidate_limit=3)

    assert len(candidates) == 3


@pytest.mark.parametrize("bad_limit", [0, -1, MAX_CANDIDATE_LIMIT + 1, 1.5, "5", None])
def test_invalid_candidate_limit_is_rejected(bad_limit):
    with pytest.raises(KnowledgeSearchError):
        run_hybrid(make_plan(original="原问题"), candidate_limit=bad_limit)


def test_a_chunk_hit_by_both_paths_outranks_a_single_path_hit():
    plan = make_plan(original="原问题", keywords=["术语甲"])
    vector = FakeVectorSearcher({"原问题": [(1, 0.5), (2, 0.1)]})
    keyword = FakeKeywordSearcher({"术语甲": [(2, 100.0)]})

    candidates, _, _ = run_hybrid(plan, vector=vector, keyword=keyword)

    # 2 号被两路同时命中，应该排到最前面
    assert candidates[0].chunk.chunk_id == 2


# --------------------------------------------------------------------------
# hybrid_search：失败降级
# --------------------------------------------------------------------------


def test_keyword_failure_keeps_the_vector_results():
    plan = make_plan(original="原问题", keywords=["术语甲"])
    vector = FakeVectorSearcher({"原问题": [(1, 0.1)]})
    keyword = FakeKeywordSearcher(errors={"术语甲": RuntimeError("boom")})

    candidates, _, _ = run_hybrid(plan, vector=vector, keyword=keyword)

    assert [c.chunk.chunk_id for c in candidates] == [1]


def test_vector_failure_keeps_the_keyword_results():
    plan = make_plan(original="原问题", keywords=["术语甲"])
    vector = FakeVectorSearcher(errors={"原问题": RuntimeError("boom")})
    keyword = FakeKeywordSearcher({"术语甲": [(1, 100.0)]})

    candidates, _, _ = run_hybrid(plan, vector=vector, keyword=keyword)

    assert [c.chunk.chunk_id for c in candidates] == [1]


def test_one_failing_query_does_not_drop_the_others():
    """★ 一条改写查询失败，不该把别的查询的召回结果一起丢掉。"""
    plan = make_plan(original="原问题", rewritten=["改写一"])
    vector = FakeVectorSearcher(
        {"原问题": [(1, 0.1)], "改写一": [(2, 0.2)]},
        errors={"改写一": RuntimeError("boom")},
    )

    candidates, _, _ = run_hybrid(plan, vector=vector)

    assert [c.chunk.chunk_id for c in candidates] == [1]


def test_one_failing_keyword_does_not_drop_the_others():
    plan = make_plan(original="原问题", keywords=["术语甲", "概念乙"])
    keyword = FakeKeywordSearcher(
        {"概念乙": [(2, 100.0)]}, errors={"术语甲": RuntimeError("boom")}
    )

    candidates, _, _ = run_hybrid(plan, keyword=keyword)

    assert [c.chunk.chunk_id for c in candidates] == [2]


def test_all_recalls_failing_raises_a_controlled_error():
    plan = make_plan(original="原问题", keywords=["术语甲"])
    vector = FakeVectorSearcher(errors={"原问题": RuntimeError("boom")})
    keyword = FakeKeywordSearcher(errors={"原问题": RuntimeError("boom"), "术语甲": RuntimeError("boom")})

    with pytest.raises(KnowledgeSearchError) as error:
        run_hybrid(plan, vector=vector, keyword=keyword)

    message = str(error.value)
    assert "RuntimeError" in message  # 只点出异常类名，便于定位
    assert "boom" not in message  # 但不带异常正文


def test_a_search_that_returns_nothing_is_not_a_failure():
    """召回成功但没命中，是正常结果，不是失败——不该报错。"""
    plan = make_plan(original="原问题")

    candidates, _, _ = run_hybrid(plan)

    assert candidates == []


def test_failure_log_never_contains_the_question_or_the_exception_body(caplog):
    import logging

    secret = "sk-canary-fusion-leak-0123456789abcdef"
    marker = "zz-question-marker-zz"
    question = f"关于 {marker} 的问题"
    plan = make_plan(original=question, keywords=["术语甲"])
    # 原问题既走向量也走关键词，两边都要失败，才会走到「全部失败」那条路
    vector = FakeVectorSearcher(errors={question: RuntimeError(f"401 {secret}")})
    keyword = FakeKeywordSearcher(
        errors={question: RuntimeError(f"401 {secret}"), "术语甲": RuntimeError(f"401 {secret}")}
    )

    with caplog.at_level(logging.WARNING):
        with pytest.raises(KnowledgeSearchError):
            run_hybrid(plan, vector=vector, keyword=keyword)

    assert "RuntimeError" in caplog.text
    assert marker not in caplog.text
    assert secret not in caplog.text
    assert "sk-" not in caplog.text


def test_the_final_error_message_does_not_leak_the_question():
    marker = "zz-question-marker-zz"
    plan = make_plan(original=f"关于 {marker} 的问题")
    vector = FakeVectorSearcher(errors={f"关于 {marker} 的问题": RuntimeError("boom")})
    keyword = FakeKeywordSearcher(errors={f"关于 {marker} 的问题": RuntimeError("boom")})

    with pytest.raises(KnowledgeSearchError) as error:
        run_hybrid(plan, vector=vector, keyword=keyword)

    assert marker not in str(error.value)


def test_parameter_errors_are_not_swallowed_by_the_degradation_path():
    """★ 调用参数非法要当场报错，不能被「失败降级」吸收掉。"""
    vector = FakeVectorSearcher()
    keyword = FakeKeywordSearcher()

    with pytest.raises(KnowledgeSearchError):
        run_hybrid(make_plan(original="原问题"), vector=vector, keyword=keyword, candidate_limit=999)

    assert vector.calls == []
    assert keyword.calls == []


# --------------------------------------------------------------------------
# hybrid_search：日志与通用性
# --------------------------------------------------------------------------


def test_failure_logging_records_the_recall_type_and_exception_class(caplog):
    import logging

    plan = make_plan(original="原问题", keywords=["术语甲"])
    vector = FakeVectorSearcher(errors={"原问题": TimeoutError("超时")})

    with caplog.at_level(logging.WARNING):
        run_hybrid(plan, vector=vector, keyword=FakeKeywordSearcher({"术语甲": [(1, 1.0)]}))

    assert "向量" in caplog.text
    assert "TimeoutError" in caplog.text


@pytest.mark.parametrize("term", FORBIDDEN_DOMAIN_TERMS)
def test_module_has_no_hardcoded_domain_vocabulary(term):
    assert term not in MODULE_PATH.read_text(encoding="utf-8")


def test_hybrid_search_does_not_change_the_query_plan():
    plan = make_plan(original="原问题", rewritten=["改写一"], keywords=["术语甲"])

    run_hybrid(plan)

    assert plan.original_query == "原问题"
    assert plan.rewritten_queries == ("改写一",)
    assert plan.keywords == ("术语甲",)
    assert plan.search_queries == ("原问题", "改写一")
