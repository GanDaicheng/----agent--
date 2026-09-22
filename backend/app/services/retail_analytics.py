"""零售分析口径与业务规律校验（只读）。

这里只放两样东西：
1. 五类分析场景的只读 SQL（口径写在注释里，和 README 保持一致）；
2. 把 SQL 结果映射成「通过 / 不通过」的纯函数。

纯函数不碰数据库，因此可以在 pytest 里用构造出来的行直接测，
不需要真实 PostgreSQL；scripts/verify_retail_data.py 负责跑 SQL 再调用它们。

本模块不对外提供任何 API，也不被 Agent 使用——智能问数仍然走 mock executor。
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from decimal import Decimal

# 与 app.services.retail_seed 的生成规则一一对应，作为校验金标准
EXPECTED_TOP_REGION = "华东"
PEAK_MONTHS = (11, 12)
PEAK_MIN_MULTIPLIER = 1.3
TOP_PRODUCT_LIMIT = 10
MIN_MONTH_COUNT = 12
MIN_ORDER_COUNT = 3000


@dataclass(frozen=True)
class CheckResult:
    """单个校验项的结果。evidence 是给人看的明细行，失败时用来定位原因。"""

    name: str
    passed: bool
    summary: str
    evidence: list[str] = field(default_factory=list)


# --------------------------------------------------------------------------
# 只读 SQL
# --------------------------------------------------------------------------

# 月度销售趋势：按年月汇总净销售额与订单数
MONTHLY_TREND_SQL = """
SELECT d.year,
       d.month,
       SUM(o.net_amount) AS net_sales,
       COUNT(*)          AS order_count
FROM orders o
JOIN date_dim d ON d.date_id = o.date_id
GROUP BY d.year, d.month
ORDER BY d.year, d.month
"""

# 商品销售排行：按净销售额倒序取前 10
PRODUCT_RANKING_SQL = """
SELECT p.product_id,
       p.product_name,
       p.category_name,
       SUM(o.net_amount) AS net_sales,
       SUM(o.quantity)   AS units_sold
FROM orders o
JOIN products p ON p.product_id = o.product_id
GROUP BY p.product_id, p.product_name, p.category_name
ORDER BY net_sales DESC
LIMIT 10
"""

# 区域销售分析：按区域汇总净销售额与订单数
REGION_SALES_SQL = """
SELECT r.region_id,
       r.region_name,
       SUM(o.net_amount) AS net_sales,
       COUNT(*)          AS order_count
FROM orders o
JOIN regions r ON r.region_id = o.region_id
GROUP BY r.region_id, r.region_name
ORDER BY net_sales DESC
"""

# 会员复购率。
# 口径：复购率 = 统计周期内订单数 >= 2 的客户数 / 该等级有订单的客户数。
# 先按「会员等级 + 客户」聚合出每个客户的订单数，再在第二层统计占比，
# 不能直接对 orders 做 COUNT，否则算出来的是「订单数」而不是「客户数」。
MEMBER_REPURCHASE_SQL = """
WITH per_customer AS (
    SELECT c.member_level,
           o.customer_id,
           COUNT(*) AS order_count
    FROM orders o
    JOIN customers c ON c.customer_id = o.customer_id
    GROUP BY c.member_level, o.customer_id
)
SELECT member_level,
       COUNT(*)                                                      AS customer_count,
       SUM(CASE WHEN order_count >= 2 THEN 1 ELSE 0 END)             AS repeat_customers,
       ROUND(SUM(CASE WHEN order_count >= 2 THEN 1 ELSE 0 END)::numeric
             / COUNT(*), 4)                                          AS repeat_rate
FROM per_customer
GROUP BY member_level
ORDER BY repeat_rate DESC
"""

# 客单价。
# 口径：客单价 = 总净销售额 / 去重订单数。
# 用 COUNT(DISTINCT order_no) 而不是 COUNT(*)，是为了让口径在
# 「一张订单拆成多个商品行」的情况下依然成立。
AVERAGE_ORDER_VALUE_SQL = """
SELECT r.region_name,
       SUM(o.net_amount)                                  AS net_sales,
       COUNT(DISTINCT o.order_no)                         AS order_count,
       ROUND(SUM(o.net_amount) / COUNT(DISTINCT o.order_no), 2) AS avg_order_value
