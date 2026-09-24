"""关键词召回：检索词 → 标题 / 关键词 / 同义词 / 检索文本的字面命中。

## 为什么不能只靠向量

向量检索擅长「意思相近」，但有两类查询它天生吃亏：

- **精确的名字**：字段名、表名、产品名、编号。这类词改动一个字符就是另一个东西，
  而 embedding 会把它们映射到几乎同一个位置；
- **中文短词**：两个字的关键词凑不满一个三元组，pg_trgm 的 trigram 在这种长度上
  几乎失效。所以本模块的**主体是精确匹配和 ILIKE 包含匹配**，
  trigram 只作为最后一层模糊补充。

## 搜的是哪五处

| 字段 | 为什么 |
| --- | --- |
| `knowledge_documents.document_title` | 整篇文档的主题 |
| `knowledge_chunks.section_title` | 这一段的主题，最具体 |
| `knowledge_chunks.keywords` | 入库时模型提的核心概念（JSONB 数组） |
| `knowledge_chunks.aliases` | 同一概念的其他叫法（JSONB 数组） |
| `knowledge_chunks.search_text` | 标题 + 小节 + 关键词 + 同义词 + 正文的合集 |

## 评分：取「命中的最强那一层」

分三层，权重严格递减（见 MATCH_RULES）：标题/术语的**完全匹配** > 标题/正文的
**包含匹配** > **trigram 模糊**。分数是这些层的 **GREATEST**，不是求和——
求和会让「正文包含 + 模糊」压过「标题包含」，与分层的本意正好相反。
命中了哪些层另外用 matched_terms 如实记录，信息不会因为取最大值而丢失。

分数**只在关键词这一路内部排序**。它和余弦相似度量纲完全不同，
两者绝不能直接相加——跨召回器的融合交给 RRF（retrieval_fusion.py）。

## 权重住在 Python，SQL 只负责用

所有权重、相似度阈值都作为**绑定参数**传给 SQL（`:w_*`、`:trigram_min_similarity`）。
写在 SQL 字面量里的话，两处数值迟早漂开，而漂开之后「哪条规则更强」
就只能靠读 SQL 才知道。

## 注入面

检索词只作为**参数值**出现，永远不进 SQL 文本。LIKE 的通配符
（`%`、`_`、反斜杠）在 Python 侧转义成字面量后再作为参数传下去，
并且 SQL 里显式写了 `ESCAPE '\\'`。所以用户输入一个 `%` 只会去找
「真的含一个百分号」的切片，不会变成「匹配全库」。

本模块只读、不调模型、不调 embedding、不写任何数据。
"""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.services.knowledge_search import (
    ChunkContent,
    KnowledgeSearchError,
    build_chunk_content,
    connection_scope,
)

# 单个检索词最多取多少条。关键词召回是「多路」中的一路，
# 每路多取一些才有融合的价值；但也不必超过候选上限太多。
DEFAULT_KEYWORD_LIMIT = 10
MIN_KEYWORD_LIMIT = 1
MAX_KEYWORD_LIMIT = 20

# LIKE 的转义字符。SQL 里用 ESCAPE '\' 显式声明，不依赖数据库的默认值。
LIKE_ESCAPE = "\\"

# trigram 相似度阈值。低于它的模糊命中直接不算命中——
# 否则每个检索词都会把全库都当成「有点像」，关键词这一路就退化成噪声了。
# 取值和 pg_trgm 自己的默认阈值一致。
TRIGRAM_MIN_SIMILARITY = 0.3

# --- 分层权重 -------------------------------------------------------------
# 顺序即优先级。数值本身不重要，重要的是**严格递减**，
# 而且最后一位（trigram）乘上相似度上限之后仍然低于「正文包含」那一层。
WEIGHT_SECTION_TITLE_EXACT = 100
WEIGHT_DOCUMENT_TITLE_EXACT = 90
WEIGHT_KEYWORDS_EXACT = 80
WEIGHT_ALIASES_EXACT = 70
WEIGHT_SECTION_TITLE_CONTAINS = 60
WEIGHT_DOCUMENT_TITLE_CONTAINS = 50
WEIGHT_SEARCH_TEXT_CONTAINS = 40
WEIGHT_SEARCH_TEXT_TRIGRAM = 30

