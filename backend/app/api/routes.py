import logging
from collections.abc import Mapping
from typing import Literal

from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel, Field, ValidationError, field_validator

from app.agent.data_query.constants import (
    NODE_DISCOVER_ASSETS,
    NODE_EXECUTE_QUERY,
    NODE_EXPLAIN_RESULT,
    NODE_FINISH,
    NODE_GENERATE_SQL,
    NODE_INTAKE,
    NODE_REPAIR_SQL,
    NODE_SUGGEST_VISUALIZATION,
    NODE_UNDERSTAND_QUESTION,
    NODE_VALIDATE_SQL,
)
from app.agent.data_query.graph import get_data_query_graph
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

logger = logging.getLogger(__name__)

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


# --------------------------------------------------------------------------
# 智能问数（自然语言）接口的模型与安全映射
# --------------------------------------------------------------------------

AGENT_QUESTION_MAX_LENGTH = 500

# 路由级失败的统一文案。图构建失败、图执行抛异常、结果契约不合法，
# 对外都是这一句——具体原因只进服务端日志。
AGENT_UNAVAILABLE_DETAIL = "智能问数服务暂时不可用，请稍后重试。"

# Agent 出错时的兜底回答。
# 为什么需要它？因为 finish 的错误分支**只补一条事件、不写 answer**，
# 所以正常接线下的错误终态其实没有 answer。而接口契约要求 answer 始终存在。
# 这时优先复用 Agent 自己写好的安全错误说明（state["error"] 全是固定文案），
# 实在没有才用这句兜底。
AGENT_ERROR_FALLBACK_ANSWER = "智能问数未能完成，请稍后重试。"

# 内部事件 → 前端公开文案。键用 constants 里的节点名常量，不手抄字符串：
# 哪天有人改了节点名，对应关系会在这里立刻失配（而不是悄悄映射不到、事件消失）。
PUBLIC_EVENT_TEXT: dict[str, str] = {
    NODE_INTAKE: "已接收问题",
    NODE_UNDERSTAND_QUESTION: "已识别问题类型",
    NODE_DISCOVER_ASSETS: "已匹配可用数据资产",
    NODE_GENERATE_SQL: "已生成查询方案",
    NODE_VALIDATE_SQL: "已完成查询安全校验",
    NODE_REPAIR_SQL: "已尝试修复查询方案",
    NODE_EXECUTE_QUERY: "已完成数据查询",
    NODE_EXPLAIN_RESULT: "已生成分析结论",
    NODE_SUGGEST_VISUALIZATION: "已生成图表建议",
    NODE_FINISH: "分析流程已完成",
}

# 内部事件的形状是「节点名：细节」，分隔符就是中文冒号
EVENT_SEPARATOR = "："


def to_public_agent_events(events: object) -> list[str]:
    """把 Agent 内部事件映射成可以安全外发的固定文案。

    内部事件的细节部分不可信：里面可能有用户问题全文、SQL 片段、表名字段名，
    甚至异常类名。前端要的只是「流程走到哪一步了」，
    所以这里**只按节点名查表**，一个字符都不从原文复制。

    三条规则：
    - 只认「节点名：细节」这个形状，且节点名在映射表里；缺分隔符、前缀不认识
      一律丢弃（不猜、不兜底输出原文）；
    - 保持原有顺序，同一步骤重复出现也照原样保留（例如修复后再次校验）；
    - 非字符串一律跳过。
    """
    if not isinstance(events, list):
        return []

    public: list[str] = []
    for event in events:
        if not isinstance(event, str):
            continue
        node, separator, _detail = event.partition(EVENT_SEPARATOR)
        if not separator:
            # 不符合内部事件的固定形状，不能当成已知节点处理
            continue
        text = PUBLIC_EVENT_TEXT.get(node.strip())
        if text is not None:
            public.append(text)
    return public


