"""多路召回的融合：Reciprocal Rank Fusion（RRF）+ 混合召回编排。

## 为什么用排名融合，而不是把分数加权相加

向量召回给出的是**余弦距离**（越小越像，取值 0~2 的一个几何量），
关键词召回给出的是**命中层级分**（越大越好，取值是我们自己定的 0~100 的序数）。
这两个数：

- 量纲不同：一个的 0.1 和另一个的 10 说的完全不是一回事；
- 分布不同：余弦距离挤在一个很窄的区间里，关键词分是几个离散档位；
- 含义不同：一个衡量「意思像不像」，一个衡量「字面对没对上」。

把它们加起来，等于在比较两个不同单位的数。谁的量级大谁说了算，
而这个「谁大」完全取决于我们当初把权重量成多少——那不是检索质量，那是巧合。

RRF 绕开了这件事：**只用名次，不用分数**。

    score(chunk) = Σ 1 / (k + rank_i(chunk))

在第 i 路里排第几，就贡献 1/(k+名次)。k 默认 60，作用是把高名次之间的差距压平
（第 1 名和第 2 名的贡献是 1/61 和 1/62，几乎一样），让「多路都命中」
比「一路排第一」更能拉开差距。这正是融合想要的：

- 被多路同时命中的切片 → 累加 → 排前面（它是「大家都能找到」的东西）；
- 只在某一路排第一的切片 → 只有一个 1/61 → 排在后面。

## 去重与排名语义

- **按 chunk_id 去重**：同一段切片在多路里命中多次，最终只出现一次；
- `vector_rank`：它在**所有向量结果列表**里最好的一次名次（1 起）；
- `keyword_rank`：在所有关键词结果列表里最好的一次名次；
- 某一侧完全没命中就是 `None`，不是 0——0 是个合法名次的意思，而它压根没参与。

## 不伪造分数

候选上带着四个可选分数：`distance` / `similarity`（向量专有）、
`keyword_score` / `matched_terms`（关键词专有）。**没有的那一侧就是 None 或空**。
给关键词独占的候选编一个 distance，或者给向量独占的候选编一个 keyword_score，
都会让下游拿到一个看起来合法、实际无意义的数——这类错误不会让任何地方报错，
只会让排序和判断悄悄变歪。

## hybrid_search 为什么也在这个模块

它本可以放进 knowledge_search.py（检索的家），但那样会成环：
knowledge_search 要调关键词召回，而关键词召回要用 knowledge_search 的
`ChunkContent` 和 `connection_scope`，两个模块互相 import。
所以编排放在依赖链的末端：retrieval_fusion → {knowledge_search,
knowledge_keyword_search}，单向，没有环，也不必为此再造一个共享模块。

## 本模块不做什么

不连数据库（融合是纯函数）、不调模型、不调 embedding、不做精排
（rerank_score 现在恒为 None，占位等下一阶段）。
"""

import logging
from collections.abc import Awaitable, Callable, Iterable, Sequence
from dataclasses import dataclass, field
from typing import Literal

from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.config import MAX_REWRITTEN_QUERIES_LIMIT
from app.services.knowledge_keyword_search import (
    MAX_KEYWORD_LIMIT,
    KeywordSearchResult,
    search_knowledge_keywords,
)
from app.services.knowledge_search import (
    MAX_TOP_K,
    ChunkContent,
    KnowledgeSearchError,
    KnowledgeSearchResult,
    search_knowledge,
    validate_top_k,
)
from app.services.query_rewrite import QueryRewriteResult

# RRF 的平滑常数。60 是文献里的常用值：它把「第 1 名 vs 第 5 名」的差距压得比较平，
# 于是「多路命中」比「单路第一」更容易胜出——这正是融合的目的。
RRF_K = 60

# 候选上限。融合之后最多就这么多条往下走（精排、最终上下文都在这个数之内）。
DEFAULT_CANDIDATE_LIMIT = 20
MIN_CANDIDATE_LIMIT = 1
MAX_CANDIDATE_LIMIT = 20

# 每次向量召回取多少条。取合法的最大值：召回阶段要的是「别漏」，
# 排序和裁剪交给融合与后续的精排。
DEFAULT_PER_QUERY_TOP_K = MAX_TOP_K

