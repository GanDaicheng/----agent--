"""Uvicorn event-loop factory compatible with psycopg async connections."""

import asyncio


def selector_loop_factory() -> asyncio.AbstractEventLoop:
    """Return a selector loop on every platform.

    psycopg's async implementation cannot run on Windows ProactorEventLoop.
    Uvicorn imports this factory before creating the serving loop, unlike an
    application-level policy change which would be too late.
    """

    return asyncio.SelectorEventLoop()
