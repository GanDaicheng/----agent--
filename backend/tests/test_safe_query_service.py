"""只读执行服务的测试。

用替身（fake engine / fake connection / fake runner）驱动，不依赖真实 PostgreSQL，
这样 CI 上没有数据库也能跑。真实数据库的行为由 scripts 之外的冒烟验证覆盖。

重点验证三件事：
1. 只读事务与超时设置真的被执行了，且顺序正确；
2. 结果序列化对 Decimal / 日期 / None 等类型是对的，未知类型不会被静默 str()；
3. 各种失败都被翻译成受控异常，且不泄露 SQL、连接串、密钥或数据库异常原文。
"""

import asyncio
import functools
from datetime import date, datetime, timezone
from decimal import Decimal
from uuid import UUID

import pytest
from sqlalchemy.exc import DBAPIError, OperationalError

from app.services.safe_query import (
    LOCK_TIMEOUT_MS,
    MAX_RESULT_ROWS,
    READ_ONLY_PREAMBLE,
    STATEMENT_TIMEOUT_MS,
    DatabaseUnavailableError,
    QueryExecutionError,
    ResultSerializationError,
    ResultTooLargeError,
    SafeQueryResult,
    UnsafeSqlError,
    execute_safe_query,
    run_readonly_query,
)

VALID_SQL = "SELECT COUNT(*) AS total FROM orders LIMIT 5"


def async_test(func):
    """把 async 测试函数跑成同步测试。

    项目没有装 pytest-asyncio（本阶段不新增依赖），所以这里手工
    asyncio.run 一下。每个测试各自起一个事件循环，互不干扰。
    """

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        return asyncio.run(func(*args, **kwargs))

    return wrapper

# --------------------------------------------------------------------------
# 替身
# --------------------------------------------------------------------------


class FakeTransaction:
    def __init__(self) -> None:
        self.rolled_back = False

    async def rollback(self) -> None:
        self.rolled_back = True


class FakeCursorResult:
    def __init__(self, columns, rows) -> None:
        self._columns = list(columns)
        self._rows = list(rows)
        self.closed = False

    def keys(self):
        return list(self._columns)

    def fetchmany(self, size):
        return self._rows[:size]

    def close(self) -> None:
        self.closed = True


class FakeConnection:
    """记录所有被执行过的语句，可选地在执行用户 SQL 时抛错。"""

    def __init__(self, result=None, execute_error=None) -> None:
        self.executed: list[str] = []
        self.transaction = FakeTransaction()
        self.result = result if result is not None else FakeCursorResult(["total"], [(3404,)])
        self.execute_error = execute_error

    async def begin(self):
        return self.transaction

    async def execute(self, statement):
        sql = str(statement)
        self.executed.append(sql)
        # 事务设置语句永远成功，失败只模拟用户查询本身
        if self.execute_error is not None and not sql.startswith("SET"):
            raise self.execute_error
        return self.result


class FakeConnectContext:
    def __init__(self, connection: FakeConnection) -> None:
        self._connection = connection

    async def __aenter__(self) -> FakeConnection:
        return self._connection

    async def __aexit__(self, *exc_info) -> bool:
        return False


class FakeEngine:
    def __init__(self, connection=None, connect_error=None) -> None:
        self.connection = connection if connection is not None else FakeConnection()
        self.connect_error = connect_error
        self.connect_calls = 0

    def connect(self):
        self.connect_calls += 1
        if self.connect_error is not None:
            raise self.connect_error
        return FakeConnectContext(self.connection)


def make_dbapi_error(message: str, sqlstate: str | None = None) -> DBAPIError:
    """构造一个带 sqlstate 的数据库异常，模拟 asyncpg 经 SQLAlchemy 抛出的样子。"""

    class FakeOrig(Exception):
        pass

    orig = FakeOrig(message)
    if sqlstate is not None:
        orig.sqlstate = sqlstate  # type: ignore[attr-defined]
    return DBAPIError("SELECT ...", {}, orig)


# --------------------------------------------------------------------------
# 只读事务设置
# --------------------------------------------------------------------------


@async_test
async def test_read_only_preamble_runs_before_the_user_query():
    engine = FakeEngine()

    await run_readonly_query(VALID_SQL, engine=engine)

    executed = engine.connection.executed
    # SET TRANSACTION 必须是事务里的第一条语句，否则 PostgreSQL 会静默忽略只读设置
    assert executed[0] == "SET TRANSACTION READ ONLY"
    assert executed[: len(READ_ONLY_PREAMBLE)] == list(READ_ONLY_PREAMBLE)
    assert executed[-1] == VALID_SQL