class AgentDataQueryRequest(BaseModel):
    """自然语言问数请求。

    只收 question。SQL、intent、sql_draft、query_result、retry_count 这些
    Agent 内部状态**不在模型里**，因此客户端无从注入——
    请求体能影响的只有「问什么」这一个字段。

    同样是本地开发原型：没有身份认证，也没有按用户的配额。
    """

    question: str = Field(
        min_length=1,
        max_length=AGENT_QUESTION_MAX_LENGTH,
        description="用户的自然语言数据分析问题。",
    )

    @field_validator("question", mode="after")
    @classmethod
    def _strip_question(cls, value: str) -> str:
        """去掉首尾空白；纯空白视为非法输入。

        为什么放在校验器里而不是在路由里 strip？因为「纯空白」必须在
        进入业务逻辑**之前**就被挡掉，否则会一路走到 Agent 再失败，
        白白花掉一次模型调用。放在这里，它就是一个 422。
        """
        stripped = value.strip()
        if not stripped:
            raise ValueError("问题不能为空白。")
        return stripped


class AgentQueryResultResponse(BaseModel):
    """Agent 查询结果里允许公开的部分。

    注意没有 sql、没有执行耗时、没有连接信息——那些都在 Agent 和数据服务内部。
    source 保留 "mock" 是为了兼容测试与将来的显式演示模式；
    当前生产图只会返回 "postgres"。
    """

    columns: list[str]
    rows: list[dict[str, object]]
    row_count: int
    source: Literal["postgres", "mock"]


class AgentChartSuggestionResponse(BaseModel):
    """图表建议。七个字段全部必填——前端按固定下标取值，不做存在性判断。"""

    chart_type: Literal["line", "bar", "table", "none"]
    title: str
    x_field: str | None
    y_field: str | None
    series_field: str | None
    value_format: Literal["currency", "number", "percent"] | None
    reason: str


class AgentDataQueryResponse(BaseModel):
    """智能问数的对外响应。

    status 的两种取值对应两类完全不同的处境：
    - "ok"    ：Agent 正常跑完。**包括**未知意图、没有匹配资产、
                SQL 修复后仍不合规、查询 0 行这些业务结果——
                它们是 Agent 已经安全处理过的答案，不是服务故障。
    - "error" ：Agent 内部写了受控 error（意图识别失败、数据服务不可用等）。

    两种都是 HTTP 200：能给出一个安全、完整的回答，就说明服务本身是好的。
    """

    status: Literal["ok", "error"]
    answer: str
    query_result: AgentQueryResultResponse | None
    chart_suggestion: AgentChartSuggestionResponse | None
    events: list[str]


class AgentResponseContractError(Exception):
    """Agent 返回的 State 不符合公开契约。

    单独一个异常类型，是为了和「图执行失败」区分开：
    结果形状不对是我们自己的缺陷，必须显式失败，绝不静默修正后放行。
    """


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


def _to_query_result(raw: object) -> AgentQueryResultResponse | None:
    """把 State 里的 query_result 转成公开模型。

    两道检查，缺一不可：
    1. 形状（字段齐不齐、source 是否合法）交给 Pydantic；
    2. `row_count == len(rows)` 必须自己判——Pydantic 不会替我们比这个。

    对不上就是**失败**，不是「顺手改成 len(rows)」。行数和明细不一致说明
    产出方有 bug，静默补齐只会把问题推到前端更难排查的地方。
    """
    if raw is None:
        return None

    if not isinstance(raw, Mapping):
        raise AgentResponseContractError("query_result 不是键值结构。")

    try:
        result = AgentQueryResultResponse.model_validate(dict(raw))
    except ValidationError as exc:
        raise AgentResponseContractError("query_result 字段不符合契约。") from exc

    if result.row_count != len(result.rows):
        raise AgentResponseContractError("query_result 的 row_count 与 rows 长度不一致。")

    return result


def _to_chart_suggestion(raw: object) -> AgentChartSuggestionResponse | None:
    """图表建议必须七个字段齐全。缺字段就失败，不补默认值。"""
    if raw is None:
        return None

    if not isinstance(raw, Mapping):
        raise AgentResponseContractError("chart_suggestion 不是键值结构。")

    try:
        return AgentChartSuggestionResponse.model_validate(dict(raw))
    except ValidationError as exc:
        raise AgentResponseContractError("chart_suggestion 字段不符合契约。") from exc


