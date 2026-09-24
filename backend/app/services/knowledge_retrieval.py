"""统一检索编排：查询改写 → 混合召回 → 精排。

## 三个阶段，各自对自己的失败负责

| 阶段 | 谁负责 | 它自己的降级方式 |
| --- | --- | --- |
| 改写 | `query_rewrite.rewrite_query` | 模型失败 → 退回「只用原问题」 |
| 召回 | `retrieval_fusion.hybrid_search` | 单路失败 → 保留另一路；两路全失败 → 抛 `KnowledgeSearchError` |
| 精排 | `reranker.rerank_candidates` | 供应商失败 → 退回 RRF 顺序 |

所以这一层**通篇没有 try/except**。每个环节都已经把「自己失败了该怎么办」
想清楚并实现过了；在这里再包一层，只会让「谁降级了、降级成什么样」变得说不清，
而且新写的那一份迟早会和各层内部的实现漂开。

唯一需要这一层自己判断的是**参数和配置**——那两类是编程错误与部署错误，
必须当场暴露：

- 问题为空、`final_top_k` 非法 → `KnowledgeRetrievalError`；
- 配置缺 Key、候选上限越界 → `ConfigurationError`（直接来自配置层）。

## 它不捕获 KnowledgeSearchError

召回阶段两路全失败时抛出的 `KnowledgeSearchError` 会**原样往上传递**，
由 API 层映射成 503「知识库暂时不可用」。不在这里吞掉它，是因为
「检索失败」和「没有相关资料」必须区分开：后者是正常结果（返回空来源、
不调回答模型），前者是故障（该报错）。

## 粗召回要宽，精排之后才窄

```
请求 top_k = 3
  → hybrid_search(candidate_limit = 20)   先捞 20 条
  → rerank_candidates(top_n = 3)          精排后留 3 条
  → 回答模型
```

**不要把 `top_k` 当成每一路召回的宽度。** 交叉编码再准，也只能在候选里挑；
如果召回阶段就只捞 3 条，正确答案很可能压根不在里面，后面谁都救不回来。

## 精排只用原问题

召回阶段发散——用改写问题多开几条路，宁可多捞；
排序阶段收敛——回到用户真正问的那句话做相关性判断。
改写是模型换的说法，可能把限定词抹平，拿它精排会让最终结果偏离用户原意。

## 本模块不做什么

不拼 Prompt、不调回答模型、不算向量、不连数据库、没有第二套检索逻辑。
它只做一件事：把三个已经实现好的环节按正确顺序、用正确的参数串起来。
"""

from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass

from app.core.config import get_settings
from app.core.exceptions import AppError
from app.services.query_rewrite import QueryRewriteResult, rewrite_query
from app.services.reranker import rerank_candidates
from app.services.retrieval_fusion import RetrievalCandidate, hybrid_search

# 三个环节的调用签名。用 ... 而不是精确签名：替身只需要接受
# 对应的关键字参数即可，测试不必复刻每一个默认值。
Rewriter = Callable[[str], Awaitable[QueryRewriteResult]]
HybridRetriever = Callable[..., Awaitable[Sequence[RetrievalCandidate]]]
CandidateReranker = Callable[..., Awaitable[Sequence[RetrievalCandidate]]]


class KnowledgeRetrievalError(AppError):
    """编排层的受控错误：调用参数非法。

    刻意与 `KnowledgeSearchError` 分开，因为它们该被区别对待：

    - 本异常 = 「参数传错了」——编程/调用方的锅，该当场暴露；
    - `KnowledgeSearchError` = 「检索这次没能给出候选」——故障，由 API 层
      映射成 503。

    合成一个类型的话，API 层就没法只靠类型把这两件事分开，
    只能去猜异常消息——那是最不该依赖的东西。
    """


