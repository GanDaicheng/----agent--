"""领域路由：判断一个问题问的是零售数仓还是天猫数据集。

## 为什么用规则，不让模型选

和 knowledge.py 的 `needs_knowledge` 同一个理由，而且这里更硬：

- **可测试**：规则是纯函数，给定问题就能断言领域，不需要调模型。
  模型判领域的话，同一句话今天 retail 明天 tmall，测试只能写得很宽松。
- **可解释**：命中哪个词能直接写进事件流，排查时一眼看到原因。
- **绝不能判错**：领域判断决定了后面允许查哪些表。判错的后果不是「答得不好」，
  而是「拿天猫的行为数去解释零售的销售额」——一个不会报错的错误答案。
  规则至少是确定的、可审计的。
- **成本**：每个问题少一次模型调用。

代价是规则会漏判。所以默认值放在零售上：漏判的后果是「天猫问题走了零售口径」，
下游会因为查不到匹配资产而给出一句诚实的「没有匹配的数据资产」，
而不是编一个答案。反过来把默认值放在天猫上，就会让所有现有的零售问题
突然找不到资产——那是**破坏性**的。

## 跨领域 JOIN 要从这里就开始防

白名单和 SQL 校验都能挡住跨领域查询，但那两道防线都要等到 SQL 写出来才生效。
资产检索是第一道：如果一个问题同时匹配到 `orders` 和 `tmall_daily_metrics`，
模型就有机会把它们写进同一条 SQL。所以 catalog 的检索会按这里判出的领域过滤，
从源头上只给模型看同一个领域的资产。

## 「复购」为什么算共享词，而不是天猫词

需求里把「复购」列为天猫的识别词，但零售目录里也登记了 `repurchase_rate`
（复购率）这个指标，现有的一批零售问题正是靠它命中的。
把「复购」判成天猫，会让那些问题突然查不到资产——这是破坏性改动。

所以「复购」被登记为**共享词**：它本身不决定领域，只在和其他词组合时起作用。
实践上这不影响天猫问题的识别——「天猫的复购」「复购样本的标签分布」
都带有别的天猫词（天猫 / 样本），照样路由到天猫。
"""

from dataclasses import dataclass
from typing import Final

from app.services.data_domains import DOMAIN_RETAIL, DOMAIN_TMALL

# 出现任意一个就足以判定为天猫领域。
#
# 「点击」「加购」「收藏」这三个词是这份数据集独有的动作名——
# 零售数仓里根本没有「加购」这个概念，所以它们是无歧义的强信号。
TMALL_DOMAIN_KEYWORDS: Final[tuple[str, ...]] = (
    "天猫",
    "双十一",
    "点击",
    "加购",
    "收藏",
    "购物车",
    "行为",
    "漏斗",
    "商家",
    "品牌",
    "转化",
    "浏览",
    "用户日志",
    "样本",
    "预测",
)

# 出现任意一个就足以判定为零售领域。
#
# 「销售额」「客单价」「区域」「会员」这些词在天猫数据集里**根本没有对应的字段**
# （没有价格、没有地区、没有会员体系），所以它们同样是无歧义的强信号。
RETAIL_DOMAIN_KEYWORDS: Final[tuple[str, ...]] = (
    "销售额",
    "销售金额",
    "订单",
    "客单价",
    "区域",
    "会员",
    "品类",
    "折扣",
    "促销",
    "库存",
    "毛利",
    "gmv",
    "地区",
    "大区",
    "客户",
    "门店",
)

# 两个领域都成立的词。它们不参与判定，只作为证据记录——
# 写进事件流能让人看懂「为什么判成了这个领域」。
SHARED_DOMAIN_KEYWORDS: Final[tuple[str, ...]] = (
    "复购",
    "回购",
    "重复购买",
    "商品",
    "类目",
)

# 一个信号都没有时的默认领域。**必须是零售**：
# 这是本模块加入之前唯一存在的领域，改默认值等于让所有老问题失效。
DEFAULT_DOMAIN: Final[str] = DOMAIN_RETAIL


@dataclass(frozen=True)
class DomainRouting:
    """领域路由结果。`reason` 是给事件流看的中文说明。"""

    domain: str
    reason: str
    tmall_hits: tuple[str, ...] = ()
    retail_hits: tuple[str, ...] = ()
    shared_hits: tuple[str, ...] = ()

    @property
    def is_tmall(self) -> bool:
        return self.domain == DOMAIN_TMALL


def _match(keywords: tuple[str, ...], text: str) -> tuple[str, ...]:
    lowered = text.lower()
    return tuple(keyword for keyword in keywords if keyword.lower() in lowered)


def route_domain(question: str) -> DomainRouting:
    """把问题路由到某个领域。纯函数，可脱离 Graph 单独测试。

    判定顺序：

    1. 天猫信号有、零售信号没有 → 天猫
    2. 零售信号有、天猫信号没有 → 零售
    3. 两边都有 → 命中多的赢；一样多 → 零售（默认，不引入新行为）
    4. 都没有 → 零售

    第 3 条用「命中数」而不是「先出现的位置」:后者会让
    「销售额和点击量」与「点击量和销售额」路由到不同领域，
    同一类问题得到两个答案，没法解释也没法测。
    """
    text = (question or "").strip()
    if not text:
        return DomainRouting(DEFAULT_DOMAIN, "问题为空，按默认领域处理")

    tmall_hits = _match(TMALL_DOMAIN_KEYWORDS, text)
    retail_hits = _match(RETAIL_DOMAIN_KEYWORDS, text)
    shared_hits = _match(SHARED_DOMAIN_KEYWORDS, text)

    if tmall_hits and not retail_hits:
        return DomainRouting(
            DOMAIN_TMALL,
            f"命中天猫领域关键词「{'、'.join(tmall_hits)}」",
            tmall_hits,
            retail_hits,
            shared_hits,
        )

    if retail_hits and not tmall_hits:
        return DomainRouting(
            DOMAIN_RETAIL,
            f"命中零售领域关键词「{'、'.join(retail_hits)}」",
            tmall_hits,
            retail_hits,
            shared_hits,
        )

    if tmall_hits and retail_hits:
        if len(tmall_hits) > len(retail_hits):
            return DomainRouting(
                DOMAIN_TMALL,
                f"天猫词 {len(tmall_hits)} 个、零售词 {len(retail_hits)} 个，"
                f"按命中更多的判为天猫（{'、'.join(tmall_hits)}）",
                tmall_hits,
                retail_hits,
                shared_hits,
            )
        return DomainRouting(
            DOMAIN_RETAIL,
            f"天猫词 {len(tmall_hits)} 个、零售词 {len(retail_hits)} 个，"
            f"数量不占优，按默认领域处理（{'、'.join(retail_hits)}）",
            tmall_hits,
            retail_hits,
            shared_hits,
        )

    if shared_hits:
        return DomainRouting(
            DOMAIN_RETAIL,
            f"只命中共享词「{'、'.join(shared_hits)}」，按默认领域处理",
            tmall_hits,
            retail_hits,
            shared_hits,
        )

    return DomainRouting(DEFAULT_DOMAIN, "没有命中任何领域关键词，按默认领域处理")


def domain_of_question(question: str) -> str:
    """只要领域名的便捷入口。"""
    return route_domain(question).domain
