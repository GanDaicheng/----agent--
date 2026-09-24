import asyncio

from app.core.event_loop import selector_loop_factory


def test_selector_loop_factory_returns_a_selector_compatible_loop():
    loop = selector_loop_factory()
    try:
        assert isinstance(loop, asyncio.SelectorEventLoop)
    finally:
        loop.close()
