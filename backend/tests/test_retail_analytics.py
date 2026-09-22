"""验证逻辑的测试。

校验函数被设计成「接收查询结果行、返回通过与否」的纯函数，
所以这里可以喂构造出来的行，验证它既能放过正确数据，也能在规律被破坏时判失败。
这很重要：一个永远返回「通过」的验证脚本等于没有验证。
"""

from decimal import Decimal

import pytest

from app.services.retail_analytics import (
    AVERAGE_ORDER_VALUE_SQL,
    MEMBER_REPURCHASE_SQL,
    MONTHLY_TREND_SQL,
    PRODUCT_RANKING_SQL,
    REGION_SALES_SQL,
    check_average_order_value,
    check_member_repurchase,
    check_monthly_trend,
    check_order_volume,
    check_product_ranking,
    check_region_sales,
)

HOT_PRODUCTS = ("PRD005", "PRD009", "PRD013")

READ_ONLY_SQL = {
    "MONTHLY_TREND_SQL": MONTHLY_TREND_SQL,
    "PRODUCT_RANKING_SQL": PRODUCT_RANKING_SQL,
    "REGION_SALES_SQL": REGION_SALES_SQL,
    "MEMBER_REPURCHASE_SQL": MEMBER_REPURCHASE_SQL,
    "AVERAGE_ORDER_VALUE_SQL": AVERAGE_ORDER_VALUE_SQL,
}

FORBIDDEN_SQL_KEYWORDS = (
    "insert",
    "update",
    "delete",
    "drop",
    "alter",
    "truncate",
    "create",
    "grant",
)


def _monthly_rows(sales_by_month: dict[int, float]) -> list[dict]:
    return [
        {
            "year": 2025,
            "month": month,
            "net_sales": Decimal(str(sales)),
            "order_count": 100,
        }
        for month, sales in sorted(sales_by_month.items())
    ]


# 普通月份约 100，11/12 月明显更高
NORMAL_YEAR = {
    1: 100.0, 2: 95.0, 3: 100.0, 4: 100.0, 5: 105.0, 6: 110.0,
    7: 110.0, 8: 105.0, 9: 100.0, 10: 110.0, 11: 260.0, 12: 300.0,
}


def test_all_analytic_sql_is_read_only():
    """验证脚本只允许查询；出现写操作关键字就说明它可能会改数据。"""
    for name, sql in READ_ONLY_SQL.items():
        normalized = sql.lower()
        assert normalized.lstrip().startswith(("select", "with")), f"{name} 不是查询语句"
        for keyword in FORBIDDEN_SQL_KEYWORDS:
            assert f" {keyword} " not in normalized, f"{name} 含写操作关键字 {keyword}"


# --------------------------------------------------------------------------
# 订单规模
# --------------------------------------------------------------------------


def test_order_volume_passes_at_minimum():
    assert check_order_volume(3000).passed is True


def test_order_volume_fails_below_minimum():
    assert check_order_volume(2999).passed is False


# --------------------------------------------------------------------------
# 月度趋势
# --------------------------------------------------------------------------


def test_monthly_trend_passes_on_peak_december_data():
    result = check_monthly_trend(_monthly_rows(NORMAL_YEAR))
    assert result.passed is True
    assert "12" in result.summary


def test_monthly_trend_fails_when_fewer_than_twelve_months():
    short_year = {month: sales for month, sales in NORMAL_YEAR.items() if month <= 11}
    result = check_monthly_trend(_monthly_rows(short_year))
    assert result.passed is False
    assert "少于" in result.summary


def test_monthly_trend_fails_when_peaks_are_flat():
    flat = dict.fromkeys(range(1, 13), 100.0)
    result = check_monthly_trend(_monthly_rows(flat))
    assert result.passed is False


def test_monthly_trend_fails_when_another_month_outsells_a_peak():
    shifted = dict(NORMAL_YEAR)
    shifted[11] = 260.0
    shifted[12] = 300.0
    shifted[6] = 900.0  # 6 月异常高，旺季不再是前两名
    result = check_monthly_trend(_monthly_rows(shifted))
    assert result.passed is False


# --------------------------------------------------------------------------
# 商品排行
# --------------------------------------------------------------------------


def _product_rows(product_ids: list[str], net_sales: list[float]) -> list[dict]:
    return [
        {
            "product_id": product_id,
            "product_name": f"商品{index}",
            "category_name": "测试品类",
            "net_sales": Decimal(str(sales)),
            "units_sold": 100,
        }
        for index, (product_id, sales) in enumerate(zip(product_ids, net_sales), start=1)
    ]


TOP_TEN_WITH_HOT_FIRST = ["PRD005", "PRD013", "PRD009"] + [f"PRD1{index:02d}" for index in range(1, 8)]


def test_product_ranking_passes_when_hot_products_lead():
    rows = _product_rows(TOP_TEN_WITH_HOT_FIRST, [500, 400, 300] + [100] * 7)
    result = check_product_ranking(rows, HOT_PRODUCTS)
    assert result.passed is True
    assert len(result.evidence) == 10