# 检索表达的上限：原问题 + 最多两条改写。
# 从配置层的常量推导而不是写死 3，改了改写条数上限这里自动跟上。
MAX_SEARCH_QUERIES = 1 + MAX_REWRITTEN_QUERIES_LIMIT

RetrievalType = Literal["vector", "keyword"]
RETRIEVAL_TYPES: tuple[RetrievalType, ...] = ("vector", "keyword")

# 两路召回的调用签名。用 ... 而不是精确签名：替身只需要接受
# (query, *, top_k/limit, connection) 这几个关键字参数即可。
VectorSearcher = Callable[..., Awaitable[Sequence[KnowledgeSearchResult]]]
KeywordSearcher = Callable[..., Awaitable[Sequence[KeywordSearchResult]]]

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RankedResults:
    """一路召回的结果，连同它的来源信息。

    **来源必须显式写出来**，不能靠「它在列表里的第几个」去猜：
    名次要被记进 vector_rank 还是 keyword_rank 完全取决于它属于哪一路，
    猜错的后果是「结果看起来正常，但排名语义是错的」，几乎无法察觉。

    results 是有序的：第 1 个元素的 rank 就是 1。
    """

    retrieval_type: RetrievalType
    query: str
    results: tuple[KnowledgeSearchResult | KeywordSearchResult, ...]


@dataclass(frozen=True)
class RetrievalCandidate:
    """融合后的一个候选切片。

    这里同时住着两件东西：**切片内容**（chunk，两路共有）和**分数**
    （各路的可选字段，没有就是 None）。把两者分开写，是为了让
    「这条候选是被哪一路找出来的」一眼可见。
    """

    chunk: ChunkContent
    vector_rank: int | None
    keyword_rank: int | None
    rrf_score: float
    matched_queries: tuple[str, ...]
    distance: float | None = None
    similarity: float | None = None
    keyword_score: float | None = None
    matched_terms: tuple[str, ...] = ()
    rerank_score: float | None = None


@dataclass
class _Ledger:
    """融合过程中的临时账本。可变是有意的：它只活在这一个函数里。"""

    chunk: ChunkContent
    first_seen: int
    rrf_score: float = 0.0
    vector_rank: int | None = None
    keyword_rank: int | None = None
    distance: float | None = None
    similarity: float | None = None
    keyword_score: float | None = None
    matched_terms: tuple[str, ...] = ()
    matched_queries: list[str] = field(default_factory=list)


# --------------------------------------------------------------------------
# 校验与工具
# --------------------------------------------------------------------------


def validate_candidate_limit(limit: int) -> int:
    """候选上限必须是 1~20 的整数。越界报错而不是截断。"""
    if isinstance(limit, bool) or not isinstance(limit, int):
        raise KnowledgeSearchError(f"candidate_limit 必须是整数，当前是 {type(limit).__name__}。")

    if not MIN_CANDIDATE_LIMIT <= limit <= MAX_CANDIDATE_LIMIT:
        raise KnowledgeSearchError(
            f"candidate_limit 必须在 {MIN_CANDIDATE_LIMIT} 到 {MAX_CANDIDATE_LIMIT} 之间，"
            f"当前是 {limit}。"
        )
    return limit


def validate_rrf_k(k: int) -> int:
    """RRF 的平滑常数必须是正整数。"""
    if isinstance(k, bool) or not isinstance(k, int):
        raise KnowledgeSearchError(f"k 必须是整数，当前是 {type(k).__name__}。")

    if k < 1:
        raise KnowledgeSearchError(f"k 必须是正整数，当前是 {k}。")
    return k


def dedupe_terms(values: Iterable[str], *, limit: int | None = None) -> tuple[str, ...]:
    """去首尾空白、丢空串、大小写不敏感去重；保留首次出现的原文。

    limit 用来钉死「原问题 + 最多两条改写」这条上限：即使调用方递进来一个
    超标的计划，也不会真的去跑第 4 条召回。

    大小写不敏感只对英文有意义（Order 和 order 是同一个检索表达），
    中文不受影响。保留原文而不是统一成小写：检索词要原样送去匹配。
    """
    seen: set[str] = set()
    kept: list[str] = []

    for value in values:
        if not isinstance(value, str):
            continue
        text = value.strip()
        if not text:
            continue
        key = text.casefold()
        if key in seen:
            continue
        seen.add(key)
        kept.append(text)
        if limit is not None and len(kept) >= limit:
            break

    return tuple(kept)


