"""样例数据生成规则的测试。

全部基于内存中的生成结果，不连数据库。核心要证明两件事：
1. 生成过程是确定性的（同参数永远同样结果，幂等才有基础）；
2. 任务书要求的业务规律确实由生成规则产生，而不是事后手工改数。
"""

import re
from collections import Counter, defaultdict
from decimal import Decimal

import pytest

from app.models.retail import MEMBER_LEVELS
from app.services.retail_seed import (
    HOT_PRODUCT_IDS,
    REPEAT_PROBABILITY,
    SeedDataSet,
    build_seed_dataset,
    compute_amounts,
    repeat_customer_rate,
)

CUSTOMER_NAME_PATTERN = re.compile(r"^样例客户\d{4}$")


@pytest.fixture(scope="module")
def dataset() -> SeedDataSet:
    """整套样例数据只构建一次，模块内共享。"""
    return build_seed_dataset()


def _net_sales_by(key: str, orders) -> dict[str, Decimal]:
    totals: dict[str, Decimal] = defaultdict(Decimal)
    for order in orders:
        totals[order[key]] += order["net_amount"]
    return dict(totals)


def _net_sales_by_month(orders) -> dict[int, Decimal]:
    totals: dict[int, Decimal] = defaultdict(Decimal)
    for order in orders:
        totals[int(str(order["date_id"])[4:6])] += order["net_amount"]
    return dict(totals)


# --------------------------------------------------------------------------
# 确定性
# --------------------------------------------------------------------------


def test_generation_is_deterministic():
    """两次构建必须完全一致，否则 seed 脚本无法幂等。"""
    first = build_seed_dataset()
    second = build_seed_dataset()

    assert first.customers == second.customers
    assert first.products == second.products
    assert first.regions == second.regions
    assert first.date_dim == second.date_dim
    assert first.orders == second.orders


def test_order_numbers_are_unique():
    orders = build_seed_dataset().orders
    numbers = [order["order_no"] for order in orders]
    assert len(numbers) == len(set(numbers))


# --------------------------------------------------------------------------
# 规模
# --------------------------------------------------------------------------


def test_dataset_meets_minimum_scale(dataset):
    assert len(dataset.customers) >= 200
    assert len(dataset.products) >= 20
    assert len(dataset.regions) == 4
    assert len(dataset.date_dim) == 365
    assert len(dataset.orders) >= 3000


def test_products_span_multiple_categories(dataset):
    categories = {product["category_name"] for product in dataset.products}
    assert len(categories) >= 5


def test_all_four_member_levels_appear(dataset):
    levels = Counter(customer["member_level"] for customer in dataset.customers)
    assert set(levels) == set(MEMBER_LEVELS)
    assert all(count > 0 for count in levels.values())


# --------------------------------------------------------------------------
# 维度表完整性
# --------------------------------------------------------------------------


def test_date_dim_covers_a_full_year_one_to_one(dataset):
    rows = dataset.date_dim
    assert min(row["full_date"] for row in rows).isoformat() == "2025-01-01"
    assert max(row["full_date"] for row in rows).isoformat() == "2025-12-31"

    # date_id 与 full_date 一一对应
    assert len({row["date_id"] for row in rows}) == len(rows)
    assert len({row["full_date"] for row in rows}) == len(rows)
    for row in rows:
        assert row["date_id"] == int(row["full_date"].strftime("%Y%m%d"))
        assert row["is_weekend"] == (row["full_date"].weekday() >= 5)


def test_region_names_are_unique(dataset):
    names = [region["region_name"] for region in dataset.regions]
    # 用集合比较：中文按码位排序的结果不是业务顺序，这里只关心「四个区域各出现一次」
    assert set(names) == {"华东", "华南", "华北", "华中"}
    assert len(names) == len(set(names))


def test_every_order_references_existing_dimension_rows(dataset):
    customer_ids = {customer["customer_id"] for customer in dataset.customers}
    product_ids = {product["product_id"] for product in dataset.products}
    region_ids = {region["region_id"] for region in dataset.regions}
    date_ids = {row["date_id"] for row in dataset.date_dim}

    for order in dataset.orders:
        assert order["customer_id"] in customer_ids
        assert order["product_id"] in product_ids
        assert order["region_id"] in region_ids
        assert order["date_id"] in date_ids


# --------------------------------------------------------------------------
# 金额口径
# --------------------------------------------------------------------------


def test_compute_amounts_follows_the_documented_formula():
    gross, discount, net = compute_amounts(
        quantity=3, unit_price=Decimal("299.00"), discount_rate=Decimal("0.10")
    )
    assert gross == Decimal("897.00")
    assert discount == Decimal("89.70")
    assert net == Decimal("807.30")
    assert gross == Decimal("299.00") * 3
    assert net == gross - discount


def test_compute_amounts_rounds_to_cents():
    # 99.99 × 3 = 299.97，15% 折扣 = 44.9955，四舍五入到分应为 45.00
    gross, discount, net = compute_amounts(
        quantity=3, unit_price=Decimal("99.99"), discount_rate=Decimal("0.15")
    )
    assert gross == Decimal("299.97")
    assert discount == Decimal("45.00")
    assert net == Decimal("254.97")


