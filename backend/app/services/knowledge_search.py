"""知识检索：问题 → 查询向量 → pgvector 余弦距离 top-k。

## 距离算子

用 pgvector 的 `<=>` —— **余弦距离**。取它的理由：文本 embedding 关心的是方向
（语义相近），不是长度（文本长短）。欧氏距离 `<->` 会被向量模长影响，
同一句话写长一点、短一点就可能拉开距离，对语义检索是干扰。
内积 `<#>` 在向量已归一化时和余弦等价，但这里不假设模型做了归一化。

余弦距离 `distance = 1 - cos(θ)`，取值范围 `[0, 2]`：
0 表示方向完全相同，1 表示正交（无关），2 表示方向完全相反。
**distance 越小越相似**，所以 `ORDER BY embedding <=> :qv` 是升序。

## similarity 的含义

`similarity = 1 - distance`，把距离换算回余弦相似度，取值范围 `[-1, 1]`。
这个换算是**算术上精确的**（对 `<=>` 而言），但别把它当绝对质量分：
它衡量的是「两个向量在这个 embedding 模型眼里的接近程度」，
不等于「这段文字真的回答了这个问题」。排序可信，阈值不可全信——
所以它主要用来横向比较同一批结果的相对好坏，以及人工排查召回质量。

## 为什么用 text() + 显式 CAST，而不是拼接字符串

查询向量是一串浮点数，来自 embedding 接口。它作为**绑定参数**传入，
再加 `CAST(:query_embedding AS vector)` 把类型说清楚，
避免 PostgreSQL 去猜 `unknown` 参数该当什么类型。

**用户的问题文本从头到尾没有进入 SQL**——它只被送去算向量，
SQL 里出现的是向量和 top_k 两个绑定参数。所以这里不存在 SQL 注入面。

## 为什么不建向量索引

44 条切片用顺序扫描（精确最近邻）又快又准。HNSW 是近似算法，
在这个量级上不但省不了多少时间，还可能漏掉真正的最近邻。
等切片上千再补一个迁移建索引，检索代码不用改。

## 本模块在召回链路里的位置

这里是**向量召回**那一路，同时也是召回链路的公共底座：

- `ChunkContent`：两路召回命中的「同一段切片」，只描述内容、不带分数；
- `connection_scope`：两个召回器共用的借连接规则（测试注入才只对一路生效）；
- `KnowledgeSearchError`：整条链路共用的受控异常。

关键词召回（knowledge_keyword_search）与候选融合（retrieval_fusion）建在这之上。
本模块不调用 LLM、不生成回答、不写任何数据、不做候选融合。
"""

from collections.abc import Awaitable, Callable, Mapping, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.config import EmbeddingSettings
from app.core.exceptions import AppError
from app.repositories.database import get_connection
from app.services.embedding import embed_text

# top_k 的合法区间。上限设 10 是因为：知识库只有 44 条切片，
# 一次拿十几二十条除了把上下文塞满、把注意力稀释掉之外没有好处。
DEFAULT_TOP_K = 5
MIN_TOP_K = 1
MAX_TOP_K = 10

# 查询向量必须是这个长度，与 vector(1024) 列一致
EXPECTED_DIMENSION = 1024

# 检索用 SQL。参数只有两个：向量与 top_k，都是绑定参数。
SEARCH_SQL = text(
    """
    SELECT
        kc.id                      AS chunk_id,
        kd.id                      AS document_id,
        kd.source_file             AS source_file,
        kd.document_title          AS document_title,
        kc.section_title           AS section_title,
        kc.chunk_index             AS chunk_index,
        kc.content                 AS content,
        kc.embedding_model         AS embedding_model,
        kc.embedding <=> CAST(:query_embedding AS vector) AS distance
    FROM knowledge_chunks kc
    JOIN knowledge_documents kd ON kd.id = kc.document_id
    WHERE kc.embedding IS NOT NULL
    ORDER BY kc.embedding <=> CAST(:query_embedding AS vector)
    LIMIT :top_k
    """
)

# 查询向量生成器的签名：问题文本 → (向量, 配置)
QueryEmbedder = Callable[[str], Awaitable[tuple[list[float], EmbeddingSettings]]]