def build_agent_response(state: object) -> AgentDataQueryResponse:
    """把 Agent 的 State 筛成可以安全外发的响应。

    这是个**纯函数**：不碰数据库、不调模型、不读配置，
    因此可以脱离 HTTP 直接单测各种畸形 State。

    这里做的是「白名单式」的字段挑选——只取 answer / query_result /
    chart_suggestion / events 四项，逐项转换；State 里其余的键
    （sql_draft、sql_validation、matched_assets、retry_count、intent、
    error、question）根本不会被读出来，也就没有「忘记过滤」的风险。
    """
    if not isinstance(state, Mapping):
        raise AgentResponseContractError("Agent 返回的 State 不是键值结构。")

    error = state.get("error")
    answered = state.get("answer")

    if not isinstance(answered, str) or not answered.strip():
        # Agent 出错时不会写 answer（finish 的错误分支只补事件），
        # 所以这里退回它自己生成的安全错误说明。
        if isinstance(error, str) and error.strip():
            answered = error
        else:
            answered = AGENT_ERROR_FALLBACK_ANSWER

    events = to_public_agent_events(state.get("events"))

    if error:
        # 受控失败：不返回可能残留的 query_result / chart_suggestion。
        # 出错时它们要么不存在，要么是上一次尝试的中间产物，一律不外发。
        return AgentDataQueryResponse(
            status="error",
            answer=answered,
            query_result=None,
            chart_suggestion=None,
            events=events,
        )

    return AgentDataQueryResponse(
        status="ok",
        answer=answered,
        query_result=_to_query_result(state.get("query_result")),
        chart_suggestion=_to_chart_suggestion(state.get("chart_suggestion")),
        events=events,
    )


@router.post(
    "/api/v1/agent/data-query",
    response_model=AgentDataQueryResponse,
    responses={
        500: {"description": AGENT_UNAVAILABLE_DETAIL},
    },
)
async def agent_data_query(req: AgentDataQueryRequest) -> AgentDataQueryResponse:
    """自然语言智能问数。

    路由只做四件事：接参数、取生产图、await 图执行、把 State 筛成安全响应。
    它**不**理解业务问题、不生成或校验 SQL、不查数据库、不解释结果、不建议图表——
    那些全部在 LangGraph Agent 和数据中台服务里，路由重复一遍只会多出一份会走样的副本。

    三点必须守住的约定：

    1. 用 `await graph.ainvoke(...)`。生产图里 execute_query 是异步节点
       （它要 await 数据服务），LangGraph 对含异步节点的图**拒绝**同步 invoke；
       而且本函数运行在 FastAPI 的事件循环里，绝不能再套 asyncio.run()。
    2. 不绕过 Agent 直接调用 execute_safe_query / get_engine。
       数据访问只有一个入口，就是 Agent。
    3. 不通过 HTTP 调用自己的 /api/v1/data/query —— 同进程内直接调函数即可。

    状态码约定：
    - 200：Agent 给出了回答。**error 也是 200**，因为那是一个安全的、
          可展示的业务结果，不是 HTTP 层故障。
    - 422：请求体不合法（缺 question、纯空白、超过长度上限）。
    - 500：图构建/执行抛异常，或 Agent 返回的 State 不符合公开契约。

    错误响应只回显固定文案，绝不带问题原文、SQL、连接串或异常原文；
    服务端日志也只记异常类型。
    """
    try:
        graph = get_data_query_graph()
        state = await graph.ainvoke({"question": req.question})
    except Exception as exc:  # noqa: BLE001
        # 只记异常类名。异常原文里可能带着连接串、SQL 片段甚至密钥；
        # 也**不记 req.question** —— 用户问题属于用户数据，不进普通日志。
        logger.warning("智能问数执行失败：%s", type(exc).__name__)
        raise HTTPException(status_code=500, detail=AGENT_UNAVAILABLE_DETAIL) from exc

    try:
        return build_agent_response(state)
    except AgentResponseContractError as exc:
        # 契约异常的信息都是固定文案，可以直接进日志
        logger.warning("智能问数结果不符合公开契约：%s", exc)
        raise HTTPException(status_code=500, detail=AGENT_UNAVAILABLE_DETAIL) from exc
