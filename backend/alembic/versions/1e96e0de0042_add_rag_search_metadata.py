"""add rag search metadata

Revision ID: 1e96e0de0042
Revises: 69e6c2579c1b
Create Date: 2026-09-24 13:19:53.618480

给 knowledge_chunks 加检索元数据：keywords / aliases / search_text，
启用 pg_trgm，并为 search_text 建 GIN trigram 索引。

**本迁移只改结构，不生成任何元数据。** keywords 和 aliases 保持空数组，
search_text 用「文档标题 + 小节标题 + 正文」把已有切片回填出来。
关键词与同义词的提取是下一阶段的事，本迁移不调用任何外部接口。

三个刻意的选择：

1. **三个新列都带 server default**（`[]` / `[]` / `''`）。
   表里已有数据，加 NOT NULL 列时不给默认值就会直接失败。
   更实际的原因在下一阶段之前：入库代码还不会主动写这三列，
   新切片只能靠数据库默认值兜住。所以这个默认值**不能**在迁完之后删掉——
   删了，现有入库路径立刻会撞上 NOT NULL 违例。

2. **回填 search_text 用 concat_ws，不用 `||`。**
   `||` 的语义是「有一个 NULL 结果就是 NULL」：小节标题一旦为空，
   整条 search_text 就变成 NULL，而这一列是 NOT NULL，回填会当场失败。
   concat_ws 会跳过 NULL 参数，只把非空片段用换行连起来。

3. **downgrade 不删 pg_trgm。**
   扩展是库级别的共享对象，将来别的表或别的迁移也会用它。
   回滚一个功能不等于要废掉一个公共扩展——和上一个迁移不删 vector 是同一条理由。

本迁移**不碰** content、content_for_embedding、content_hash、embedding、
embedding_model 和向量维度，也不碰任何零售业务表。回填是纯 SQL，
不经过 ORM，因此不会触发 updated_at 的 onupdate。
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '1e96e0de0042'
down_revision: Union[str, Sequence[str], None] = '69e6c2579c1b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# 索引名与 app/models/knowledge.SEARCH_TEXT_TRGM_INDEX 必须一致。
# 这里不导入那个常量：迁移一旦提交就该冻结，导入应用代码会让它的行为
# 跟着应用一起变（同 69e6c2579c1b 里重新声明 vector 类型的理由）。
# 两处不一致时，以后 autogenerate 会认为索引丢了，再生成一条重复建索引的迁移。
SEARCH_TEXT_TRGM_INDEX = "ix_knowledge_chunks_search_text_trgm"

# JSONB 空数组的数据库默认值。**必须带 ::jsonb 转换**：
# 不加的话 DEFAULT '[]' 只是个字符串字面量，一旦有人照着写成 '"[]"'，
# 库里存的就成了 JSON 字符串而不是数组，后续 jsonb_typeof(...) = 'array'
# 的检查会静默漏掉这些行。
EMPTY_JSONB_ARRAY = "'[]'::jsonb"

# 回填 SQL。三处细节都是有意的：
# 1. 用 raw 字符串（r 前缀）保住反斜杠，让 SQL 看到的是 E'\n' 而不是
#    Python 先解出来的真换行——两层转义叠在一起是最容易写错的地方；
# 2. concat_ws 而不是 ||，理由见文件说明；
# 3. WHERE 只命中 search_text 仍为空串的行，所以重复执行安全，
#    也**只**改 search_text，其它列一律不动。
SEARCH_TEXT_BACKFILL = r"""
UPDATE knowledge_chunks AS kc
SET search_text = concat_ws(
    E'\n',
    kd.document_title,
    kc.section_title,
    kc.content
)
FROM knowledge_documents AS kd
WHERE kd.id = kc.document_id
  AND kc.search_text = ''
"""


def upgrade() -> None:
    """Upgrade schema."""
    # 1. pg_trgm。search_text 的 trigram 索引依赖它，扩展必须先存在。
    #    幂等写法：库上装过就什么也不做。
    #    **不动 vector 扩展**——那是上一段功能的对象，本迁移与它无关。
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")

    # 2~4. 三个新列。都带 server_default，所以对已有行也能直接加 NOT NULL 列。
    # 默认值不在迁移末尾删除：入库代码接入之前，新切片全靠它兜底。
    op.add_column(
        'knowledge_chunks',
        sa.Column(
            'keywords',
            postgresql.JSONB(),
            server_default=sa.text(EMPTY_JSONB_ARRAY),
            nullable=False,
        ),
    )
    op.add_column(
        'knowledge_chunks',
        sa.Column(
            'aliases',
            postgresql.JSONB(),
            server_default=sa.text(EMPTY_JSONB_ARRAY),
            nullable=False,
        ),
    )
    op.add_column(
        'knowledge_chunks',
        sa.Column(
            'search_text',
            sa.Text(),
            server_default=sa.text("''"),
            nullable=False,
        ),
    )

    # 5. 回填已有切片。新列此刻全是空串，所以这条语句会覆盖全部存量行；
    #    只改 search_text，见 SEARCH_TEXT_BACKFILL 的说明。
    op.execute(SEARCH_TEXT_BACKFILL)

    # 6. GIN trigram 索引。**放在回填之后**：先建索引再灌数据的话，
    #    每一行都要额外维护一次索引，存量回填会明显变慢。
    op.create_index(
        SEARCH_TEXT_TRGM_INDEX,
        'knowledge_chunks',
        ['search_text'],
        unique=False,
        postgresql_using='gin',
        postgresql_ops={'search_text': 'gin_trgm_ops'},
    )


def downgrade() -> None:
    """Downgrade schema."""
    # 顺序与 upgrade 严格相反：先删索引，再删列。
    # 反过来的话，drop_column 会把索引一起带走，后面那条 drop_index
    # 就会因为「索引不存在」而报错。
    op.drop_index(SEARCH_TEXT_TRGM_INDEX, table_name='knowledge_chunks')
    op.drop_column('knowledge_chunks', 'search_text')
    op.drop_column('knowledge_chunks', 'aliases')
    op.drop_column('knowledge_chunks', 'keywords')
    # **不执行 DROP EXTENSION pg_trgm**：理由是扩展属于整个库、可能被别人共享，
    # 见文件说明。回滚本功能只该删掉本功能自己建的东西。
