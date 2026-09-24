from __future__ import annotations

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.store.postgres import AsyncPostgresStore


def normalize_checkpoint_url(connection_string: str) -> str:
    if connection_string.startswith("postgresql+asyncpg://"):
        return "postgresql://" + connection_string.split("://", 1)[1]
    return connection_string


def build_postgres_checkpoint(connection_string: str):
    """Return the async context manager supplied by the verified package version."""

    return AsyncPostgresSaver.from_conn_string(connection_string)


def build_postgres_store(connection_string: str):
    """Return the async Store context manager supplied by the verified package version."""

    return AsyncPostgresStore.from_conn_string(connection_string)
