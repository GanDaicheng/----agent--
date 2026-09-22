"""数据库连通性检查：只执行 SELECT 1，不涉及任何业务表。"""

import logging
from dataclasses import dataclass

from sqlalchemy import text

from app.core.exceptions import ConfigurationError
from app.repositories.database import get_connection

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DatabaseHealthResult:
    connected: bool
    error_type: str | None = None
    message: str = "数据库连接正常"


async def check_database() -> DatabaseHealthResult:
    """探测数据库是否可连接。

    连接失败时返回结构化结果而不是抛异常，让接口层能区分状态码；
    配置缺失属于服务端自身问题，原样抛出交给接口层返回明确的配置错误。
    """
    try:
        async with get_connection() as conn:
            await conn.execute(text("SELECT 1"))
    except ConfigurationError:
        raise
    except Exception as exc:
        # 只记录异常类名。驱动异常的原文可能带出主机、用户名甚至整个连接串，
        # 类名（如 InvalidPasswordError / ConnectionRefusedError）已足够定位问题。
        logger.warning("数据库健康检查失败：%s", type(exc).__name__)
        return DatabaseHealthResult(
            connected=False,
            error_type=type(exc).__name__,
            message="无法连接数据库，请确认 PostgreSQL 容器已启动且 DATABASE_URL 配置正确。",
        )
    return DatabaseHealthResult(connected=True)