# 命中规则：(列别名, 权重)，顺序即优先级顺序，也是 matched_terms 的顺序。
# 定义成不可变元组而不是字典，是为了让「顺序有意义」这件事写在类型上，
# 也防止有人在别处顺手往字典里塞一条。
MATCH_RULES: tuple[tuple[str, int], ...] = (
    ("section_title_exact", WEIGHT_SECTION_TITLE_EXACT),
    ("document_title_exact", WEIGHT_DOCUMENT_TITLE_EXACT),
    ("keywords_exact", WEIGHT_KEYWORDS_EXACT),
    ("aliases_exact", WEIGHT_ALIASES_EXACT),
    ("section_title_contains", WEIGHT_SECTION_TITLE_CONTAINS),
    ("document_title_contains", WEIGHT_DOCUMENT_TITLE_CONTAINS),
    ("search_text_contains", WEIGHT_SEARCH_TEXT_CONTAINS),
    ("search_text_trigram", WEIGHT_SEARCH_TEXT_TRIGRAM),
)

MATCH_RULE_ORDER: tuple[str, ...] = tuple(label for label, _ in MATCH_RULES)
MATCH_RULE_WEIGHTS: dict[str, int] = dict(MATCH_RULES)

# 命中的完整判定，写成一个 CTE 里的布尔列；分数从这些列算出来。
# 用 CTE 而不是把条件在 WHERE 和 SELECT 里各写一遍：两处重复写入迟早会漂开，
# 而漂开的后果是「排序用了一套规则、过滤用了另一套」，很难看出来。
# PostgreSQL 12+ 会把这个 CTE 内联，条件可以下推到基表扫描，不会真的物化全表。
KEYWORD_SEARCH_SQL = text(
    r"""
    WITH signal AS (
        SELECT
            kc.id              AS chunk_id,
            kc.document_id     AS document_id,
            kd.source_file     AS source_file,
            kd.document_title  AS document_title,
            kc.section_title   AS section_title,
            kc.chunk_index     AS chunk_index,
            kc.content         AS content,
            kc.embedding_model AS embedding_model,

            (kc.section_title = :term)  AS section_title_exact,
            (kd.document_title = :term) AS document_title_exact,

            EXISTS (
                SELECT 1
                FROM jsonb_array_elements_text(kc.keywords) AS element(term_value)
                WHERE lower(term_value) = lower(:term)
            ) AS keywords_exact,

            EXISTS (
                SELECT 1
                FROM jsonb_array_elements_text(kc.aliases) AS element(term_value)
                WHERE lower(term_value) = lower(:term)
            ) AS aliases_exact,

            (kc.section_title ILIKE :contains ESCAPE '\')  AS section_title_contains,
            (kd.document_title ILIKE :contains ESCAPE '\') AS document_title_contains,
            (kc.search_text ILIKE :contains ESCAPE '\')    AS search_text_contains,

            similarity(lower(kc.search_text), lower(:term)) AS trigram_similarity
        FROM knowledge_chunks kc
        JOIN knowledge_documents kd ON kd.id = kc.document_id
    ),
    matched AS (
        SELECT
            *,
            (trigram_similarity >= :trigram_min_similarity) AS search_text_trigram
        FROM signal
        WHERE section_title_exact
           OR document_title_exact
           OR keywords_exact
           OR aliases_exact
           OR section_title_contains
           OR document_title_contains
           OR search_text_contains
           OR trigram_similarity >= :trigram_min_similarity
    )
    SELECT
        chunk_id,
        document_id,
        source_file,
        document_title,
        section_title,
        chunk_index,
        content,
        embedding_model,
        section_title_exact,
        document_title_exact,
        keywords_exact,
        aliases_exact,
        section_title_contains,
        document_title_contains,
        search_text_contains,
        search_text_trigram,
        GREATEST(
            CASE WHEN section_title_exact THEN :w_section_title_exact ELSE 0 END,
            CASE WHEN document_title_exact THEN :w_document_title_exact ELSE 0 END,
            CASE WHEN keywords_exact THEN :w_keywords_exact ELSE 0 END,
            CASE WHEN aliases_exact THEN :w_aliases_exact ELSE 0 END,
            CASE WHEN section_title_contains THEN :w_section_title_contains ELSE 0 END,
            CASE WHEN document_title_contains THEN :w_document_title_contains ELSE 0 END,
            CASE WHEN search_text_contains THEN :w_search_text_contains ELSE 0 END,
            CASE WHEN search_text_trigram
                 THEN :w_search_text_trigram * trigram_similarity
                 ELSE 0 END
        ) AS keyword_score
    FROM matched
    ORDER BY keyword_score DESC, chunk_id ASC
    LIMIT :limit
    """
)


