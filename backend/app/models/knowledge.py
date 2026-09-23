"""知识库模型：RAG 用的文档表与切片表。

两张表的分工：
- `knowledge_documents`：一行 = 一份源 Markdown 文档，存文档级元信息；
- `knowledge_chunks`：一行 = 一个切片，存正文、送 embedding 的文本、向量。

**为什么要拆成两张表？** 重新入库时是按文档整体替换的：改了 `retail_metrics.md`
就该把这份文档的所有切片换掉，而不是逐条猜哪些切片变了。有了文档表，
这一步就是「按 document_id 删旧切片、插新切片」，边界清晰。
把文档信息平铺进切片表的话，同一份文档的标题、hash 会在几十行里重复，
改一次要更新几十行，还容易出现行与行之间不一致。

**embedding 为什么允许为空？** 分两段入库更实际：先把切片全部落库（文本入库不花钱、
不会失败），再单独跑一轮补向量。embedding 接口偶发超时、限流时，
已经落好的文本不用重来，续跑只补那些 embedding IS NULL 的行。
如果这一列是 NOT NULL，就必须「算完全部向量才能插第一行」，
中途失败就全丢，成本和风险都更高。

维度固定 1024，与 EMBEDDING_DIMENSION（text-embedding-v4 的 1024 档）以及
`vector(1024)` 三处必须一致。测试 test_model_dimension_matches_configured_embedding_dimension
会在 .env 被改歪时报错。
"""

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import UserDefinedType

from app.models.base import Base

# 向量维度。改这里必须同步改 .env 里的 EMBEDDING_DIMENSION，
# 并且要新写一个迁移把列类型从 vector(1024) 改成新维度（PG 不允许直接改长度）。
KNOWLEDGE_EMBEDDING_DIMENSIONS = 1024

# content_hash 是 sha256 的十六进制串，固定 64 个字符
CONTENT_HASH_LENGTH = 64


class Vector(UserDefinedType):
    """pgvector 的 vector 类型。

    **为什么不装 `pgvector` 这个 Python 包？** 项目当前没装它
    （`requirements.txt` 里连 openai 都还没显式声明，靠的是 langchain-openai 传递带入）。
    为了一个列类型再加一个依赖不划算，而且会重演「隐式依赖」那个坑。
    SQLAlchemy 自带的 `UserDefinedType` 只要能报出类型名就够建表和读写。

    bind / result 处理器不是顺手加的，下一步入库立刻要用：
    没有 bind_processor，插一个 Python list 会被 asyncpg 拒绝（它不认识这个类型）；
    没有 result_processor，读出来的是 `'[0.1,0.2]'` 这样的字符串而不是 list[float]。
    pgvector 的文本格式就是 `[v1,v2,...]`，这里按它的格式互相转换。
    """

    cache_ok = True

    def __init__(self, dimensions: int) -> None:
        self.dimensions = dimensions

    def get_col_spec(self, **kw: object) -> str:
        return f"vector({self.dimensions})"

    def bind_processor(self, dialect):  # noqa: ANN001, ANN201 - SQLAlchemy 约定的签名
        def process(value):  # noqa: ANN001, ANN202
            if value is None:
                return None
            if isinstance(value, str):
                # 已经是 pgvector 文本格式（例如直接执行 SQL 时），原样放行
                return value
            return "[" + ",".join(str(float(item)) for item in value) + "]"

        return process

    def result_processor(self, dialect, coltype):  # noqa: ANN001, ANN201
        def process(value):  # noqa: ANN001, ANN202
            if value is None or not isinstance(value, str):
                return value
            body = value.strip().strip("[]")
            if not body:
                return []
            return [float(item) for item in body.split(",")]

        return process


class KnowledgeDocument(Base):
    """知识库文档表：一行一份源 Markdown 文档。"""

    __tablename__ = "knowledge_documents"
    __table_args__ = (
        CheckConstraint("chunk_count >= 0", name="chunk_count_not_negative"),
        {"comment": "知识库文档表：一行一份 Markdown 源文档，chunk_count 便于快速核对切片规模"},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    source_file: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    document_title: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    # 整篇文档的 hash，用来判断「这份文档改过没有」——没改就整篇跳过，连切片都不用重算
    content_hash: Mapped[str] = mapped_column(
        String(CONTENT_HASH_LENGTH), nullable=False, index=True
    )
    chunk_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    # 删文档时连带删掉它的切片。passive_deletes=True 让删除交给数据库的
    # ON DELETE CASCADE 完成，不必先把成百上千个子行加载进内存再逐个删。
    chunks: Mapped[list["KnowledgeChunk"]] = relationship(
        back_populates="document",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class KnowledgeChunk(Base):
    """知识切片表：一行一个 chunk。

    字段与 app/services/knowledge_chunking.py 的 KnowledgeChunk 数据类一一对应，
    入库时几乎是直接搬运——切片模块先行的价值就在这里。
    """

    __tablename__ = "knowledge_chunks"
    __table_args__ = (
        CheckConstraint("chunk_index >= 0", name="chunk_index_not_negative"),
        CheckConstraint("estimated_token_count >= 0", name="estimated_token_count_not_negative"),
        CheckConstraint("char_count >= 0", name="char_count_not_negative"),
        # 同一份文档内切片序号唯一，重复入库时靠它做冲突检测。
        # 写成表级组合约束而不是给单个字段加 unique：单加在 document_id 上会限制
        # 「一份文档只能有一个切片」，单加在 chunk_index 上会限制「全库只有一个 0 号切片」，
        # 两个都是错的。
        # 这里**不显式传 name**：base.NAMING_CONVENTION 里 uq 的模板用的是
        # %(column_0_N_name)s，传了 name 反而会绕过约定、让约束名跟其它表不成套。
        UniqueConstraint("document_id", "chunk_index"),
        # content_hash 刻意不做全局唯一：不同文档完全可能有一模一样的说明片段，
        # 全局唯一会让后入库的那条直接失败。去重策略留给后续，不在这里做强约束。
        {"comment": "知识切片表：embedding 可空，支持先落文本后补向量"},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    document_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("knowledge_documents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    section_title: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)

    # 给人看的正文，不含标题（标题单独存字段）
    content: Mapped[str] = mapped_column(Text, nullable=False)
    # 送去算向量的文本：标题上下文 + 正文。单独存一份是有意的——
    # 排查「为什么这条召回不准」时，要能直接看到当时到底拿什么文本算的向量。
    content_for_embedding: Mapped[str] = mapped_column(Text, nullable=False)
    # 对 content_for_embedding 取的 hash（理由见 knowledge_chunking.chunk_hash）
    content_hash: Mapped[str] = mapped_column(
        String(CONTENT_HASH_LENGTH), nullable=False, index=True
    )

    estimated_token_count: Mapped[int] = mapped_column(Integer, nullable=False)
    char_count: Mapped[int] = mapped_column(Integer, nullable=False)

    # 可空：支持「先落文本、后补向量」的两段式入库
    embedding: Mapped[list[float] | None] = mapped_column(
        Vector(KNOWLEDGE_EMBEDDING_DIMENSIONS), nullable=True
    )
    # 记录这条向量是哪个模型算的。将来换 embedding 模型时，
    # 靠它能精确找出「需要重算」的行，而不是全表重嵌。
    embedding_model: Mapped[str | None] = mapped_column(String(64), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    document: Mapped[KnowledgeDocument] = relationship(back_populates="chunks")