@pytest.mark.parametrize(
    "quantity,unit_price,discount_rate",
    [
        (0, Decimal("10.00"), Decimal("0.1")),
        (-1, Decimal("10.00"), Decimal("0.1")),
        (1, Decimal("-1.00"), Decimal("0.1")),
        (1, Decimal("10.00"), Decimal("-0.1")),
        (1, Decimal("10.00"), Decimal("1.5")),
    ],
)
def test_compute_amounts_rejects_invalid_input(quantity, unit_price, discount_rate):
    with pytest.raises(ValueError):
        compute_amounts(quantity, unit_price, discount_rate)


def test_every_order_amount_is_self_consistent(dataset):
    price_by_product = {
        product["product_id"]: product["unit_price"] for product in dataset.products
    }

    for order in dataset.orders:
        assert order["quantity"] > 0
        # 下单价必须等于商品维表里的价格（下单时点的价格快照）
        assert order["unit_price"] == price_by_product[order["product_id"]]
        assert order["gross_amount"] == order["unit_price"] * order["quantity"]
        assert order["net_amount"] == order["gross_amount"] - order["discount_amount"]
        assert order["discount_amount"] <= order["gross_amount"]
        assert order["discount_amount"] >= 0
        assert order["net_amount"] >= 0


def test_average_order_value_is_positive(dataset):
    total = sum(order["net_amount"] for order in dataset.orders)
    assert total > 0
    assert total / len(dataset.orders) > 0


# --------------------------------------------------------------------------
# 业务规律
# --------------------------------------------------------------------------


def test_orders_exist_in_all_twelve_months(dataset):
    months = Counter(int(str(order["date_id"])[4:6]) for order in dataset.orders)
    assert set(months) == set(range(1, 13))
    assert all(count > 0 for count in months.values())


def test_peak_months_are_clearly_higher_than_normal_months(dataset):
    monthly = _net_sales_by_month(dataset.orders)
    assert len(monthly) == 12

    top_two = sorted(monthly, key=monthly.get, reverse=True)[:2]
    assert set(top_two) == {11, 12}, f"销售额前两名应为 11、12 月，实际为 {top_two}"

    ordered = sorted(monthly.values())
    median = (ordered[5] + ordered[6]) / 2
    for month in (11, 12):
        assert monthly[month] >= median * Decimal("1.3"), f"{month} 月未明显高于普通月份"


def test_top_products_are_the_designated_hot_products(dataset):
    ranking = _net_sales_by("product_id", dataset.orders)
    top_three = [product_id for product_id, _ in
                 sorted(ranking.items(), key=lambda kv: kv[1], reverse=True)[:3]]
    assert set(top_three) == set(HOT_PRODUCT_IDS)


def test_east_china_region_ranks_first(dataset):
    """区域权重设计为 华东 > 华南 > 华北 > 华中，汇总结果必须保持这个次序。"""
    region_names = {region["region_id"]: region["region_name"] for region in dataset.regions}
    by_region = _net_sales_by("region_id", dataset.orders)
    ranked = [region_names[region_id] for region_id, _ in
              sorted(by_region.items(), key=lambda kv: kv[1], reverse=True)]
    assert ranked == ["华东", "华南", "华北", "华中"]


def test_every_region_has_orders(dataset):
    counts = Counter(order["region_id"] for order in dataset.orders)
    assert len(counts) == 4
    assert all(count > 0 for count in counts.values())


def test_repurchase_rate_rises_with_member_level(dataset):
    """复购率口径：订单数 >= 2 的客户数 / 有订单的客户数。"""
    rates = repeat_customer_rate(dataset.customers, dataset.orders)

    assert rates["普通会员"] < rates["银卡会员"] < rates["金卡会员"] < rates["黑金会员"]
    assert rates["金卡会员"] > rates["普通会员"]
    assert rates["黑金会员"] > rates["普通会员"]

    # 分层抽样保证复购率紧贴配置的概率，不会出现「银卡反而高于金卡」的抽样噪声
    for level, expected in REPEAT_PROBABILITY.items():
        assert rates[level] == pytest.approx(expected, abs=0.05)


def test_discount_rate_is_higher_for_premium_members(dataset):
    """等级越高折扣越大，这条规律会体现在平均折扣率上。"""
    level_by_customer = {
        customer["customer_id"]: customer["member_level"] for customer in dataset.customers
    }
    ratio_sums: dict[str, Decimal] = defaultdict(Decimal)
    counts: Counter = Counter()

    for order in dataset.orders:
        if order["gross_amount"] == 0:
            continue
        level = level_by_customer[order["customer_id"]]
        ratio_sums[level] += order["discount_amount"] / order["gross_amount"]
        counts[level] += 1

    average = {level: ratio_sums[level] / counts[level] for level in counts}
    assert average["普通会员"] < average["银卡会员"] < average["金卡会员"] < average["黑金会员"]


# --------------------------------------------------------------------------
# 隐私
# --------------------------------------------------------------------------


def test_customer_names_contain_no_real_personal_information(dataset):
    for customer in dataset.customers:
        assert CUSTOMER_NAME_PATTERN.match(customer["customer_name"]), (
            f"客户名 {customer['customer_name']} 不符合占位名格式，可能引入了真实个人信息"
        )


def test_generated_columns_hold_no_personal_information(dataset):
    """生成的数据里不应出现电话、邮箱、住址这类字段。"""
    forbidden = ("电话", "手机", "邮箱", "@", "身份证", "住址")
    for customer in dataset.customers:
        for value in customer.values():
            text = str(value)
            for keyword in forbidden:
                assert keyword not in text
