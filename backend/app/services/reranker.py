"""精排（rerank）：把召回出来的候选按「真的答不答这个问题」重新排序。

## 精排和向量检索有什么区别

向量检索是**双塔**结构：问题和文档各自独立算成一个向量，再比两个向量的距离。
问题那边的向量在算的时候，完全不知道候选文档长什么样。它很快（文档向量可以
提前算好、建索引），但精度有上限——两段文字「像」不等于「这段回答了那个问题」。

精排是**交叉编码**（cross-encoder）：把问题和一段候选**拼在一起**送进模型，
模型同时看到两边，逐条判断相关性。它准得多，代价是每条候选都要单独跑一次推理，
所以只能作用在少量候选上。这就解释了整条链路为什么要分两步：

    全库 48 条 ──向量召回（快，能扫全库）──▶ 20 条 ──精排（慢，但准）──▶ 5 条

在全库上直接跑精排要 48 次推理，而且大部分是白跑的；先召回 20 条再精排，
推理次数降到 20 次，而召回阶段已经保证「答案大概率就在这 20 条里」。
用可接受的代价换到明显更好的排序，这就是「先召回 Top 20、再重排成 Top 5」。

## 为什么精排只拿原问题

召回阶段用改写问题是对的——多几条路，多捞点候选回来。但**最终判断相关性**
必须回到用户真正问的那句话：改写是模型换的说法，它可能把一个限定词抹平
（把具体的范围、时间、对象换成笼统的说法），拿它去精排，选出来的候选
就偏离了用户的原意。召回可以发散，排序必须收敛到原问题。

## 为什么要退回 RRF 顺序

精排是**增益**步骤，不是必需步骤。它挂了（超时、限流、5xx、响应畸形），
召回阶段的候选**仍然是有效的**，只是排序不如精排准。所以正确的反应是
退回 RRF 顺序继续回答，而不是让整个问答失败。

但界线必须划清楚，三类错误三种处理：

| 错误类型 | 例子 | 处理 |
| --- | --- | --- |
| 供应商故障 | 超时、429、5xx、响应畸形 | 降级回 RRF（`RerankerProviderError`） |
| 配置错误 | 缺 Key、候选上限写成 99 | 抛 `ConfigurationError`，当场暴露 |
| 程序错误 | `TypeError`、`AssertionError` | 不捕获，直接冒泡 |

前两类要是混在一起，「Key 没填」和「服务挂了」就会长得一模一样，
排查时完全分不清——而这两种的处理方式正好相反（一个要改配置，一个只要等）。

## 关于响应格式

`qwen3-rerank` 的 `results` 在**响应顶层**，不像 `gte-rerank-v2` 那样嵌在
`output.results` 下面；它也不支持 `return_documents`。这两点都是查过官方文档确认的，
不要按另一套格式解析。每个结果项只有两个字段：`index`（提交时的下标）
和 `relevance_score`（0.0~1.0，且只对同一次请求内的相对排序有意义）。

## 本模块不做什么

不连数据库、不调 LLM、不调 embedding、不自己读环境变量、不把精排分数
和 RRF 分数相加（量纲不同，融合只在召回阶段做一次）。
"""

import logging
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Protocol

import httpx

from app.core.config import RERANK_PATH, RerankSettings, get_settings
from app.core.exceptions import AppError
from app.services.retrieval_fusion import RetrievalCandidate

# 官方给 qwen3-rerank 的默认任务指令：偏向「能回答这个问题的段落」，
# 而不是「语义相似的段落」。问答检索正是我们想要的排序策略。
# 官方建议用英文书写，且只有 qwen3 系列认这个参数。
RERANK_INSTRUCT = (
    "Given a web search query, retrieve relevant passages that answer the query."
)

# relevance_score 的官方取值范围
MIN_RELEVANCE_SCORE = 0.0
MAX_RELEVANCE_SCORE = 1.0

# 候选文本的两个标签。与 search_text 的写法保持一致，
# 但这里特意重新声明而不从 knowledge_metadata 导入：那边是入库链路，
# 为了两个字符串把 langchain/pydantic 那一串依赖拖进来不值得。
DOCUMENT_LABEL = "文档"
SECTION_LABEL = "小节"

logger = logging.getLogger(__name__)


class RerankerError(AppError):
    """精排相关的可预期错误基类（参数非法等）。

    `rerank_candidates` **不**捕获它——参数写错是调用方的 bug，
    安静地降级只会让 bug 一直藏着。
    """