@async_test
async def test_statement_and_lock_timeouts_are_set():
    engine = FakeEngine()

    await run_readonly_query(VALID_SQL, engine=engine)

    executed = engine.connection.executed
    assert f"SET LOCAL statement_timeout = '{STATEMENT_TIMEOUT_MS}ms'" in executed
    assert f"SET LOCAL lock_timeout = '{LOCK_TIMEOUT_MS}ms'" in executed


@async_test
async def test_transaction_is_rolled_back_and_cursor_closed():
    engine = FakeEngine()

    await run_readonly_query(VALID_SQL, engine=engine)

    assert engine.connection.transaction.rolled_back is True
    assert engine.connection.result.closed is True


@async_test
async def test_transaction_is_rolled_back_even_when_the_query_fails():
    connection = FakeConnection(execute_error=make_dbapi_error("boom", "42703"))
    engine = FakeEngine(connection=connection)

    with pytest.raises(QueryExecutionError):
        await run_readonly_query(VALID_SQL, engine=engine)

    assert connection.transaction.rolled_back is True


# --------------------------------------------------------------------------
# 结果序列化
# --------------------------------------------------------------------------


@async_test
async def test_result_values_are_json_serializable():
    row = (
        12,
        Decimal("280302.01"),
        date(2025, 1, 1),
        datetime(2025, 1, 1, 12, 30, tzinfo=timezone.utc),
        UUID("12345678-1234-5678-1234-567812345678"),
        None,
        True,
    )
    columns = ["month", "amount", "day", "ts", "uid", "missing", "flag"]
    engine = FakeEngine(FakeConnection(result=FakeCursorResult(columns, [row])))

    result = await run_readonly_query(VALID_SQL, engine=engine)

    assert result.columns == columns
    assert result.row_count == 1
    assert result.rows[0] == {
        "month": 12,
        "amount": 280302.01,  # Decimal → JSON number
        "day": "2025-01-01",
        "ts": "2025-01-01T12:30:00+00:00",
        "uid": "12345678-1234-5678-1234-567812345678",
        "missing": None,
        "flag": True,
    }


@async_test
async def test_decimal_becomes_float_but_int_stays_int():
    engine = FakeEngine(
        FakeConnection(result=FakeCursorResult(["amount", "count"], [(Decimal("10.50"), 3)]))
    )

    result = await run_readonly_query(VALID_SQL, engine=engine)

    assert isinstance(result.rows[0]["amount"], float)
    assert isinstance(result.rows[0]["count"], int)
    assert result.rows[0]["amount"] == 10.5


@async_test
async def test_bool_is_not_confused_with_int():
    """Python 里 bool 是 int 的子类，序列化顺序写反会把 True 变成 1。"""
    engine = FakeEngine(FakeConnection(result=FakeCursorResult(["flag"], [(True,)])))

    result = await run_readonly_query(VALID_SQL, engine=engine)

    assert result.rows[0]["flag"] is True


@async_test
async def test_unknown_type_raises_instead_of_silently_stringifying():
    class Weird:
        def __str__(self) -> str:
            return "看起来很无辜"

    engine = FakeEngine(FakeConnection(result=FakeCursorResult(["weird"], [(Weird(),)])))

    with pytest.raises(ResultSerializationError):
        await run_readonly_query(VALID_SQL, engine=engine)


@async_test
async def test_row_count_matches_rows():
    rows = [(index,) for index in range(7)]
    engine = FakeEngine(FakeConnection(result=FakeCursorResult(["n"], rows)))

    result = await run_readonly_query(VALID_SQL, engine=engine)

    assert result.row_count == len(result.rows) == 7


# --------------------------------------------------------------------------
# 行数上限
# --------------------------------------------------------------------------


@async_test
async def test_result_at_the_limit_is_accepted():
    rows = [(index,) for index in range(MAX_RESULT_ROWS)]
    engine = FakeEngine(FakeConnection(result=FakeCursorResult(["n"], rows)))

    result = await run_readonly_query(VALID_SQL, engine=engine)

    assert result.row_count == MAX_RESULT_ROWS


@async_test
async def test_result_over_the_limit_is_rejected():
    """LIMIT 已限制在 200 以内，走到这里说明校验被绕过，必须受控失败。"""
    rows = [(index,) for index in range(MAX_RESULT_ROWS + 1)]
    engine = FakeEngine(FakeConnection(result=FakeCursorResult(["n"], rows)))

    with pytest.raises(ResultTooLargeError):
        await run_readonly_query(VALID_SQL, engine=engine)


# --------------------------------------------------------------------------
# 异常翻译与脱敏
# --------------------------------------------------------------------------


@async_test
async def test_connection_refused_maps_to_unavailable():
    engine = FakeEngine(connect_error=ConnectionRefusedError("connection refused"))

    with pytest.raises(DatabaseUnavailableError):
        await run_readonly_query(VALID_SQL, engine=engine)


