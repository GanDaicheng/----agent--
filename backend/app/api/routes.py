from typing import Literal

from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel, Field

from app.agent.graph import run_agent
from app.core.exceptions import ConfigurationError
from app.services.database_health import check_database
from app.services.safe_query import (
    MAX_SQL_LENGTH,
    DatabaseUnavailableError,
    QueryExecutionError,
    ResultSerializationError,
    ResultTooLargeError,
    UnsafeSqlError,
    execute_safe_query,
)

router = APIRouter()


class Message(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    messages: list[Message] = Field(min_length=1)


class ChatResponse(BaseModel):
    reply: str


class DatabaseHealthResponse(BaseModel):
    status: str
    database: str
    error_type: str | None = None
    message: str | None = None


class ApplicationHealthResponse(DatabaseHealthResponse):
    """统一健康检查的响应：在数据库探针结果上补一个服务标识。

    service 用 Literal["backend"] 固定住，Docker Compose 的 healthcheck
    可以据此确认应答确实来自后端，而不是别的什么占用了 8000 端口。
    """

    service: Literal["backend"] = "backend"


class SafeQueryRequest(BaseModel):
    """数据服务的查询请求。

    这是本地开发原型：没有身份认证，也没有按用户的行级数据权限。
    生产环境必须在网关或本层补上认证、授权与数据权限过滤。
    """

    sql: str = Field(
        min_length=1,
        max_length=MAX_SQL_LENGTH,
        description="仅允许受控的单条 PostgreSQL SELECT 分析查询。必须包含 LIMIT（1~200）。",
    )


class SafeQueryResponse(BaseModel):
    """结构化只读查询结果。

    columns 与 rows 中每个字典的键顺序一致；source 固定为 postgres，
    便于调用方区分数据来源。响应里不含原始 SQL。
    """

    columns: list[str]
    rows: list[dict[str, object]]
    row_count: int
    source: Literal["postgres"] = "postgres"


class SafeQueryErrorResponse(BaseModel):
    """安全查询失败时的响应体。issues 里只有固定文案，不回显调用方的 SQL。"""

    message: str
    issues: list[str] = Field(default_factory=list)


@router.get("/")
def index() -> dict[str, str]:
    """后端服务说明。

    早期这里返回的是临时聊天页面，该文件已迁到 frontend/legacy-static/，
    不再由后端提供静态文件；页面渲染一律交给前端工程。
    """
    return {
        "service": "data-platform-agent-backend",
        "docs": "/docs",
        "health": "/api/v1/health",
    }


@router.post("/chat", response_model=ChatResponse)
def chat(req: ChatRequest) -> ChatResponse:
    try:
        reply = run_agent([m.model_dump() for m in req.messages])
    except ConfigurationError as exc:
        # 配置类错误（如缺 key）直接告诉调用方原因
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"模型调用失败：{exc}") from exc
    return ChatResponse(reply=reply)


async def get_database_health(response: Response) -> DatabaseHealthResponse:
    """共用的数据库健康探测：只负责把探测结果翻译成 HTTP 状态码和响应体。

    真实连接逻辑在 app/services/database_health.py，这里不重复任何数据库代码。
    两个健康接口都走这个函数，避免以后改一处漏一处。
    """
    try:
        result = await check_database()
    except ConfigurationError as exc:
        # 连接串缺失或驱动不对，属于服务端配置问题，直接说明原因
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    if not result.connected:
        # 依赖不可用用 503，而不是 500：这是「下游挂了」，不是「本服务写错了」
        response.status_code = 503
        return DatabaseHealthResponse(
            status="error",
            database="unavailable",
            error_type=result.error_type,
            message=result.message,
        )
    return DatabaseHealthResponse(status="ok", database="connected")


@router.get(
    "/api/v1/health",
    response_model=ApplicationHealthResponse,
    # 成功时只输出 status / service / database，不带上 null 的错误字段
    response_model_exclude_none=True,
)
async def application_health(response: Response) -> ApplicationHealthResponse:
    """统一健康检查。Docker Compose 用它判断后端是否真正可用。"""
    health = await get_database_health(response)
    return ApplicationHealthResponse(
        service="backend",
        **health.model_dump(exclude_none=True),
    )


@router.get(
    "/health/db",
    response_model=DatabaseHealthResponse,
    # 成功时只输出 status 和 database 两个字段，不带上 null 的错误字段
    response_model_exclude_none=True,
)
async def health_db(response: Response) -> DatabaseHealthResponse:
    """数据库连通性自检：只执行 SELECT 1。宿主机开发时的调试探针。"""
    return await get_database_health(response)


@router.post(
    "/api/v1/data/query",
    response_model=SafeQueryResponse,
    responses={
        400: {"model": SafeQueryErrorResponse, "description": "已通过安全校验但执行失败"},
        422: {"model": SafeQueryErrorResponse, "description": "未通过安全策略"},
        503: {"model": SafeQueryErrorResponse, "description": "数据库不可用"},
    },
)
async def data_query(req: SafeQueryRequest) -> SafeQueryResponse:
    """受控只读分析查询。

    路由本身只做「调用服务 → 把受控异常翻译成状态码」，不解析 SQL、
    不拼 SQL、不直接碰 engine。所有安全策略都在 app/services/safe_query.py。

    状态码约定：
    - 200：合规查询执行成功
    - 422：请求体非法（缺少 sql / 长度超限），或 SQL 未通过安全策略
    - 400：已通过安全校验，但语句本身执行失败（字段类型不符、超时被取消等）
    - 503：数据库不可用
    - 500：服务端配置缺失，或结果无法安全序列化

    错误响应只回显固定文案，绝不带原始 SQL、连接串或数据库异常原文。
    """
    try:
        result = await execute_safe_query(req.sql)
    except UnsafeSqlError as exc:
        # issues 是服务端预定义的固定文案，不含调用方输入
        raise HTTPException(
            status_code=422,
            detail={"message": str(exc), "issues": exc.issues},
        ) from exc
    except DatabaseUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except QueryExecutionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except (ResultSerializationError, ResultTooLargeError) as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except ConfigurationError as exc:
        # 连接串缺失或驱动不对：服务端自身配置问题，与健康检查保持一致的 500
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return SafeQueryResponse(
        columns=result.columns,
        rows=result.rows,
        row_count=result.row_count,
        source="postgres",
    )