class RerankerProviderError(RerankerError):
    """供应商侧故障：超时、限流、状态码异常、响应畸形。

    这一类才是调用层应当降级回 RRF 顺序的错误。它继承 RerankerError 是为了
    让「精排出的问题」有一个共同基类，而捕获时只捕它、不捕父类。
    """


@dataclass(frozen=True)
class RerankItem:
    """一条精排结果：候选在**提交时的下标**，以及它的相关性分数。"""

    index: int
    relevance_score: float


class Reranker(Protocol):
    """精排器的能力契约。

    只要满足这个形状就能被 `rerank_candidates` 使用——测试里的替身、
    将来换一家供应商的实现，都不需要继承什么基类。

    把它定义成 Protocol 而不是抽象基类，是为了让依赖注入变成一件**零成本**的事：
    替身不必假装自己是 DashScope 的实现，它只是一个「能 rerank 的东西」。
    """

    async def rerank(
        self,
        query: str,
        documents: Sequence[str],
        *,
        top_n: int,
    ) -> Sequence[RerankItem]: ...


# --------------------------------------------------------------------------
# 纯函数
# --------------------------------------------------------------------------


def normalize_query_text(query: str) -> str:
    """去掉首尾空白并校验非空。

    空查询发出去只会白花一次调用，而且精排结果毫无意义。
    """
    if query is None:
        raise RerankerError("精排用的查询不能为空。")

    normalized = query.strip()
    if not normalized:
        raise RerankerError("精排用的查询不能是空白字符。")
    return normalized


def validate_top_n(top_n: int) -> int:
    """精排要留几条，必须是正整数。"""
    if isinstance(top_n, bool) or not isinstance(top_n, int):
        raise RerankerError(f"top_n 必须是整数，当前是 {type(top_n).__name__}。")

    if top_n < 1:
        raise RerankerError(f"top_n 必须是正整数，当前是 {top_n}。")
    return top_n


def build_rerank_url(base_url: str) -> str:
    """拼出最终请求地址：base_url 去掉末尾的 /，再接上 /reranks。

    配置层已经拦住了「base_url 本身就带 /reranks」的情况，
    所以这里只会拼上一次。
    """
    return f"{base_url.rstrip('/')}{RERANK_PATH}"


def build_rerank_payload(
    *,
    model: str,
    query: str,
    documents: Sequence[str],
    top_n: int,
) -> dict[str, object]:
    """组装请求体。

    字段名与层级严格按官方文档：qwen3-rerank 不用 `input` 包一层，
    query / documents / top_n / instruct 与 model 平级。
    **不设置 return_documents**：这个模型不支持它（只有 gte-rerank-v2 和
    qwen3-vl-rerank 支持），而且我们要的是排名，回传一遍正文纯属浪费带宽。
    """
    return {
        "model": model,
        "query": query,
        "documents": list(documents),
        "top_n": top_n,
        "instruct": RERANK_INSTRUCT,
    }


def build_rerank_document(candidate: RetrievalCandidate) -> str:
    """把一条候选拼成给精排模型看的文本：文档标题 + 小节标题 + 正文。

    **只放这三样。** 内部主键、source_file、向量、RRF 的排名和分数都不进：
    精排判的是「这段文字答不答这个问题」，给它排名信息只会干扰判断，
    给它主键则完全无用，还平白多一份泄露面。

    不做截断：当前切片远低于 qwen3-rerank 单条 4,000 token 的上限，
    在没有证据的情况下砍正文，只会让模型看不到答案。
    """
    chunk = candidate.chunk
    return (
        f"{DOCUMENT_LABEL}：{chunk.document_title}\n"
        f"{SECTION_LABEL}：{chunk.section_title}\n\n"
        f"{chunk.content}"
    )


