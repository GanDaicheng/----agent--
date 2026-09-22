"""零售样例数据的只读验证。

用法（在 backend/ 目录下执行）：

    python scripts/verify_retail_data.py

对数据库只做 SELECT，不写入、不修改任何数据。五个分析场景全部通过时退出码为 0，
任意一项不通过则以退出码 1 结束，方便接进 CI 或 pre-commit。

分析口径见 app/services/retail_analytics.py 的说明与 README。
"""

import asyncio
import sys
from pathlib import Path

# 直接运行时 sys.path[0] 是 scripts/，这里补上 backend/ 才能 import app
BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from sqlalchemy import func, select, text  # noqa: E402

from app.models.retail import Order  # noqa: E402
from app.repositories.database import dispose_engine, get_engine  # noqa: E402
from app.services.retail_analytics import (  # noqa: E402
    AVERAGE_ORDER_VALUE_SQL,
    MEMBER_REPURCHASE_SQL,
    MONTHLY_TREND_SQL,
    PRODUCT_RANKING_SQL,
    REGION_SALES_SQL,
    CheckResult,
    check_average_order_value,
    check_member_repurchase,
    check_monthly_trend,
    check_order_volume,
    check_product_ranking,
    check_region_sales,
)
from app.services.retail_seed import HOT_PRODUCT_IDS  # noqa: E402


async def _fetch(conn, sql: str):
    result = await conn.execute(text(sql))
    return [dict(row) for row in result.mappings().all()]


async def collect_checks() -> list[CheckResult]:
    """跑完全部只读查询与校验。"""
    engine = get_engine()
    async with engine.connect() as conn:
        monthly_rows = await _fetch(conn, MONTHLY_TREND_SQL)
        product_rows = await _fetch(conn, PRODUCT_RANKING_SQL)
        region_rows = await _fetch(conn, REGION_SALES_SQL)
        member_rows = await _fetch(conn, MEMBER_REPURCHASE_SQL)
        aov_rows = await _fetch(conn, AVERAGE_ORDER_VALUE_SQL)
        total_orders = await conn.scalar(select(func.count()).select_from(Order))

    return [
        check_order_volume(total_orders),
        check_monthly_trend(monthly_rows),
        check_product_ranking(product_rows, HOT_PRODUCT_IDS),
        check_region_sales(region_rows),
        check_member_repurchase(member_rows),
        check_average_order_value(aov_rows),
    ]


def print_report(checks: list[CheckResult]) -> None:
    for index, check in enumerate(checks, start=1):
        flag = "通过" if check.passed else "不通过"
        print(f"\n[{index}] {check.name} —— {flag}")
        print(f"    {check.summary}")
        for line in check.evidence:
            print(f"      {line}")


async def main() -> int:
    try:
        checks = await collect_checks()
    finally:
        await dispose_engine()

    print("=" * 60)
    print("零售样例数据验证报告")
    print("=" * 60)
    print_report(checks)

    failed = [check for check in checks if not check.passed]
    print("\n" + "=" * 60)
    if failed:
        print(f"验证失败：{len(failed)}/{len(checks)} 项未通过 -> {[c.name for c in failed]}")
        return 1

    print(f"验证通过：{len(checks)}/{len(checks)} 项业务规律全部满足。")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
