import pytest

from app.agent.business_analysis.memory import (
    load_user_preferences,
    save_user_preference,
)


class FakeStore:
    def __init__(self):
        self.values = {}

    async def aput(self, namespace, key, value):
        self.values[(tuple(namespace), key)] = value

    async def aget(self, namespace, key):
        return self.values.get((tuple(namespace), key))


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
