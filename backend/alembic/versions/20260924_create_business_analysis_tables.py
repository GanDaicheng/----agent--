"""create business analysis persistence tables"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260924ba01"
down_revision: Union[str, Sequence[str], None] = "1e96e0de0042"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "business_analysis_runs",
        sa.Column("id", sa.String(length=80), nullable=False),
        sa.Column("thread_id", sa.String(length=128), nullable=False),
        sa.Column("user_id", sa.String(length=128), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_business_analysis_runs"),
    )
    op.create_index(
        "ix_business_analysis_runs_thread_id",
        "business_analysis_runs",
        ["thread_id", "updated_at"],
    )

    op.create_table(
        "business_analysis_reports",
        sa.Column("id", sa.String(length=80), nullable=False),
        sa.Column("run_id", sa.String(length=80), nullable=False),
        sa.Column("report", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_business_analysis_reports"),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["business_analysis_runs.id"],
            name="fk_business_analysis_reports_run_id",
            ondelete="CASCADE",
        ),
    )
    op.create_index(
        "ix_business_analysis_reports_run_id",
        "business_analysis_reports",
        ["run_id"],
    )

    op.create_table(
        "business_analysis_artifacts",
        sa.Column("id", sa.String(length=80), nullable=False),
        sa.Column("run_id", sa.String(length=80), nullable=False),
        sa.Column("kind", sa.String(length=64), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_business_analysis_artifacts"),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["business_analysis_runs.id"],
            name="fk_business_analysis_artifacts_run_id",
            ondelete="CASCADE",
        ),
    )
    op.create_index(
        "ix_business_analysis_artifacts_run_id",
        "business_analysis_artifacts",
        ["run_id"],
    )

    op.create_table(
        "business_analysis_memories",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.String(length=128), nullable=False),
        sa.Column("memory_key", sa.String(length=64), nullable=False),
        sa.Column("memory_value", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_business_analysis_memories"),
        sa.UniqueConstraint(
            "user_id",
            "memory_key",
            name="uq_business_analysis_memories_user_id_memory_key",
        ),
    )


def downgrade() -> None:
    op.drop_table("business_analysis_memories")
    op.drop_index("ix_business_analysis_artifacts_run_id", table_name="business_analysis_artifacts")
    op.drop_table("business_analysis_artifacts")
    op.drop_index("ix_business_analysis_reports_run_id", table_name="business_analysis_reports")
    op.drop_table("business_analysis_reports")
    op.drop_index("ix_business_analysis_runs_thread_id", table_name="business_analysis_runs")
    op.drop_table("business_analysis_runs")