def parse_rerank_response(
    payload: object,
    *,
    document_count: int,
    top_n: int,
) -> list[RerankItem]:
    """严格校验并解析精排响应，返回按相关性排好的结果。

    校验一长串是有原因的：这是**第三方返回的数据**，它可能因为我们发错了
    请求、供应商改了格式、或者中间被截断而变得奇形怪状。每一条都可能让
    「按 index 映射回候选」这一步错位，而错位的表现是「排序看起来正常但
    内容对不上」——最难发现的一类问题。所以宁可全部拒掉退回 RRF。

    最后**不信任供应商的返回顺序**，按「分数降序、同分按原始下标升序」
    自己排：同分时按原始下标是为了让同样的响应永远得到同样的顺序。
    """
    if not isinstance(payload, Mapping):
        raise RerankerProviderError("精排响应不是一个 JSON 对象。")

    results = payload.get("results")
    if not isinstance(results, list):
        # 必须是 list 而不是「可迭代就行」：字符串也能迭代，
        # 那样会把 "results" 的每个字符当成一条结果。
        raise RerankerProviderError("精排响应里没有 results 数组。")
    if not results:
        raise RerankerProviderError("精排响应里的 results 是空的。")

    items: list[RerankItem] = []
    seen_indexes: set[int] = set()

    for entry in results:
        if not isinstance(entry, Mapping):
            raise RerankerProviderError("精排响应里的结果项不是对象。")

        index = entry.get("index")
        score = entry.get("relevance_score")

        # bool 是 int 的子类，True 会被当成 1 悄悄放过去，所以先排掉
        if isinstance(index, bool) or not isinstance(index, int):
            raise RerankerProviderError("精排响应里的 index 不是整数。")
        if not 0 <= index < document_count:
            raise RerankerProviderError("精排响应里的 index 超出候选范围。")
        if index in seen_indexes:
            raise RerankerProviderError("精排响应里出现了重复的 index。")

        if isinstance(score, bool) or not isinstance(score, (int, float)):
            raise RerankerProviderError("精排响应里的 relevance_score 不是数字。")

        number = float(score)
        if not math.isfinite(number):
            # json 解析默认接受 NaN / Infinity 字面量，所以这一条检查不是多余的：
            # 一旦它们混进排序，顺序就完全不可预测了。
            raise RerankerProviderError("精排响应里的 relevance_score 不是有限数。")
        if not MIN_RELEVANCE_SCORE <= number <= MAX_RELEVANCE_SCORE:
            raise RerankerProviderError("精排响应里的 relevance_score 超出合法范围。")

        seen_indexes.add(index)
        items.append(RerankItem(index=index, relevance_score=number))

    items.sort(key=lambda item: (-item.relevance_score, item.index))
    return items[:top_n]


def apply_rerank_order(
    candidates: Sequence[RetrievalCandidate],
    items: Sequence[RerankItem],
    *,
    top_n: int,
) -> list[RetrievalCandidate]:
    """按精排结果重排候选，并按原顺序补足不够的部分。

    两件事必须说清楚：

    1. **写分数走 `dataclasses.replace`**，不就地改原对象。原候选是 RRF 的产物，
       别处（日志、调试、后续阶段）可能还拿着它；就地改字段会让「这份候选到底
       排过序没有」变成说不清的问题。
    2. **补上来的候选没有 rerank_score。** 它们确实没被精排过，编一个分数
       （哪怕是 0）就是在撒谎——下游会以为「它被评过，而且很差」。
    """
    ordered: list[RetrievalCandidate] = []
    used_positions: set[int] = set()

    for item in items:
        if len(ordered) >= top_n:
            break
        # 越界或重复的下标说明这份结果本身是畸形的。跳过它、继续按原顺序补足，
        # 效果等同于「安全退回 RRF 顺序」，而不是让一次下标错位把整条链路打断。
        if item.index in used_positions or not 0 <= item.index < len(candidates):
            continue
        used_positions.add(item.index)
        ordered.append(
            replace(candidates[item.index], rerank_score=item.relevance_score)
        )

    if len(ordered) < top_n:
        for position, candidate in enumerate(candidates):
            if len(ordered) >= top_n:
                break
            if position in used_positions:
                continue
            ordered.append(candidate)

    return ordered


# --------------------------------------------------------------------------
# Provider 适配器
# --------------------------------------------------------------------------


