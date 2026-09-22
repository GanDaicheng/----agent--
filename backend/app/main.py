from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.routes import router
from app.core.logging import configure_logging
from app.repositories.database import dispose_engine

configure_logging()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """应用生命周期：启动时什么都不用做，退出时释放数据库连接池。

    必须显式关闭，否则 --reload 反复重启会遗留一批没归还的连接，
    数据库端的连接数会慢慢涨上去。
    """
    yield
    await dispose_engine()


app = FastAPI(
    title="数据中台 Agent",
    description="零售数据中台智能问数工作台后端服务",
    version="0.1.0",
    lifespan=lifespan,
)

app.include_router(router)