def test_product_ranking_fails_when_a_hot_product_drops_out_of_top_three():
    product_ids = ["PRD001", "PRD013", "PRD009"] + ["PRD005"] + [f"PRD1{index:02d}" for index in range(2, 8)]
    rows = _product_rows(product_ids, [500, 400, 300, 250] + [100] * 6)
    result = check_product_ranking(rows, HOT_PRODUCTS)
    assert result.passed is False
    assert "前三名" in result.summary


def test_product_ranking_fails_when_fewer_than_ten_rows():
    rows = _product_rows(["PRD005", "PRD013", "PRD009"], [500, 400, 300])
    result = check_product_ranking(rows, HOT_PRODUCTS)
    assert result.passed is False


def test_product_ranking_fails_on_non_positive_sales():
    rows = _product_rows(TOP_TEN_WITH_HOT_FIRST, [500, 400, 300] + [0] * 7)
    result = check_product_ranking(rows, HOT_PRODUCTS)
    assert result.passed is False


# --------------------------------------------------------------------------
# 区域
# --------------------------------------------------------------------------


def _region_rows(rows: list[tuple[str, float, int]]) -> list[dict]:
    return [
        {
            "region_id": f"REG{index:02d}",
            "region_name": name,
            "net_sales": Decimal(str(sales)),
            "order_count": count,
        }
        for index, (name, sales, count) in enumerate(rows, start=1)
    ]


def test_region_sales_passes_when_east_china_leads():
    result = check_region_sales(
        _region_rows([("华东", 900, 100), ("华南", 600, 80), ("华北", 400, 60), ("华中", 300, 50)])
    )
    assert result.passed is True


def test_region_sales_fails_when_east_china_is_not_first():
    result = check_region_sales(
        _region_rows([("华南", 900, 100), ("华东", 600, 80), ("华北", 400, 60), ("华中", 300, 50)])
    )
    assert result.passed is False
    assert "华东" in result.summary


def test_region_sales_fails_when_a_region_has_no_orders():
    result = check_region_sales(
        _region_rows([("华东", 900, 100), ("华南", 600, 80), ("华北", 400, 60), ("华中", 0, 0)])
    )
    assert result.passed is False


# --------------------------------------------------------------------------
# 会员复购率
# --------------------------------------------------------------------------


def _member_rows(rows: list[tuple[str, int, int]]) -> list[dict]:
    return [
        {
            "member_level": level,
            "customer_count": customers,
            "repeat_customers": repeaters,
            "repeat_rate": Decimal(str(round(repeaters / customers, 4))),
        }
        for level, customers, repeaters in rows
    ]


GOOD_MEMBER_ROWS = [
    ("黑金会员", 20, 19),
    ("金卡会员", 40, 34),
    ("银卡会员", 60, 37),
    ("普通会员", 120, 48),
]


def test_member_repurchase_passes_when_premium_members_repeat_more():
    result = check_member_repurchase(_member_rows(GOOD_MEMBER_ROWS))
    assert result.passed is True


def test_member_repurchase_fails_when_gold_is_not_above_ordinary():
    rows = [
        ("黑金会员", 20, 19),
        ("金卡会员", 40, 10),  # 0.25 < 普通会员 0.40
        ("银卡会员", 60, 37),
        ("普通会员", 120, 48),
    ]
    result = check_member_repurchase(_member_rows(rows))
    assert result.passed is False
    assert "金卡会员" in result.summary


def test_member_repurchase_fails_without_an_ordinary_baseline():
    rows = [row for row in GOOD_MEMBER_ROWS if row[0] != "普通会员"]
    result = check_member_repurchase(_member_rows(rows))
    assert result.passed is False
    assert "普通会员" in result.summary


def test_repurchase_definition_requires_two_or_more_orders():
    """复购率口径是「订单数 >= 2 的客户占比」，下单一次不算复购。

    构造一组客户：3 人各下 1 单、1 人下 2 单，复购率应为 1/4。
    """
    per_customer_orders = {"A": 1, "B": 1, "C": 1, "D": 2}
    repeaters = sum(1 for count in per_customer_orders.values() if count >= 2)
    assert repeaters / len(per_customer_orders) == pytest.approx(0.25)


# --------------------------------------------------------------------------
# 客单价
# --------------------------------------------------------------------------


def test_average_order_value_passes_when_positive():
    rows = _region_rows([("华东", 900, 100), ("华南", 600, 80)])
    for row in rows:
        row["avg_order_value"] = row["net_sales"] / row["order_count"]
    result = check_average_order_value(rows)
    assert result.passed is True


def test_average_order_value_fails_when_zero():
    rows = _region_rows([("华东", 0, 100)])
    rows[0]["avg_order_value"] = Decimal("0")
    result = check_average_order_value(rows)
    assert result.passed is False


def test_average_order_value_fails_on_empty_result():
    assert check_average_order_value([]).passed is False