@async_test
async def test_operational_error_maps_to_unavailable():
    engine = FakeEngine(connection=FakeConnection(execute_error=OperationalError("x", {}, Exception())))

    with pytest.raises(DatabaseUnavailableError):
        await run_readonly_query(VALID_SQL, engine=engine)


@async_test
async def test_sqlstate_class_08_maps_to_unavailable():
    error = make_dbapi_error("server closed the connection", "08006")
    engine = FakeEngine(connection=FakeConnection(execute_error=error))

    with pytest.raises(DatabaseUnavailableError):
        await run_readonly_query(VALID_SQL, engine=engine)


@async_test
async def test_bad_column_maps_to_query_execution_error():
    error = make_dbapi_error('column "nope" does not exist', "42703")
    engine = FakeEngine(connection=FakeConnection(execute_error=error))

    with pytest.raises(QueryExecutionError):
        await run_readonly_query(VALID_SQL, engine=engine)


@async_test
async def test_statement_timeout_maps_to_query_execution_error():
    error = make_dbapi_error("canceling statement due to statement timeout", "57014")
    engine = FakeEngine(connection=FakeConnection(execute_error=error))

    with pytest.raises(QueryExecutionError):
        await run_readonly_query(VALID_SQL, engine=engine)


@pytest.mark.parametrize(
    "secret_payload",
    [
        "postgresql://data_platform:sup3r-s3cret@localhost:5432/data_platform",
        "sk-secret-api-key-12345",
    ],
)
@async_test
async def test_errors_never_leak_secrets_or_sql(secret_payload):
    """底层异常原文里带着连接串/密钥/ SQL 时，对外异常一个字都不能带出来。"""
    error = make_dbapi_error(f"failed while running {VALID_SQL} using {secret_payload}", "42703")
    engine = FakeEngine(connection=FakeConnection(execute_error=error))

    with pytest.raises(QueryExecutionError) as excinfo:
        await run_readonly_query(VALID_SQL, engine=engine)

    text = str(excinfo.value)
    assert secret_payload not in text
    assert "sup3r-s3cret" not in text
    assert "sk-secret" not in text
    assert VALID_SQL not in text
    assert "postgresql://" not in text
    assert "does not exist" not in text


@async_test
async def test_connection_error_message_is_also_sanitized():
    engine = FakeEngine(
        connect_error=ConnectionRefusedError(
            "could not connect to postgresql://user:secret@localhost:5432/db"
        )
    )

    with pytest.raises(DatabaseUnavailableError) as excinfo:
        await run_readonly_query(VALID_SQL, engine=engine)

    assert "secret" not in str(excinfo.value)
    assert "postgresql://" not in str(excinfo.value)


# --------------------------------------------------------------------------
# 编排：校验与执行的职责分离
# --------------------------------------------------------------------------


class RecordingRunner:
    def __init__(self, result=None) -> None:
        self.calls: list[str] = []
        self.result = result if result is not None else SafeQueryResult(
            columns=["total"], rows=[{"total": 1}], row_count=1
        )

    async def __call__(self, sql: str) -> SafeQueryResult:
        self.calls.append(sql)
        return self.result


@async_test
async def test_valid_sql_is_handed_to_the_runner():
    runner = RecordingRunner()

    result = await execute_safe_query(VALID_SQL, runner=runner)

    assert runner.calls == [VALID_SQL]
    assert result.row_count == 1


@pytest.mark.parametrize(
    "sql",
    [
        "DELETE FROM orders",
        "SELECT * FROM orders LIMIT 5",
        "SELECT orders.order_id FROM orders",
        "SELECT pg_sleep(10) AS v FROM orders LIMIT 5",
        "SELECT t.table_name FROM information_schema.tables AS t LIMIT 5",
    ],
)
@async_test
async def test_invalid_sql_never_reaches_the_runner(sql):
    """最关键的一条：校验没过时，执行器一次都不能被调用。"""
    runner = RecordingRunner()

    with pytest.raises(UnsafeSqlError):
        await execute_safe_query(sql, runner=runner)

    assert runner.calls == []


@async_test
async def test_unsafe_sql_error_carries_safe_issues_only():
    runner = RecordingRunner()

    with pytest.raises(UnsafeSqlError) as excinfo:
        await execute_safe_query("DELETE FROM orders", runner=runner)

    error = excinfo.value
    assert error.issues
    assert "DELETE FROM orders" not in str(error)
    assert all("DELETE" not in issue for issue in error.issues)


@async_test
async def test_runner_is_not_called_for_blank_sql():
    runner = RecordingRunner()

    with pytest.raises(UnsafeSqlError):
        await execute_safe_query("   ", runner=runner)

    assert runner.calls == []
