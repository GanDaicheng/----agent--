"""领域路由的测试。

这一层判错的代价比别的模块大：领域决定了后面允许查哪些表，
判错的结果不是「答得不好」，而是「拿天猫的行为数去解释零售的销售额」——
一条语法合法、不会报错、数字却毫无意义的结论。
所以每条规则都要有断言，包括「拿不准时默认到哪」。
"""

import pytest

from app.agent.data_query.catalog import (
    METRICS,
    search_datasets_in_catalog,
    search_metrics_in_catalog,
)
from app.agent.data_query.domain import (
    DEFAULT_DOMAIN,
    RETAIL_DOMAIN_KEYWORDS,
    SHARED_DOMAIN_KEYWORDS,
    TMALL_DOMAIN_KEYWORDS,
    domain_of_question,
    route_domain,
)
from app.agent.data_query.sql_validation import validate_sql_draft
from app.services.data_domains import DOMAIN_RETAIL, DOMAIN_TMALL

# 需求里点名要求能识别出天猫的领域词
REQUIRED_TMALL_WORDS = ("双十一", "天猫", "点击", "加购", "收藏", "商家", "类目", "复购")


# --------------------------------------------------------------------------
# 关键词表本身
# --------------------------------------------------------------------------


def test_the_two_decisive_keyword_sets_do_not_overlap():
    """同一个词不能既是天猫的强信号又是零售的强信号。

    重叠的话判定就变成「看哪张表先被遍历到」——同一句话可能得到两个答案，
    而且没法解释也没法测。
    """
    assert not (set(TMALL_DOMAIN_KEYWORDS) & set(RETAIL_DOMAIN_KEYWORDS))


def test_shared_keywords_are_not_in_either_decisive_set():
    """共享词不能出现在任何一边的判定集里，否则它的「共享」是假的。"""
    shared = set(SHARED_DOMAIN_KEYWORDS)
    assert not (shared & set(TMALL_DOMAIN_KEYWORDS))
    assert not (shared & set(RETAIL_DOMAIN_KEYWORDS))


def test_every_required_tmall_word_is_recognised_somewhere():
    """需求点名的天猫词必须都在某张表里登记过。

    「类目」和「复购」被登记为共享词（见 domain.py 的说明），所以这里
    检查的是「出现在两张表的并集里」，而不是「必须出现在天猫表里」。
    """
    registered = set(TMALL_DOMAIN_KEYWORDS) | set(SHARED_DOMAIN_KEYWORDS)
    for word in REQUIRED_TMALL_WORDS:
        assert word in registered, f"需求要求能识别「{word}」，但它没被登记"


def test_default_domain_is_retail():
    """默认值必须是零售。

    本模块加入之前只存在零售领域；把默认值改成天猫，
    等于让所有现有问题突然查不到资产——那是破坏性改动。
    """
    assert DEFAULT_DOMAIN == DOMAIN_RETAIL


# --------------------------------------------------------------------------
# 路由判定
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "question",
    [
        "天猫各个行为环节分别有多少人",
        "双十一期间点击量怎么样",
        "加购和收藏的用户数对比",
        "点击最多的商家是哪个",
        "天猫类目排行",
        "用户行为漏斗是什么样",
    ],
)
def test_tmall_questions_route_to_tmall(question):
    assert domain_of_question(question) == DOMAIN_TMALL


@pytest.mark.parametrize(
    "question",
    [
        "华东地区近六个月销售额趋势怎么样",
        "订单数最多的商品是什么",
        "各区域的客单价对比",
        "黑金会员的复购率是多少",
        "2025 年销售额最高的品类",
    ],
)
def test_retail_questions_route_to_retail(question):
    assert domain_of_question(question) == DOMAIN_RETAIL


def test_a_keyword_hit_is_reported_in_the_reason():
    """reason 要能解释「为什么判成这个领域」——排查时比一个孤零零的 true 有用。"""
    routing = route_domain("天猫点击量趋势")
    assert routing.is_tmall
    assert "天猫" in routing.reason or "点击" in routing.reason


def test_shared_words_alone_do_not_switch_the_domain():
    """只有「复购」时留在零售。

    这是**刻意**的取舍：零售目录里也登记了复购率指标，现有的一批零售问题
    正是靠它命中的。把「复购」判成天猫会让那些问题突然失效。
    真实的天猫复购问题一定还带着别的天猫词（天猫 / 样本 / 标签），
    照样能路由过去——见下面那条测试。
    """
    routing = route_domain("复购率是多少")
    assert routing.domain == DOMAIN_RETAIL
    assert routing.shared_hits == ("复购",)
    assert "共享词" in routing.reason


def test_a_shared_word_plus_a_tmall_word_routes_to_tmall():
    assert domain_of_question("天猫用户的复购样本有多少") == DOMAIN_TMALL


def test_majority_of_hits_wins_when_both_domains_match():
    """两边都有信号时按命中数取胜。

    用「命中数」而不是「先出现的位置」：后者会让
    「销售额和点击量」与「点击量和销售额」路由到不同领域，
    同一类问题得到两个答案。
    """
    # 天猫两个词（点击、加购），零售一个词（销售额）
    assert domain_of_question("点击、加购和销售额的关系") == DOMAIN_TMALL
    # 零售两个词（销售额、订单），天猫一个词（点击）
    assert domain_of_question("销售额和订单的点击来源") == DOMAIN_RETAIL


def test_a_tie_falls_back_to_retail():
    routing = route_domain("销售额与点击")
    assert routing.domain == DOMAIN_RETAIL
    assert routing.tmall_hits and routing.retail_hits


def test_routing_is_symmetric_with_respect_to_word_order():
    assert domain_of_question("销售额和点击量") == domain_of_question("点击量和销售额")