@dataclass(frozen=True)
class RetrievalResult:
    """一次完整检索的产物。

    `candidates_considered` 是**精排前**的候选数，`results` 是精排后的最终切片。
    分开记是因为它们回答的是两个不同的问题：「召回捞回来多少」与
    「最后交给回答模型几条」——只留一个数字的话，排查召回质量时会看不出来
    到底是召回没捞到，还是捞到了却被精排丢了。

    `rerank_applied` 说的是**这次请求真的精排过**，不是「精排功能开着」。
    """

    original_query: str
    search_queries: tuple[str, ...]
    candidates_considered: int
    rerank_applied: bool
    results: tuple[RetrievalCandidate, ...]


def normalize_question(question: str) -> str:
    """去掉首尾空白并校验非空。

    空问题必须在**任何外部调用之前**拦住：改写要花一次模型调用、
    召回要花一次 embedding 调用，为一个空字符串付这些钱毫无意义。
    """
    if question is None:
        raise KnowledgeRetrievalError("检索问题不能为空。")

    normalized = question.strip()
    if not normalized:
        raise KnowledgeRetrievalError("检索问题不能是空白字符，请提供具体问题。")
    return normalized


def validate_final_top_k(final_top_k: int, *, candidate_limit: int) -> int:
    """校验最终留给回答模型的条数。

    上限用**候选上限**而不是某个写死的数字：最终条数不可能超过候选总数，
    配成这样只可能是参数写反了。这里报错而不是悄悄截断——
    静默截断会让「要 3 条却只给了 2 条」变成一个没人发现的安静错误。
    """
    if isinstance(final_top_k, bool) or not isinstance(final_top_k, int):
        raise KnowledgeRetrievalError(
            f"final_top_k 必须是整数，当前是 {type(final_top_k).__name__}。"
        )

    if final_top_k < 1:
        raise KnowledgeRetrievalError(f"final_top_k 必须是正整数，当前是 {final_top_k}。")

    if final_top_k > candidate_limit:
        raise KnowledgeRetrievalError(
            f"final_top_k 不能超过候选上限 {candidate_limit}，当前是 {final_top_k}。"
        )
    return final_top_k


async def retrieve_knowledge(
    question: str,
    *,
    final_top_k: int | None = None,
    rewriter: Rewriter = rewrite_query,
    hybrid_retriever: HybridRetriever = hybrid_search,
    candidate_reranker: CandidateReranker = rerank_candidates,
) -> RetrievalResult:
    """把用户问题走完「改写 → 召回 → 精排」，返回最终候选。

    三个环节都可注入，测试因此能在不碰模型、不碰数据库的前提下
    断言调用顺序与参数。默认值就是生产实现——「默认就是真的」，
    不会出现「上线忘了接线」这种没人发现的状态。

    `final_top_k` 不传时用配置里的 `RAG_FINAL_TOP_K`。
    """
    normalized = normalize_question(question)

    settings = get_settings().require_rerank_settings()
    limit = (
        settings.final_top_k
        if final_top_k is None
        else validate_final_top_k(final_top_k, candidate_limit=settings.candidate_limit)
    )

    plan = await rewriter(normalized)

    candidates = await hybrid_retriever(plan, candidate_limit=settings.candidate_limit)

    if not candidates:
        # 一条候选都没有：精排没有输入，一次调用都不该发。
        # 这是正常结果（知识库里可能确实没有相关内容），不是错误。
        return RetrievalResult(
            original_query=plan.original_query,
            search_queries=plan.search_queries,
            candidates_considered=0,
            rerank_applied=False,
            results=(),
        )

    final = await candidate_reranker(plan.original_query, candidates, top_n=limit)

    return RetrievalResult(
        original_query=plan.original_query,
        search_queries=plan.search_queries,
        candidates_considered=len(candidates),
        # 判据是「有没有哪条候选真的拿到了精排分数」，而不是配置开关：
        # 开关开着但这次调用失败了，精排其实一次都没生效。
        rerank_applied=any(item.rerank_score is not None for item in final),
        results=tuple(final),
    )
