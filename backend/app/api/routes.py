from typing import Literal

from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel, Field

from app.agent.graph import run_agent
from app.core.exceptions import ConfigurationError
from app.services.database_health import check_database

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
