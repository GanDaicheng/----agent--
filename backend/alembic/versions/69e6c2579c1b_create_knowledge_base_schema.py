"""create knowledge base schema

Revision ID: 69e6c2579c1b
Revises: e205344666e8
Create Date: 2026-09-23 15:18:55.833222

RAG 知识库的两张表。本迁移只建结构，不写入任何知识文档数据。

两个刻意的选择：

1. **迁移自己保证 vector 扩展存在**（upgrade 开头的 CREATE EXTENSION IF NOT EXISTS）。
   不写成「假设谁已经手工执行过一条 SQL」——否则在一台干净机器上
   `alembic upgrade head` 会直接失败，而报错信息（"type vector does not exist"）
   离真正的原因很远。IF NOT EXISTS 保证它在已装过的库上重复执行也安全。

2. **vector 类型在本文件里重新声明了一份**，没有从 app.models.knowledge 导入。
   迁移一旦提交就应该冻结：它记录的是「当时发生了什么」，必须永远能重放。
   如果导入应用代码，将来有人改动了模型里的类型定义，这条老迁移的行为就跟着变了，
   在一台新机器上重放出来的结构会和当初不一样。为此多写 8 行是值得的。

本迁移**不创建 HNSW / IVFFlat 向量索引**：当前只有 44 个切片，
精确扫描（顺序扫描逐行算距离）又快又准，索引在这个量级上反而可能漏召回。
等切片规模上千再单独加一个迁移建索引，不影响现有数据。
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '69e6c2579c1b'
down_revision: Union[str, Sequence[str], None] = 'e205344666e8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# 与 app.models.knowledge.KNOWLEDGE_EMBEDDING_DIMENSIONS 和 .env 的
# EMBEDDING_DIMENSION 必须同为 1024。三处不一致时，插入会在维度校验上失败。
EMBEDDING_DIMENSIONS = 1024


class VectorType(sa.types.UserDefinedType):
    """只用于生成 DDL 的 pgvector 类型声明。

    建表只需要 get_col_spec 报出类型名；bind/result 处理器是读写数据时才需要的，
    而迁移不读写数据，所以这里不必重复实现。
    """

    cache_ok = True

    def __init__(self, dimensions: int) -> None:
        self.dimensions = dimensions

    def get_col_spec(self, **kw: object) -> str:
        return f"vector({self.dimensions})"


def upgrade() -> None:
    """Upgrade schema."""
    # 幂等：库上已经装过 vector 时这条语句什么也不做
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        'knowledge_documents',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('source_file', sa.String(length=255), nullable=False),
        sa.Column('document_title', sa.String(length=255), nullable=False),
        sa.Column('content_hash', sa.String(length=64), nullable=False),
        sa.Column('chunk_count', sa.Integer(), server_default=sa.text('0'), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.CheckConstraint('chunk_count >= 0', name=op.f('ck_knowledge_documents_chunk_count_not_negative')),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_knowledge_documents')),
        sa.UniqueConstraint('source_file', name=op.f('uq_knowledge_documents_source_file')),
        comment='知识库文档表：一行一份 Markdown 源文档，chunk_count 便于快速核对切片规模',
    )
    op.create_index(
        op.f('ix_knowledge_documents_content_hash'),
        'knowledge_documents',
        ['content_hash'],
        unique=False,
    )
    op.create_index(
        op.f('ix_knowledge_documents_document_title'),
        'knowledge_documents',
        ['document_title'],
        unique=False,
    )

    op.create_table(
        'knowledge_chunks',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('document_id', sa.BigInteger(), nullable=False),
        sa.Column('section_title', sa.String(length=255), nullable=False),
        sa.Column('chunk_index', sa.Integer(), nullable=False),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('content_for_embedding', sa.Text(), nullable=False),
        sa.Column('content_hash', sa.String(length=64), nullable=False),
        sa.Column('estimated_token_count', sa.Integer(), nullable=False),
        sa.Column('char_count', sa.Integer(), nullable=False),
        # 可空：支持「先落文本、后补向量」的两段式入库
        sa.Column('embedding', VectorType(EMBEDDING_DIMENSIONS), nullable=True),
        sa.Column('embedding_model', sa.String(length=64), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.CheckConstraint('char_count >= 0', name=op.f('ck_knowledge_chunks_char_count_not_negative')),
        sa.CheckConstraint('chunk_index >= 0', name=op.f('ck_knowledge_chunks_chunk_index_not_negative')),
        sa.CheckConstraint('estimated_token_count >= 0', name=op.f('ck_knowledge_chunks_estimated_token_count_not_negative')),
        # 删文档时连带删切片；用数据库级级联而不是 ORM 级联，删除不必先把子行读进内存
        sa.ForeignKeyConstraint(
            ['document_id'],
            ['knowledge_documents.id'],
            name=op.f('fk_knowledge_chunks_document_id'),
            ondelete='CASCADE',
        ),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_knowledge_chunks')),
        sa.UniqueConstraint('document_id', 'chunk_index', name=op.f('uq_knowledge_chunks_document_id_chunk_index')),
        comment='知识切片表：embedding 可空，支持先落文本后补向量',
    )
    op.create_index(
        op.f('ix_knowledge_chunks_content_hash'),
        'knowledge_chunks',
        ['content_hash'],
        unique=False,
    )
    op.create_index(
        op.f('ix_knowledge_chunks_document_id'),
        'knowledge_chunks',
        ['document_id'],
        unique=False,
    )
    op.create_index(
        op.f('ix_knowledge_chunks_section_title'),
        'knowledge_chunks',
        ['section_title'],
        unique=False,
    )


def downgrade() -> None:
    """Downgrade schema."""
    # 只删这两张知识库表，**不执行 DROP EXTENSION vector**。
    # 扩展是库级别的对象，将来别的表也会用它；在这里删掉，
    # 回滚一次知识库就会连带把别人的向量列一起废掉。
    # 删表顺序：先删有外键的子表，再删父表。
    op.drop_index(op.f('ix_knowledge_chunks_section_title'), table_name='knowledge_chunks')
    op.drop_index(op.f('ix_knowledge_chunks_document_id'), table_name='knowledge_chunks')
    op.drop_index(op.f('ix_knowledge_chunks_content_hash'), table_name='knowledge_chunks')
    op.drop_table('knowledge_chunks')
    op.drop_index(op.f('ix_knowledge_documents_document_title'), table_name='knowledge_documents')
    op.drop_index(op.f('ix_knowledge_documents_content_hash'), table_name='knowledge_documents')
    op.drop_table('knowledge_documents')
