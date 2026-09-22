"""把零售样例数据写入本地 PostgreSQL。

用法（在 backend/ 目录下执行）：

    python scripts/seed_retail_data.py

幂等性：所有行都由 app.services.retail_seed 用固定种子确定性生成，
写入时统一使用 ON CONFLICT DO NOTHING。因此重复执行不会产生重复数据，
第二次执行的新增行数应当全部为 0。

连接串来自项目根 .env（经 app.core.config 读取），脚本本身不含任何凭据，
输出里也不会打印连接串。
"""

import asyncio
import sys
from dataclasses import dataclass
from pathlib import Path

# 直接以 `python scripts/seed_retail_data.py` 运行时，sys.path[0] 是 scripts/ 而不是
# backend/，会导致 `import app` 失败。这里显式把 backend/ 加进搜索路径。
BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from sqlalchemy import func, select  # noqa: E402
from sqlalchemy.dialects.postgresql import insert  # noqa: E402

from app.models.retail import Customer, DateDim, Order, Product, Region  # noqa: E402
from app.repositories.database import dispose_engine, get_engine  # noqa: E402
from app.services.retail_seed import SeedDataSet, build_seed_dataset  # noqa: E402

# 插入顺序必须满足外键依赖：先维度表，最后事实表
DIMENSION_TABLES = (
    ("regions", Region, ("region_id",)),
    ("customers", Customer, ("customer_id",)),
    ("products", Product, ("product_id",)),
    ("date_dim", DateDim, ("date_id",)),
)
FACT_TABLES = (("orders", Order, ("order_no",)),)


@dataclass(frozen=True)
class SeedSummary:
    """写库结果摘要，只含规模信息，不含任何凭据。"""

    inserted: dict[str, int]
    totals: dict[str, int]
    first_date: str
    last_date: str
    total_net_amount: str


async def _insert_ignore_conflicts(conn, model, conflict_columns, rows) -> None:
    """批量插入并跳过已存在的行。"""
    if not rows:
        return

    statement = insert(model).on_conflict_do_nothing(index_elements=list(conflict_columns))
    await conn.execute(statement, rows)


async def _count_rows(conn) -> dict[str, int]:
    """统计五张表当前行数。"""
    counts = {}
    for name, model, _ in DIMENSION_TABLES + FACT_TABLES:
        counts[name] = await conn.scalar(select(func.count()).select_from(model))
    return counts


async def seed_database() -> SeedSummary:
    dataset = build_seed_dataset()

    engine = get_engine()
    # 一个事务里写完五张表：中途失败不会留下「有维度没订单」的半截状态
    async with engine.begin() as conn:
        # 注意：ON CONFLICT 批量插入时 rowcount 在 asyncpg 下会返回 -1，
        # 不能用来判断新增行数。这里改为在同一个事务里比对写入前后的行数差，
        # 结果同样精确，而且不受驱动实现影响。
        before = await _count_rows(conn)

        for name, model, conflict_columns in DIMENSION_TABLES + FACT_TABLES:
            await _insert_ignore_conflicts(conn, model, conflict_columns, getattr(dataset, name))

        totals = await _count_rows(conn)
        inserted = {name: totals[name] - before[name] for name in totals}

        first_date, last_date = (
            await conn.execute(select(func.min(DateDim.full_date), func.max(DateDim.full_date)))
        ).one()
        total_net_amount = await conn.scalar(select(func.coalesce(func.sum(Order.net_amount), 0)))

    return SeedSummary(
        inserted=inserted,
        totals=totals,
        first_date=str(first_date),
        last_date=str(last_date),
        total_net_amount=str(total_net_amount),
    )


def print_summary(summary: SeedSummary) -> None:
    print("零售样例数据写入完成")
    print("-" * 46)
    for name in ("regions", "customers", "products", "date_dim", "orders"):
        print(f"  {name:<10} 总行数 {summary.totals[name]:>6}   本次新增 {summary.inserted[name]:>6}")
    print("-" * 46)
    print(f"  日期范围      {summary.first_date} ~ {summary.last_date}")
    print(f"  净销售额合计  {summary.total_net_amount}")

    if all(count == 0 for count in summary.inserted.values()):
        print("\n本次没有任何新增行 —— 幂等生效，数据库已是最新样例数据。")


async def main() -> int:
    try:
        summary = await seed_database()
    finally:
        await dispose_engine()

    print_summary(summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
