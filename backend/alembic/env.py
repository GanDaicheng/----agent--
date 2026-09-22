"""Alembic 运行环境。

三个关键点：
1. 连接串不落在 alembic.ini 里，而是运行时从 app.core.config 读 .env，
   这样 alembic.ini 可以安全地提交进 Git。
2. 项目用的是 async SQLAlchemy + asyncpg，所以这里建的是 async engine，
   Alembic 的迁移函数本身仍是同步 API，通过 connection.run_sync 桥接过去。
3. target_metadata 指向 app.models 的 Base.metadata，autogenerate 才能比对出差异。
"""

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from app.core.config import get_settings
from app.models import Base

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def get_database_url() -> str:
    """从应用配置层取异步连接串。

    复用 require_database_url()：缺失或驱动写错时会抛出说明清楚的配置错误，
    并且报错信息里不含连接串本身。
    """
    return get_settings().require_database_url()


def run_migrations_offline() -> None:
    """离线模式：只把 SQL 打到标准输出，不真正连库。"""
    context.configure(
        url=get_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        # 打开类型与默认值比对，避免列类型被悄悄改了而迁移没跟上
        compare_type=True,
        compare_server_default=True,
    )

    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """用 asyncpg 建引擎，再把同步的迁移流程交给 run_sync 执行。"""
    configuration = config.get_section(config.config_ini_section, {})
    # 只写进内存中的 Config 对象，不会落盘到 alembic.ini
    configuration["sqlalchemy.url"] = get_database_url()

    connectable = async_engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