def _validate_ranked(ranked: RankedResults) -> None:
    """检查这一路声明的来源和它实际装的结果对不对得上。

    对不上就必须当场报错：名次会被记到错误的那一路上，
    而融合结果看起来完全正常——这是最难发现的一类错误。
    """
    if ranked.retrieval_type not in RETRIEVAL_TYPES:
        raise KnowledgeSearchError(
            f"未知的召回类型：{ranked.retrieval_type!r}，"
            f"只能是 {'、'.join(RETRIEVAL_TYPES)}。"
        )

    expected = KnowledgeSearchResult if ranked.retrieval_type == "vector" else KeywordSearchResult
    for hit in ranked.results:
        if not isinstance(hit, expected):
            raise KnowledgeSearchError(
                f"召回类型标为 {ranked.retrieval_type}，却带了一条 {type(hit).__name__}："
                "名次会被记到错误的召回路上。"
            )


def _hit_scores(
    hit: KnowledgeSearchResult | KeywordSearchResult,
    retrieval_type: RetrievalType,
) -> tuple[float | None, float | None, float | None, tuple[str, ...]]:
    """取出这一次命中携带的分数：向量侧是距离，关键词侧是命中分。

    **没有的那一侧一律 None / 空**，绝不互补一个数字出来。
    """
    if retrieval_type == "vector":
        return hit.distance, hit.similarity, None, ()  # type: ignore[union-attr]
    return None, None, hit.keyword_score, tuple(hit.matched_terms)  # type: ignore[union-attr]


def _best_rank(ledger: _Ledger) -> int:
    """这条候选在所有路里最好的一次名次，用于平分时的排序。

    一路都没命中是不可能的（账本因命中而生），所以这里必然有值。
    """
    ranks = [rank for rank in (ledger.vector_rank, ledger.keyword_rank) if rank is not None]
    return min(ranks) if ranks else 0


# --------------------------------------------------------------------------
# 融合
# --------------------------------------------------------------------------


def reciprocal_rank_fusion(
    ranked_lists: Sequence[RankedResults],
    *,
    k: int = RRF_K,
    limit: int = DEFAULT_CANDIDATE_LIMIT,
) -> list[RetrievalCandidate]:
    """把多路有序结果按 RRF 融合成一个候选列表。

    纯函数：不连数据库、不调模型、不改动入参。同样的输入永远得到同样的顺序——
    候选顺序会直接决定回答依据，顺序抖动意味着同一句话两次问出不同答案。
    """
    validate_rrf_k(k)
    capped = validate_candidate_limit(limit)

    ledger_by_chunk: dict[int, _Ledger] = {}

    for ranked in ranked_lists:
        _validate_ranked(ranked)

        for position, hit in enumerate(ranked.results, start=1):
            chunk = hit.chunk
            ledger = ledger_by_chunk.get(chunk.chunk_id)

            if ledger is None:
                # first_seen 记的是「第几个被召回的」，用于平分时保持稳定
                ledger = _Ledger(chunk=chunk, first_seen=len(ledger_by_chunk))
                ledger_by_chunk[chunk.chunk_id] = ledger

            ledger.rrf_score += 1.0 / (k + position)

            if ranked.query not in ledger.matched_queries:
                ledger.matched_queries.append(ranked.query)

            if ranked.retrieval_type == "vector":
                if ledger.vector_rank is None or position < ledger.vector_rank:
                    ledger.vector_rank = position
                    distance, similarity, _, _ = _hit_scores(hit, "vector")
                    ledger.distance, ledger.similarity = distance, similarity
            else:
                if ledger.keyword_rank is None or position < ledger.keyword_rank:
                    ledger.keyword_rank = position
                    _, _, keyword_score, matched_terms = _hit_scores(hit, "keyword")
                    ledger.keyword_score = keyword_score
                    ledger.matched_terms = matched_terms

    ordered = sorted(
        ledger_by_chunk.values(),
        key=lambda ledger: (
            -ledger.rrf_score,  # 分数高的在前
            _best_rank(ledger),  # 平分时：最好名次靠前的在前
            ledger.first_seen,  # 再平分：先被召回的在前
            ledger.chunk.chunk_id,  # 最后兜底：保证全序，结果一定稳定
        ),
    )

    return [
        RetrievalCandidate(
            chunk=ledger.chunk,
            vector_rank=ledger.vector_rank,
            keyword_rank=ledger.keyword_rank,
            rrf_score=ledger.rrf_score,
            matched_queries=tuple(ledger.matched_queries),
            distance=ledger.distance,
            similarity=ledger.similarity,
            keyword_score=ledger.keyword_score,
            matched_terms=ledger.matched_terms,
        )
        for ledger in ordered[:capped]
    ]