class DashScopeReranker:
    """百炼 `/reranks` 的适配器。

    职责只有一件：把一次精排请求发出去，把响应翻译成 `RerankItem`，
    并把**所有外部故障**统一成 `RerankerProviderError`。

    为什么用 httpx 而不是 openai SDK：qwen3-rerank 是一个独立的 `/reranks`
    路径，不是 `/chat/completions` 的形状，套 SDK 反而要自己绕一层；
    而 httpx 能直接控制超时、状态码、响应校验，测试里也能用 MockTransport
    把请求拦下来逐字段断言。

    客户端**不在这里常驻**：默认每次调用现建一个、用完就关（一个 AsyncClient
    不关会留下未关闭的连接池）。精排一次问答只调一次，为此常驻一个全局客户端
    不划算。要复用连接时可以从外面注入一个 client。
    """

    def __init__(
        self,
        settings: RerankSettings,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._settings = settings
        self._transport = transport
        self._client = client

    @property
    def endpoint(self) -> str:
        """最终请求地址。只读属性，方便测试断言而不必真的发请求。"""
        return build_rerank_url(self._settings.base_url)

    async def rerank(
        self,
        query: str,
        documents: Sequence[str],
        *,
        top_n: int,
    ) -> list[RerankItem]:
        limit = validate_top_n(top_n)

        if not documents:
            # 没有候选时发出去的请求只会换来一个 400，不如直接说「没有」
            return []

        payload = build_rerank_payload(
            model=self._settings.model,
            query=query,
            documents=list(documents),
            top_n=limit,
        )

        response = await self._post(payload)

        if response.status_code != httpx.codes.OK:
            # 只带状态码，不带响应正文——正文里可能有请求回显、Key 或用户问题
            raise RerankerProviderError(f"精排服务返回 {response.status_code}。")

        try:
            body = response.json()
        except ValueError:
            # `from None` 是必须的：httpx 的异常原文可能带着完整 URL 和响应内容，
            # 让它们顺着 __cause__ 出现在日志里，等于把「不记录响应正文」这条
            # 规矩绕过去了。
            raise RerankerProviderError("精排响应不是合法的 JSON。") from None

        return parse_rerank_response(
            body, document_count=len(documents), top_n=limit
        )

    async def _post(self, payload: dict[str, object]) -> httpx.Response:
        headers = {"Authorization": f"Bearer {self._settings.api_key}"}

        try:
            if self._client is not None:
                return await self._client.post(
                    self.endpoint, json=payload, headers=headers
                )

            async with httpx.AsyncClient(
                timeout=self._settings.timeout_seconds,
                transport=self._transport,
            ) as client:
                return await client.post(self.endpoint, json=payload, headers=headers)
        except httpx.TimeoutException as error:
            # 只保留异常类名：它能说清是连接超时还是读取超时
            raise RerankerProviderError(
                f"精排请求超时（{type(error).__name__}）。"
            ) from None
        except httpx.HTTPError as error:
            raise RerankerProviderError(
                f"精排请求失败（{type(error).__name__}）。"
            ) from None


def build_reranker(settings: RerankSettings) -> Reranker:
    """按配置创建生产适配器。

    写在函数里而不是模块顶层：任何一次 import（测试收集、Alembic env、脚本）
    都不该因为配置缺失或建客户端而受影响。
    """
    return DashScopeReranker(settings)


# --------------------------------------------------------------------------
# 编排
# --------------------------------------------------------------------------


async def rerank_candidates(
    query: str,
    candidates: Sequence[RetrievalCandidate],
    *,
    top_n: int | None = None,
    reranker: Reranker | None = None,
) -> list[RetrievalCandidate]:
    """用 `query` 对候选精排，返回最多 `top_n` 条。

    query 必须传**用户原问题**（`QueryRewriteResult.original_query`）：
    改写问题只负责扩大召回，最终相关性判断要回到用户真正问的那句话。

    执行顺序里有两处顺序是有意的：

    1. 先校验 query，再看候选是否为空——参数错误要被看见，
       不能因为「反正没有候选」就悄悄放过；
    2. 候选为空**在读配置之前**返回——没东西可排的时候，既不该因为
       「没配 Key」而报错，也不该为了一个空列表去建 HTTP 客户端和联网。

    降级只针对 `RerankerProviderError`：供应商故障退 RRF 顺序，
    配置错误和程序错误照常抛出。
    """
    normalized = normalize_query_text(query)

    if not candidates:
        return []

    settings = get_settings().require_rerank_settings()
    limit = settings.final_top_k if top_n is None else validate_top_n(top_n)

    if not settings.enabled:
        # 关掉精排就是「不排序」，返回 RRF 的顺序前 N 条，一次网络都不发
        return list(candidates[:limit])

    adapter = reranker if reranker is not None else build_reranker(settings)
    documents = [build_rerank_document(candidate) for candidate in candidates]

    try:
        items = await adapter.rerank(normalized, documents, top_n=limit)
    except RerankerProviderError as error:
        # 只记异常类名。异常正文可能带着响应回显、Key 和用户问题；
        # 候选正文也不进日志——它们都是数据，不是诊断信息。
        logger.warning("精排失败，退回 RRF 顺序：%s", type(error).__name__)
        return list(candidates[:limit])

    return apply_rerank_order(candidates, items, top_n=limit)
