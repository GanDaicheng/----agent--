"""Agent 与数据中台安全查询服务的唯一接入点。

依赖方向（只能这一个方向）：

    AI 中台 Agent
    → 数据中台 app.services.safe_query.execute_safe_query
    → 数据库基础设施

三条硬边界，本模块是它们的落点：

1. **Agent 不直接连数据库**。不导入 sqlalchemy / asyncpg、不拿 AsyncEngine、
   不碰 app.repositories，也不读数据库配置。所有取数都必须经过
   execute_safe_query 这一道已经做过 AST 校验 + 只读事务的关口。
2. **不经 HTTP 调用自己**。后端和 safe_query 在同一个进程里，
   绕过 HTTP 直接调服务函数：少一次序列化、少一个端口、
   也不会因为自己没起来而调用失败。
3. **两层 SQL 校验都要保留**。Agent 自己的 validate_sql 管「工作流」——
   支持 repair_sql、挡住明显不合规的草稿；数据服务的 validate_safe_select
   管「数据库」——独立于 Agent 存在，未来别的调用方也受它保护。
   本模块不重复实现任何白名单或 SQL 解析，那是数据服务的职责。

本模块只做三件事：调用、转换、把异常翻译成安全文案。
"""

from collections.abc import Awaitable, Callable, Mapping
from typing import Any

from app.services.safe_query import (
    DatabaseUnavailableError,
    SafeQueryResult,
    UnsafeSqlError,
    execute_safe_query,
)

from app.agent.data_query.state import QueryResult

# 数据来源标记。与 state.QueryResult 的 Literal 必须一致，有测试钉住。
SOURCE_MOCK = "mock"
SOURCE_POSTGRES = "postgres"
ALLOWED_SOURCES: tuple[str, ...] = (SOURCE_MOCK, SOURCE_POSTGRES)

REQUIRED_FIELDS: tuple[str, ...] = ("columns", "rows", "row_count", "source")

# 面向用户的受控文案。刻意都写得很笼统：
# 用户需要的是「能不能重试」，不是「哪个字段错了」。
# 数据服务的 issues、异常原文、SQL 原文一律不进这里。
REJECTED_MESSAGE = "生成的查询未通过数据服务安全策略，因此没有执行。"
UNAVAILABLE_MESSAGE = "数据服务暂时不可用，请稍后重试。"
FAILED_MESSAGE = "真实数据查询失败，请稍后重试。"
CONTRACT_MESSAGE = "真实数据查询返回的结果不符合约定，已终止后续分析。"


class QueryResultContractError(Exception):
    """执行器返回的结果不符合 QueryResult 契约。

    单独一个异常类型，是为了让节点把它和「执行失败」分开处理：
    结果形状不对是**代码缺陷**，不是业务失败，绝不能被静默修正后放行。
    """


# 执行器的统一契约：吃 sql（+ 意图），还一份已经成形的 QueryResult。
# 真实执行器和 mock 执行器都满足它，因此节点只有一条代码路径。
QueryExecutor = Callable[..., Awaitable[QueryResult]]


def _validate(
    columns: Any, rows: Any, row_count: Any, source: Any
) -> QueryResult:
    """四字段的公共校验，任何一项不合规都抛错（fail closed）。

    这里**只报「哪里不合规」，不报「实际值是什么」**——异常信息会顺着
    日志和 events 走，不该把结果内容带出去。
    """
    if not isinstance(columns, list) or not all(isinstance(name, str) for name in columns):
        raise QueryResultContractError("columns 必须是字符串列表。")

    if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
        raise QueryResultContractError("rows 必须是字典列表。")

    # bool 是 int 的子类，先排掉，避免 True 被当成合法行数
    if isinstance(row_count, bool) or not isinstance(row_count, int):
        raise QueryResultContractError("row_count 必须是整数。")

    if row_count != len(rows):
        # 明确不「顺手改成 len(rows)」：行数和明细对不上，
        # 说明产出方有 bug，静默补齐只会把问题推到更远的地方。
        raise QueryResultContractError("row_count 与 rows 长度不一致。")

    if source not in ALLOWED_SOURCES:
        raise QueryResultContractError("source 不是受支持的数据来源。")

    # 复制一份再交出去：不把调用方持有的可变结构直接塞进 State
    return {
        "columns": list(columns),
        "rows": [dict(row) for row in rows],
        "row_count": row_count,
        "source": source,
    }


def to_agent_query_result(result: SafeQueryResult) -> QueryResult:
    """把数据中台的 SafeQueryResult 转成 Agent 的 QueryResult。

    只做字段搬运，不重新实现任何 SQL 执行、白名单或序列化逻辑——
    那些都在数据服务里做完了，这里再写一遍只会多出一份会走样的副本。
    """
    if not isinstance(result, SafeQueryResult):
        raise QueryResultContractError("数据服务返回的结果类型不符合约定。")

    return _validate(result.columns, result.rows, result.row_count, SOURCE_POSTGRES)


def ensure_query_result_contract(raw: object) -> QueryResult:
    """校验任意执行器的返回值是否符合 QueryResult 契约。

    节点用它给**所有**执行器（真实的和测试替身）把关：
    契约为真不保证数据正确，但契约破了就一定有问题。
    """
    if not isinstance(raw, Mapping):
        raise QueryResultContractError("执行器返回值不是结构化的键值结果。")

    missing = [field for field in REQUIRED_FIELDS if field not in raw]
    if missing:
        raise QueryResultContractError("执行器返回值缺少必需字段。")

    return _validate(raw["columns"], raw["rows"], raw["row_count"], raw["source"])


async def execute_real_query(*, sql: str, intent: str = "unknown") -> QueryResult:
    """Agent 的默认执行器：调用数据中台安全查询服务读取真实数据。

    intent 参数在本函数里用不上，但保留它——执行器的契约对真实和 mock
    两个实现是同一份，节点因此不需要知道自己拿到的是哪一个。

    execute_safe_query 内部会做 AST 校验和只读事务，所以传进来的 SQL
    即使有问题，也只会在数据服务那一层被拒绝，不会碰到数据库。
    """
    result = await execute_safe_query(sql)
    return to_agent_query_result(result)


def describe_execution_failure(exc: BaseException) -> tuple[str, str]:
    """把执行阶段的异常翻译成 (面向用户的文案, 事件里的安全类别)。

    返回的类别只用**异常类名**：它足以定位问题方向（是策略拒绝、还是服务不可用、
    还是别的），又不像异常原文那样可能夹带连接串、SQL 片段或密钥。
    """
    if isinstance(exc, UnsafeSqlError):
        return REJECTED_MESSAGE, type(exc).__name__
    if isinstance(exc, DatabaseUnavailableError):
        return UNAVAILABLE_MESSAGE, type(exc).__name__
    return FAILED_MESSAGE, type(exc).__name__
