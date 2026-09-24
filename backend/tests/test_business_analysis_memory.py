import pytest

from app.agent.business_analysis.memory import (
    load_user_preferences,
    save_user_preference,
)
from app.agent.business_analysis.persistence import normalize_checkpoint_url


class FakeStore:
    def __init__(self):
        self.values = {}

    async def aput(self, namespace, key, value):
        self.values[(tuple(namespace), key)] = value

    async def aget(self, namespace, key):
        return self.values.get((tuple(namespace), key))


class FakeConnection:
    def __init__(self):
        self.statements = []

    async def execute(self, statement, params):
        self.statements.append((str(statement), params))


@pytest.mark.anyio
async def test_preference_is_applied_to_new_thread():
    store = FakeStore()

    await save_user_preference(store, "user-1", "currency_unit", "万元")
    preferences = await load_user_preferences(store, "user-1")

    assert preferences["currency_unit"] == "万元"


@pytest.mark.anyio
async def test_unknown_preference_key_is_rejected():
    store = FakeStore()

    with pytest.raises(ValueError):
        await save_user_preference(store, "user-1", "prompt", "secret")


def test_checkpoint_url_removes_sqlalchemy_driver_suffix():
    assert normalize_checkpoint_url(
        "postgresql+asyncpg://user:pass@localhost/db"
    ) == "postgresql://user:pass@localhost/db"


@pytest.mark.anyio
async def test_save_user_preference_to_db_uses_upsert():
    from app.agent.business_analysis.memory import save_user_preference_to_db

    connection = FakeConnection()
    await save_user_preference_to_db(connection, "user-1", "currency_unit", "万元")

    assert "ON CONFLICT" in connection.statements[0][0]
    assert connection.statements[0][1]["user_id"] == "user-1"