class KnowledgeSearchError(AppError):
    """检索相关的可预期错误（参数非法、知识库为空等）。"""


@dataclass(frozen=True)
class ChunkContent:
    """一份切片的**内容部分**，不含任何"分数"。

    这是召回链路上的公共货币：向量召回和关键词召回命中的是同一种东西
    （一段切片），只是各自附带不同的分数。把公共字段抽出来单独定义，
    有三个具体的好处：

    1. 融合层只需要认一种类型，不必为两路各写一套取属性的代码；
    2. 「同一个 chunk_id 只能出现一次」这条规则在类型上就说得通——
       两路命中的确实是同一个对象；
    3. 分数各归各的：向量距离留在 KnowledgeSearchResult 上，
       关键词分数留在 KeywordSearchResult 上，谁都不会被伪造。

    为什么不直接复用 KnowledgeSearchResult？因为它的 distance / similarity
    是**向量召回专有**的量。关键词命中根本没有向量距离，硬塞 0 或 1 进去，
    下游任何一处拿它做判断都会得到一个看起来合法、实际毫无意义的数。
    """

    chunk_id: int
    document_id: int
    source_file: str
    document_title: str
    section_title: str
    chunk_index: int
    content: str
    embedding_model: str | None


@dataclass(frozen=True)
class KnowledgeSearchResult:
    """一条**向量**检索结果。

    content 是给人看、要交给 LLM 的正文；content_for_embedding **不返回**——
    那是算向量用的文本（带标题前缀的副本），对生成回答没有额外价值，
    带上只会让上下文里出现两份近似内容。

    distance / similarity 是向量召回专有的量，没有默认值：
    这个类型只该由向量召回产出。关键词召回有自己的结果类型。
    """

    chunk_id: int
    document_id: int
    source_file: str
    document_title: str
    section_title: str
    chunk_index: int
    content: str
    embedding_model: str | None
    distance: float
    similarity: float

    @property
    def chunk(self) -> ChunkContent:
        """这份切片的内容部分，供融合层统一取用。

        做成属性而不是改字段：KnowledgeSearchResult 已经被 RAG 回答服务
        和大量测试按现有关键字参数构造，改构造签名等于把那些调用点全打翻。
        加一个只读属性既能给融合层一个统一入口，又不动任何既有行为。
        """
        return ChunkContent(
            chunk_id=self.chunk_id,
            document_id=self.document_id,
            source_file=self.source_file,
            document_title=self.document_title,
            section_title=self.section_title,
            chunk_index=self.chunk_index,
            content=self.content,
            embedding_model=self.embedding_model,
        )


# --------------------------------------------------------------------------
# 纯函数
# --------------------------------------------------------------------------


def normalize_query(query: str) -> str:
    """去掉首尾空白并校验非空。

    空白问题在这里拦住而不是发给 embedding 接口：空文本换回来的向量没有意义，
    发出去纯粹是白花一次调用。
    """
    if query is None:
        raise KnowledgeSearchError("检索问题不能为空。")

    normalized = query.strip()
    if not normalized:
        raise KnowledgeSearchError("检索问题不能是空白字符，请提供具体问题。")
    return normalized


def validate_top_k(top_k: int) -> int:
    """校验 top_k 落在合法区间。

    这里**直接报错而不是静默截断**：如果调用方要 50 条、实际只给 10 条，
    它拿到结果时完全不知道发生了什么，会以为「相关知识就只有这 10 条」。
    这是那种很难排查的安静错误——宁可当场失败，并把合法区间写在错误信息里。
    """
    if isinstance(top_k, bool) or not isinstance(top_k, int):
        raise KnowledgeSearchError(f"top_k 必须是整数，当前是 {type(top_k).__name__}。")

    if not MIN_TOP_K <= top_k <= MAX_TOP_K:
        raise KnowledgeSearchError(
            f"top_k 必须在 {MIN_TOP_K} 到 {MAX_TOP_K} 之间，当前是 {top_k}。"
        )
    return top_k