@dataclass(frozen=True)
class KeywordSearchResult:
    """一条**关键词**检索结果。

    和 KnowledgeSearchResult 是两种东西，所以是两个类型：

    - 向量结果带的是 distance / similarity（向量召回专有的量）；
    - 关键词结果带的是 keyword_score / matched_terms（字面命中算出来的量）。

    如果为了「统一」把它们塞进同一个类型，就一定有人要给关键词结果编一个
    distance，或者给向量结果编一个 keyword_score。那种编出来的数字
    看起来完全合法，下游用它做判断时不会报错，只会得出错的结论。
    所以这里宁可多一个类型：**没有的量就是没有**。

    两边共同的部分（这一段切片是什么）住在 ChunkContent 里，
    融合层只认它，所以多一个类型并不会让融合代码变复杂。
    """

    chunk: ChunkContent
    keyword_score: float
    matched_terms: tuple[str, ...]


# --------------------------------------------------------------------------
# 纯函数
# --------------------------------------------------------------------------


def normalize_term(term: str) -> str:
    """去掉首尾空白并校验非空。

    空检索词在这里拦住：发出去只会白跑一次 SQL，还会把全库都匹配成
    「包含空串」——那是最坏的一种「有结果」。
    """
    if term is None:
        raise KnowledgeSearchError("关键词不能为空。")

    normalized = term.strip()
    if not normalized:
        raise KnowledgeSearchError("关键词不能是空白字符，请提供具体的检索词。")
    return normalized


def validate_keyword_limit(limit: int) -> int:
    """校验单个检索词的取数上限。

    和 top_k 一样**直接报错而不是静默截断**：要 100 条却只给 20 条，
    调用方会以为「相关的就这么多」。
    """
    if isinstance(limit, bool) or not isinstance(limit, int):
        raise KnowledgeSearchError(f"limit 必须是整数，当前是 {type(limit).__name__}。")

    if not MIN_KEYWORD_LIMIT <= limit <= MAX_KEYWORD_LIMIT:
        raise KnowledgeSearchError(
            f"limit 必须在 {MIN_KEYWORD_LIMIT} 到 {MAX_KEYWORD_LIMIT} 之间，当前是 {limit}。"
        )
    return limit


def escape_like_pattern(value: str) -> str:
    """把 LIKE 的通配符转义成字面量（不加两端的 %）。

    转义字符自己必须**最先**转义：先转 % 再转反斜杠的话，刚给 % 加上的那个
    反斜杠会被再转一遍，模式里就成了「一个反斜杠 + 一个通配符」，
    又变回通配符了。

    返回的是**参数值**，不是拼进 SQL 的片段——见模块说明。
    """
    return (
        value.replace(LIKE_ESCAPE, LIKE_ESCAPE * 2)
        .replace("%", LIKE_ESCAPE + "%")
        .replace("_", LIKE_ESCAPE + "_")
    )


def build_keyword_parameters(term: str, *, limit: int) -> dict[str, object]:
    """组装这条 SQL 的全部绑定参数。

    每一个都是参数值：检索词、转义后的 LIKE 模式、阈值、上限、以及各层权重。
    SQL 文本里只有占位符，没有任何一处来自用户。
    """
    parameters: dict[str, object] = {
        "term": term,
        "contains": f"%{escape_like_pattern(term)}%",
        "trigram_min_similarity": TRIGRAM_MIN_SIMILARITY,
        "limit": limit,
    }
    for label, weight in MATCH_RULES:
        parameters[f"w_{label}"] = weight
    return parameters


def select_matched_rules(signals: Mapping[str, object]) -> tuple[str, ...]:
    """从一行结果里挑出命中的规则标签，按优先级顺序返回。

    顺序由 MATCH_RULE_ORDER 决定，不随 SQL 返回列的顺序变化；
    每个标签最多出现一次，所以天然是去重的。
    """
    return tuple(label for label in MATCH_RULE_ORDER if signals.get(label))


def build_keyword_result(row: Mapping[str, Any]) -> KeywordSearchResult:
    """把一行查询结果映射成关键词检索结果。"""
    return KeywordSearchResult(
        chunk=build_chunk_content(row),
        keyword_score=float(row["keyword_score"]),
        matched_terms=select_matched_rules(row),
    )


# --------------------------------------------------------------------------
# 召回
# --------------------------------------------------------------------------


async def search_knowledge_keywords(
    term: str,
    *,
    limit: int = DEFAULT_KEYWORD_LIMIT,
    connection: AsyncConnection | None = None,
) -> list[KeywordSearchResult]:
    """按字面命中召回切片，返回按 keyword_score 降序（同分按 chunk_id 升序）的结果。

    connection 可注入，测试因此不必连数据库。排序由 SQL 完成，Python 侧不重排。
    """
    normalized = normalize_term(term)
    capped = validate_keyword_limit(limit)
    parameters = build_keyword_parameters(normalized, limit=capped)

    async with connection_scope(connection) as active:
        rows = (
            await active.execute(KEYWORD_SEARCH_SQL, parameters)
        ).mappings().all()

    return [build_keyword_result(row) for row in rows]
