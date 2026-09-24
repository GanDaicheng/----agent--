"""add public thread title to business analysis runs"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260924ba02"
down_revision: Union[str, Sequence[str], None] = "20260924ba01"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "business_analysis_runs",
        sa.Column(
            "title",
            sa.String(length=80),
            nullable=False,
            server_default="新的经营分析",
        ),
    )


def downgrade() -> None:
    op.drop_column("business_analysis_runs", "title")
