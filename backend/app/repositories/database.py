"""数据库引擎与连接的创建入口。

本模块只负责「怎么连上数据库」，不含任何表结构、ORM 模型或业务 SQL。
ORM 模型放 app/models，业务查询放 app/services。
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, create_async_engine

from app.core.config import get_settings

_engine: AsyncEngine | None = None


def get_engine() -> AsyncEngine:
    """懒加载并复用 Engine。

    Engine 内部自带连接池，整个进程共用一个即可。这里不在导入时创建，
    否则数据库没配好时连 import 都会失败。
    """
    global _engine
    if _engine is None:
        _engine = create_async_engine(
            get_settings().require_database_url(),
            # PostgreSQL 容器重启后池里的旧连接会失效；用前先探活，坏连接自动换掉
            pool_pre_ping=True,
            echo=False,
        )
    return _engine


async def dispose_engine() -> None:
    """关闭连接池。应用退出时调用，避免热重载反复启动时堆积残留连接。"""
    global _engine
    if _engine is not None:
        await _engine.dispose()
        _engine = None


@asynccontextmanager
async def get_connection() -> AsyncIterator[AsyncConnection]:
    """借出一条数据库连接，with 块结束时自动归还连接池。"""
    async with get_engine().connect() as conn:
        yield conn
