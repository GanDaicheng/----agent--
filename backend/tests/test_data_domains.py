"""数据领域登记的测试。

这些断言守住的是「跨领域查询会被拦下」这条规则能不能长期成立：
登记表与 ORM 模型脱节、或者某个领域的表被漏登记，症状都是
「一条本该被拒的 SQL 悄悄跑通了」，而它返回的数字看起来完全正常。
"""

import pytest

from app.models import Base
from app.models.tmall import GOLD_TABLES, SILVER_TABLES
from app.services.data_domains import (
    DOMAIN_LABELS,
    DOMAIN_RETAIL,
    DOMAIN_TMALL,
    RETAIL_TABLES,
    TABLE_DOMAIN,
    TMALL_TABLES,
    cross_domain_violation,
    describe_domains,
    domain_of,
    domains_in,
)

TMALL_MODEL_TABLES = (
    {name for name, _ in SILVER_TABLES}
    | {name for name, _ in GOLD_TABLES}
    | {"tmall_ingestion_runs"}
)


def test_every_registered_table_exists_in_the_models():
    """登记了模型里不存在的表，等于给自己一条永远查不到东西的路径。"""
    for name in TABLE_DOMAIN:
        assert name in Base.metadata.tables, f"登记了不存在的表：{name}"


def test_tmall_registry_matches_the_tmall_models_exactly():
    """天猫领域的登记必须覆盖**全部** tmall_* 表，一张不漏。

    漏掉明细表的话，`orders JOIN tmall_user_events` 会被当成
    「未知表 + 零售表」——跨领域规则不触发，只报一个未授权表名，
    提示方向完全错了。
    """
    assert TMALL_TABLES == TMALL_MODEL_TABLES


def test_retail_registry_matches_the_retail_models():
    retail_model_tables = {
        name for name in Base.metadata.tables if not name.startswith("tmall")
    } - {"knowledge_documents", "knowledge_chunks"}
    assert RETAIL_TABLES == retail_model_tables


def test_the_two_domains_do_not_overlap():
    assert not (RETAIL_TABLES & TMALL_TABLES)


def test_every_model_table_belongs_to_exactly_one_domain():
    """所有业务表都必须有归属。

    没有归属的表在跨领域判断里是「透明」的：它和任何表 JOIN 都不会
    触发规则。新加一张表却忘了登记，就会留下这样一个缺口。
    """
    business_tables = {
        name
        for name in Base.metadata.tables
        if name not in {"knowledge_documents", "knowledge_chunks"}
    }
    assert set(TABLE_DOMAIN) == business_tables


def test_domain_of_is_case_insensitive_and_tolerates_padding():
    assert domain_of("Orders") == DOMAIN_RETAIL
    assert domain_of("  tmall_users  ") == DOMAIN_TMALL


def test_domain_of_returns_none_for_unknown_tables():
    assert domain_of("pg_catalog") is None
    assert domain_of("") is None
    assert domain_of("users") is None


def test_domains_in_ignores_unknown_tables():
    assert domains_in(["orders", "who_knows"]) == frozenset({DOMAIN_RETAIL})


def test_cross_domain_violation_is_none_within_one_domain():
    assert cross_domain_violation(["orders", "customers"]) is None
    assert cross_domain_violation(["tmall_daily_metrics", "tmall_funnel_metrics"]) is None


def test_cross_domain_violation_is_none_for_an_empty_query():
    assert cross_domain_violation([]) is None


def test_cross_domain_violation_detects_mixing_orders_with_tmall_metrics():
    """这张 SQL 里两张表**都在**白名单内，语法完全合法。

    它算出来的数字把 2014 年的行为记录和 2025 年的订单金额连在一起，
    没有业务含义，而且不会报任何错——这正是必须显式禁止跨领域的原因。
    """
    violation = cross_domain_violation(["orders", "tmall_user_metrics"])
    assert violation == (DOMAIN_RETAIL, DOMAIN_TMALL)


def test_cross_domain_violation_detects_tmall_detail_against_retail():
    assert cross_domain_violation(["tmall_user_events", "products"]) is not None


def test_cross_domain_violation_order_is_stable():
    """提示里的领域顺序必须稳定，否则同一条 SQL 两次报错文案不一样。"""
    forward = cross_domain_violation(["orders", "tmall_daily_metrics"])
    backward = cross_domain_violation(["tmall_daily_metrics", "orders"])
    assert forward == backward == (DOMAIN_RETAIL, DOMAIN_TMALL)


def test_describe_domains_produces_chinese_labels():
    text = describe_domains((DOMAIN_RETAIL, DOMAIN_TMALL))
    assert "零售" in text and "天猫" in text


def test_domain_labels_cover_both_domains():
    assert set(DOMAIN_LABELS) == {DOMAIN_RETAIL, DOMAIN_TMALL}


@pytest.mark.parametrize("domain", [DOMAIN_RETAIL, DOMAIN_TMALL])
def test_domain_names_are_stable_lowercase_slugs(domain):
    """领域名是要写进提示、日志和测试的字面量，不能随手改。"""
    assert domain == domain.lower()
    assert domain.isascii()