# --------------------------------------------------------------------------
# 混合召回编排
# --------------------------------------------------------------------------


async def hybrid_search(
    query_plan: QueryRewriteResult,
    *,
    candidate_limit: int = DEFAULT_CANDIDATE_LIMIT,
    per_query_top_k: int = DEFAULT_PER_QUERY_TOP_K,
    vector_searcher: VectorSearcher = search_knowledge,
    keyword_searcher: KeywordSearcher = search_knowledge_keywords,
    connection: AsyncConnection | None = None,
) -> list[RetrievalCandidate]:
    """按查询计划做多路召回，再用 RRF 融合成一个去重候选列表。

    召回顺序（**顺序执行**，不并发）：

    1. 对每个检索表达（原问题 + 最多两条改写）做一次向量召回；
    2. 对每个检索表达**和**每个关键词做一次关键词召回。

    为什么顺序而不是并发：这个函数跑在一条 AsyncConnection 上，
    同一个连接同时发多条 SQL 是错的（连接不是并发安全的）。
    当前规模下一次召回也就几十毫秒，并发带来的复杂度不值得。

    失败降级：任一路、任一查询失败都只跳过它，其它路照常返回；
    **两路全部失败**才抛受控错误——那时确实没有任何候选可给。
    参数非法（上限越界、计划为空）不属于「外部失败」，当场报错。
    """
    limit = validate_candidate_limit(candidate_limit)
    top_k = validate_top_k(per_query_top_k)

    queries = dedupe_terms(query_plan.search_queries, limit=MAX_SEARCH_QUERIES)
    if not queries:
        # 真走到这里说明调用方给了一个没有原问题的计划。改写那一步不会
        # 产出这种东西，所以这是编程错误，不该被降级成「返回空列表」。
        raise KnowledgeSearchError("查询计划里没有任何可检索的表达。")

    terms = dedupe_terms([*queries, *query_plan.keywords])

    ranked_lists: list[RankedResults] = []
    failures: list[str] = []
    attempts = 0
    successes = 0

    for query in queries:
        attempts += 1
        try:
            hits = await vector_searcher(query, top_k=top_k, connection=connection)
        except Exception as error:  # noqa: BLE001
            failures.append(type(error).__name__)
            # 只记召回类型与异常类名：查询文本属于用户数据，
            # 异常正文可能带着连接串、密钥和 SQL 参数。
            logger.warning("向量召回失败，跳过这条查询：%s", type(error).__name__)
            continue
        successes += 1
        if hits:
            ranked_lists.append(RankedResults("vector", query, tuple(hits)))

    for term in terms:
        attempts += 1
        try:
            hits = await keyword_searcher(term, limit=MAX_KEYWORD_LIMIT, connection=connection)
        except Exception as error:  # noqa: BLE001
            failures.append(type(error).__name__)
            logger.warning("关键词召回失败，跳过这个检索词：%s", type(error).__name__)
            continue
        successes += 1
        if hits:
            ranked_lists.append(RankedResults("keyword", term, tuple(hits)))

    if attempts and successes == 0:
        # 全部失败。错误信息里只点出异常类名——它足够定位问题，
        # 又不会把异常正文（可能含密钥）和用户问题带出去。
        detail = "、".join(sorted(set(failures)))
        raise KnowledgeSearchError(
            f"向量召回与关键词召回全部失败（{detail}），无法返回候选。"
        )

    return reciprocal_rank_fusion(ranked_lists, limit=limit)