def to_pgvector_literal(vector: Sequence[float]) -> str:
    """把向量转成 pgvector 认的文本格式 `[v1,v2,...]`。

    只接受能转成 float 的元素：传进来一个字符串或 None 时会当场报错，
    而不是拼出一段让数据库去猜的畸形字面量。

    调用方拿到的是**绑定参数的值**，不是拼进 SQL 的片段——见模块说明。
    """
    if not vector:
        raise KnowledgeSearchError("查询向量为空，无法检索。")

    try:
        numbers = [float(value) for value in vector]
    except (TypeError, ValueError) as error:
        raise KnowledgeSearchError("查询向量里含有无法转成数值的元素。") from error

    if len(numbers) != EXPECTED_DIMENSION:
        raise KnowledgeSearchError(
            f"查询向量维度不符：期望 {EXPECTED_DIMENSION}，实际 {len(numbers)}。"
        )

    return "[" + ",".join(str(number) for number in numbers) + "]"


def similarity_from_distance(distance: float) -> float:
    """余弦距离 → 余弦相似度。对 `<=>` 而言这是精确换算，不是近似。"""
    return 1.0 - distance


def build_chunk_content(row: Mapping[str, Any]) -> ChunkContent:
    """把一行查询结果映射成切片内容。

    向量召回和关键词召回的 SQL 选的是同一批列，所以共用这一个映射函数：
    两处各写一份，迟早会在某次加字段时漏掉一边，而漏掉的那一边
    只会表现为「某个字段莫名其妙是空的」。
    """
    return ChunkContent(
        chunk_id=int(row["chunk_id"]),
        document_id=int(row["document_id"]),
        source_file=str(row["source_file"]),
        document_title=str(row["document_title"]),
        section_title=str(row["section_title"]),
        chunk_index=int(row["chunk_index"]),
        content=str(row["content"]),
        embedding_model=row["embedding_model"],
    )


def build_search_result(row: Mapping[str, Any]) -> KnowledgeSearchResult:
    """把一行查询结果映射成**向量**检索结果。"""
    distance = float(row["distance"])
    content = build_chunk_content(row)
    return KnowledgeSearchResult(
        chunk_id=content.chunk_id,
        document_id=content.document_id,
        source_file=content.source_file,
        document_title=content.document_title,
        section_title=content.section_title,
        chunk_index=content.chunk_index,
        content=content.content,
        embedding_model=content.embedding_model,
        distance=distance,
        similarity=similarity_from_distance(distance),
    )


# --------------------------------------------------------------------------
# 检索
# --------------------------------------------------------------------------


@asynccontextmanager
async def connection_scope(connection: AsyncConnection | None):
    """有外部连接就用外部的（测试注入用），没有再自己借一条。

    公开出去给关键词召回共用：两个召回器必须用同一个「借连接」规则，
    否则测试注入 connection 时只对其中一路生效，另一路会偷偷去连真库。
    """
    if connection is not None:
        yield connection
        return
    async with get_connection() as borrowed:
        yield borrowed


async def search_knowledge(
    query: str,
    *,
    top_k: int = DEFAULT_TOP_K,
    embedder: QueryEmbedder = embed_text,
    connection: AsyncConnection | None = None,
) -> list[KnowledgeSearchResult]:
    """按语义相似度检索知识切片，返回按 distance 升序的 top_k 条。

    embedder 与 connection 都可注入，测试因此不必调真实 embedding 接口、
    也不必连数据库。

    这是**向量召回**那一路，行为保持不变：候选融合（关键词召回、RRF）
    由 knowledge_keyword_search / retrieval_fusion 负责，不在这里做。
    """
    normalized = normalize_query(query)
    limit = validate_top_k(top_k)

    vector, _ = await embedder(normalized)
    literal = to_pgvector_literal(vector)

    async with connection_scope(connection) as active:
        rows = (
            await active.execute(
                SEARCH_SQL,
                {"query_embedding": literal, "top_k": limit},
            )
        ).mappings().all()

    return [build_search_result(row) for row in rows]


async def count_searchable_chunks(*, connection: AsyncConnection | None = None) -> int:
    """统计可检索的切片数（embedding 非空的那些）。

    smoke 脚本用它区分「检索没召回」和「知识库压根是空的」——
    这两种情况的处理方式完全不同，混成一个「没有结果」很难排查。
    """
    async with connection_scope(connection) as active:
        count = await active.scalar(
            text("SELECT COUNT(*) FROM knowledge_chunks WHERE embedding IS NOT NULL")
        )
    return int(count or 0)