@pytest.mark.parametrize("question", ["", "   ", None])
def test_empty_questions_route_to_the_default(question):
    routing = route_domain(question or "")
    assert routing.domain == DOMAIN_RETAIL


def test_unrecognised_questions_route_to_the_default():
    routing = route_domain("你好呀今天天气不错")
    assert routing.domain == DOMAIN_RETAIL
    assert "没有命中" in routing.reason


def test_routing_is_case_insensitive_for_latin_keywords():
    assert domain_of_question("GMV 是多少") == DOMAIN_RETAIL


def test_routing_result_is_a_frozen_value_object():
    routing = route_domain("天猫点击")
    with pytest.raises(Exception):
        routing.domain = DOMAIN_RETAIL  # type: ignore[misc]


# --------------------------------------------------------------------------
# 路由 → 资产检索的端到端效果
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "question",
    [
        "天猫各个行为环节分别有多少人",
        "双十一期间点击量趋势",
        "点击最多的商家排行",
        "类目加购对比",
    ],
)
def test_tmall_questions_actually_find_tmall_assets(question):
    """路由对了但检索不到资产，等于白路由。

    这条断言把「领域判定」和「资产检索」串起来验证——两边单独测都通过、
    合起来却是空结果，是这类两段式设计最容易出的问题。
    """
    domain = domain_of_question(question)
    assert domain == DOMAIN_TMALL

    metrics = search_metrics_in_catalog(question, domain=domain)
    datasets = search_datasets_in_catalog(question, domain=domain)
    assert metrics or datasets, f"「{question}」在天猫领域里检索不到任何资产"


@pytest.mark.parametrize(
    "question",
    [
        "华东地区近六个月销售额趋势怎么样",
        "订单数最多的商品是什么",
        "各会员等级的复购率",
    ],
)
def test_retail_questions_still_find_retail_assets(question):
    """这是回归保护：加了天猫领域之后，零售问题必须一切照旧。"""
    domain = domain_of_question(question)
    assert domain == DOMAIN_RETAIL

    metrics = search_metrics_in_catalog(question, domain=domain)
    datasets = search_datasets_in_catalog(question, domain=domain)
    assert metrics or datasets, f"「{question}」在零售领域里检索不到任何资产"


def test_every_metric_belongs_to_a_known_domain():
    """目录里的每个资产都要有明确归属，取值只能是两个领域之一。"""
    from app.agent.data_query.catalog import DATASETS

    for asset in (*METRICS, *DATASETS):
        assert asset["domain"] in {DOMAIN_RETAIL, DOMAIN_TMALL}, asset["name"]


# --------------------------------------------------------------------------
# SQL 草稿校验：跨领域是第二道防线
# --------------------------------------------------------------------------
#
# 资产检索已经按领域过滤了，所以正常情况下 matched_assets 里不会同时出现
# 两个领域的表。但校验层不能依赖「上游一定做对了」——它自己必须能拦住
# 跨领域 SQL，否则一旦检索逻辑被改坏、或者将来有人手工构造 matched_assets，
# 那条 SQL 就会一路跑到数据库并且返回一个没有业务含义的数字。


def _asset(name: str, kind: str = "dataset"):
    return {"kind": kind, "name": name, "reason": "测试构造"}


def test_cross_domain_draft_is_rejected_even_when_both_tables_are_in_the_catalog():
    matched = [_asset("orders"), _asset("tmall_daily_metrics")]
    validation = validate_sql_draft(
        "SELECT orders.order_no, tmall_daily_metrics.event_count"
        " FROM orders"
        " JOIN tmall_daily_metrics ON tmall_daily_metrics.metric_date = orders.date_id"
        " LIMIT 10",
        matched,
    )
    assert not validation["passed"]
    assert any("跨领域" in issue for issue in validation["issues"])


def test_cross_domain_issue_names_both_domains():
    """提示要说清楚把哪两个领域连起来了。

    「禁止跨领域查询」用户看不懂；「零售样例数仓 与 天猫 IJCAI 2015 数据集
    的时间范围与业务口径互不通用」能直接指路。
    """
    validation = validate_sql_draft(
        "SELECT orders.order_no, tmall_user_metrics.event_count"
        " FROM orders JOIN tmall_user_metrics"
        " ON tmall_user_metrics.user_id = orders.order_id LIMIT 10",
        [_asset("orders"), _asset("tmall_user_metrics")],
    )
    joined = " ".join(validation["issues"])
    assert "零售" in joined and "天猫" in joined


def test_single_domain_drafts_are_not_flagged():
    retail = validate_sql_draft(
        "SELECT orders.order_no FROM orders"
        " JOIN customers ON customers.customer_id = orders.customer_id LIMIT 10",
        [_asset("orders"), _asset("customers")],
    )
    assert retail["passed"], retail["issues"]

    tmall = validate_sql_draft(
        "SELECT tmall_funnel_metrics.action_type,"
        " tmall_funnel_metrics.user_count"
        " FROM tmall_funnel_metrics LIMIT 10",
        [_asset("tmall_funnel_metrics")],
    )
    assert tmall["passed"], tmall["issues"]


def test_tmall_draft_validates_against_the_catalog_field_list():
    """天猫表的字段名以 catalog 为唯一来源，写错必须在校验层就被发现。"""
    validation = validate_sql_draft(
        "SELECT tmall_funnel_metrics.action_type, tmall_funnel_metrics.event_total"
        " FROM tmall_funnel_metrics LIMIT 10",
        [_asset("tmall_funnel_metrics")],
    )
    assert not validation["passed"]
    assert any("event_total" in issue for issue in validation["issues"])