FROM orders o
JOIN regions r ON r.region_id = o.region_id
GROUP BY r.region_name
ORDER BY avg_order_value DESC
"""


# --------------------------------------------------------------------------
# 校验逻辑（纯函数）
# --------------------------------------------------------------------------


def _to_float(value) -> float:
    if isinstance(value, Decimal):
        return float(value)
    return float(value)


def check_monthly_trend(rows: Sequence[Mapping]) -> CheckResult:
    """月度趋势：至少 12 个月，且 11/12 月明显高于普通月份。"""
    evidence = [
        f"{int(row['year'])}-{int(row['month']):02d}  净销售额 {_to_float(row['net_sales']):>12,.2f}"
        f"  订单数 {int(row['order_count']):>5}"
        for row in rows
    ]

    if len(rows) < MIN_MONTH_COUNT:
        return CheckResult(
            "月度销售趋势", False, f"只覆盖 {len(rows)} 个月，少于要求的 {MIN_MONTH_COUNT} 个月", evidence
        )

    # 按 (年, 月) 聚合。只按 month 做键的话，将来数据跨年时同月份会互相覆盖，
    # 校验结果会静默出错。
    by_year_month = {
        (int(row["year"]), int(row["month"])): _to_float(row["net_sales"]) for row in rows
    }
    sales = sorted(by_year_month.values())
    # 中位数用「中间两个月的均值」，月份数为偶数时也成立
    middle = len(sales) // 2
    median = (sales[middle - 1] + sales[middle]) / 2 if len(sales) % 2 == 0 else sales[middle]

    top_two = sorted(by_year_month, key=by_year_month.get, reverse=True)[:2]
    problems: list[str] = []

    if {month for _, month in top_two} != set(PEAK_MONTHS):
        actual = "、".join(f"{year}-{month:02d}" for year, month in top_two)
        problems.append(f"销售额前两名是 {actual}，不是 {list(PEAK_MONTHS)} 月")

    peak_detail_parts: list[str] = []
    for month in PEAK_MONTHS:
        peak_values = [value for (_, row_month), value in by_year_month.items() if row_month == month]
        if not peak_values:
            problems.append(f"缺少 {month} 月数据")
            continue

        peak_value = max(peak_values)
        ratio = peak_value / median if median else 0
        peak_detail_parts.append(f"{month} 月 {peak_value:,.2f}（中位的 {ratio:.2f} 倍）")
        if ratio < PEAK_MIN_MULTIPLIER:
            problems.append(
                f"{month} 月销售额仅为中位月份的 {ratio:.2f} 倍，低于 {PEAK_MIN_MULTIPLIER} 倍"
            )

    if problems:
        return CheckResult("月度销售趋势", False, "；".join(problems), evidence)
    return CheckResult(
        "月度销售趋势",
        True,
        f"覆盖 {len(rows)} 个月，旺季 " + "、".join(peak_detail_parts),
        evidence,
    )


def check_product_ranking(rows: Sequence[Mapping], hot_product_ids: Sequence[str]) -> CheckResult:
    """商品排行：返回 10 行，前三名是规则设定的热销商品，且金额为正。"""
    evidence = [
        f"#{index}  {row['product_id']}  {row['product_name']:<12}"
        f" 净销售额 {_to_float(row['net_sales']):>12,.2f}  销量 {int(row['units_sold']):>5}"
        for index, row in enumerate(rows, start=1)
    ]

    if not rows:
        return CheckResult("商品销售排行", False, "查询没有返回任何商品", evidence)
    if len(rows) < TOP_PRODUCT_LIMIT:
        return CheckResult(
            "商品销售排行", False, f"只返回 {len(rows)} 行，少于要求的 {TOP_PRODUCT_LIMIT} 行", evidence
        )

    non_positive = [row["product_id"] for row in rows if _to_float(row["net_sales"]) <= 0]
    if non_positive:
        return CheckResult("商品销售排行", False, f"以下商品净销售额非正：{non_positive}", evidence)

    actual_top3 = {row["product_id"] for row in rows[:3]}
    expected_top3 = set(hot_product_ids)
    if actual_top3 != expected_top3:
        return CheckResult(
            "商品销售排行",
            False,
            f"前三名是 {sorted(actual_top3)}，与生成规则设定的热销商品 {sorted(expected_top3)} 不一致",
            evidence,
        )

    return CheckResult(
        "商品销售排行",
        True,
        f"Top10 全部为正，前三名正是热销商品 {sorted(expected_top3)}",
        evidence,
    )


def check_region_sales(rows: Sequence[Mapping]) -> CheckResult:
    """区域销售：华东第一，且每个区域都有订单。"""
    evidence = [
        f"{row['region_name']}  净销售额 {_to_float(row['net_sales']):>12,.2f}"
        f"  订单数 {int(row['order_count']):>5}"
        for row in rows
    ]

    if not rows:
        return CheckResult("区域销售分析", False, "查询没有返回任何区域", evidence)

    empty_regions = [row["region_name"] for row in rows if int(row["order_count"]) == 0]
    if empty_regions:
        return CheckResult("区域销售分析", False, f"以下区域没有订单：{empty_regions}", evidence)

    top_region = rows[0]["region_name"]
    if top_region != EXPECTED_TOP_REGION:
        return CheckResult(
            "区域销售分析",
            False,
            f"销售额第一的是 {top_region}，期望是 {EXPECTED_TOP_REGION}",
            evidence,
        )

    return CheckResult(
        "区域销售分析", True, f"{len(rows)} 个区域均有订单，{EXPECTED_TOP_REGION} 销售额排名第一", evidence
    )


def check_member_repurchase(rows: Sequence[Mapping]) -> CheckResult:
    """会员复购率：黑金、金卡高于普通会员。

    复购率 = 订单数 >= 2 的客户数 / 该等级有订单的客户数（见 MEMBER_REPURCHASE_SQL）。
    """
    evidence = [
        f"{row['member_level']}  客户数 {int(row['customer_count']):>4}"
        f"  复购客户 {int(row['repeat_customers']):>4}"
        f"  复购率 {_to_float(row['repeat_rate']):.4f}"
        for row in rows
    ]

    rate_by_level = {row["member_level"]: _to_float(row["repeat_rate"]) for row in rows}
    baseline = rate_by_level.get("普通会员")
    if baseline is None:
        return CheckResult("会员复购率", False, "结果里没有「普通会员」，无法作为对比基准", evidence)

    lower_levels = [level for level in ("金卡会员", "黑金会员") if level not in rate_by_level]
    if lower_levels:
        return CheckResult("会员复购率", False, f"结果里缺少等级：{lower_levels}", evidence)

    not_higher = [
        level
        for level in ("金卡会员", "黑金会员")
        if rate_by_level[level] <= baseline
    ]
    if not_higher:
        detail = "、".join(f"{level} {rate_by_level[level]:.4f}" for level in not_higher)
        return CheckResult(
            "会员复购率",
            False,
            f"以下等级复购率未高于普通会员（{baseline:.4f}）：{detail}",
            evidence,
        )

    return CheckResult(
        "会员复购率",
        True,
        f"普通会员 {baseline:.4f}，金卡 {rate_by_level['金卡会员']:.4f}，"
        f"黑金 {rate_by_level['黑金会员']:.4f}",
        evidence,
    )


def check_average_order_value(rows: Sequence[Mapping]) -> CheckResult:
    """客单价：总净销售额 / 去重订单数，必须为正。"""
    evidence = [
        f"{row['region_name']}  净销售额 {_to_float(row['net_sales']):>12,.2f}"
        f"  订单数 {int(row['order_count']):>5}"
        f"  客单价 {_to_float(row['avg_order_value']):>10,.2f}"
        for row in rows
    ]

    if not rows:
        return CheckResult("客单价", False, "查询没有返回任何区域", evidence)

    non_positive = [row["region_name"] for row in rows if _to_float(row["avg_order_value"]) <= 0]
    if non_positive:
        return CheckResult("客单价", False, f"以下区域客单价非正：{non_positive}", evidence)

    overall = sum(_to_float(row["net_sales"]) for row in rows) / sum(
        int(row["order_count"]) for row in rows
    )
    return CheckResult("客单价", True, f"各区域客单价均为正，全局客单价 {overall:,.2f}", evidence)


def check_order_volume(total_orders: int) -> CheckResult:
    """订单规模：不能少于 3000 行，否则后续分析样本太小。"""
    passed = total_orders >= MIN_ORDER_COUNT
    summary = f"订单共 {total_orders} 行" + ("" if passed else f"，少于要求的 {MIN_ORDER_COUNT} 行")
    return CheckResult("订单规模", passed, summary)
