"""模拟资产目录：智能问数 Agent 的「知识层」。

本文件里登记的指标和数据集是**人工维护的受控清单**，不是从 ORM 模型自动推导的。
真实数仓表（orders / customers / products / regions / date_dim）已经由 Alembic 迁移
建出、并由种子脚本写入样例数据，模型定义在 app/models/retail.py。

为什么不让它自动从模型推导？和 services/safe_query.py 的理由一致：自动推导意味着
给某张表加一个字段，它会立刻对所有下游可见。显式登记强迫每次扩权都经过一次有意识的
修改。代价是登记内容可能与模型脱节——所以这里登记的每个表名、字段名、枚举值都必须
能在 app/models/retail.py 里找到对应物，测试
test_catalog_fields_all_exist_in_models 会守住这条约束。

**字段名写错在这里是硬故障，不是文案瑕疵。** 本文件的 fields 同时被两处当白名单用：
- sql_generation.py：拼进 Prompt，决定模型「以为」有哪些字段可写；
- sql_validation.py：校验 AST 时用它判断列名是否存在。
而真正执行前还有第二道白名单 services/safe_query.ALLOWED_COLUMNS。两道白名单一旦不一致，
就会出现「catalog 放行、safe_query 拒绝」或反过来的死局——正确写法被判违规、错误写法
放到最后一步才报未授权，Agent 永远答不出那类问题。

本文件是纯常量 + 纯函数：不访问文件系统、数据库、网络和环境变量。
所以它可以被任何模块安全导入，测试时也不需要任何额外条件。

目录里为什么要有 keywords 字段？
真实的资产检索会靠 Embedding / 向量库做语义匹配。本阶段不引入这些依赖，
就用「中文关键词命中」来模拟同样的效果：keywords 相当于一个手工维护的
检索词表，覆盖业务同学实际会说的各种叫法。这是有意做的简化，
等以后接入向量检索时，keywords 可以直接退化成同义词表继续发挥作用。

匹配规则只有一条：**命中了才返回，没命中就返回空列表**。
绝不根据问题去猜测或拼装目录里没有的资产——猜测出来的指标名交给下游
生成 SQL，会直接变成查不存在的表、不存在的列。
"""

from typing import Literal, TypedDict

from app.agent.data_query.state import MatchedAsset


class MetricSpec(TypedDict):
    """一个指标的定义。指标是「业务口径」，不是物理表。"""

    kind: Literal["metric"]
    name: str  # 内部名，后续 SQL 生成按这个名字找口径
    display_name: str  # 中文名，给用户看
    definition: str  # 业务口径说明
    formula: str  # 计算公式，后续生成 SQL 的主要依据
    supported_dimensions: tuple[str, ...]  # 支持按哪些维度下钻
    keywords: tuple[str, ...]  # 检索词表，用于中文关键词匹配


class DatasetSpec(TypedDict):
    """一个数据集（物理表）的定义。字段是「字段名 -> 中文说明」。"""

    kind: Literal["dataset"]
    name: str
    display_name: str
    description: str
    fields: dict[str, str]
    keywords: tuple[str, ...]


# --------------------------------------------------------------------------
# 指标目录
# --------------------------------------------------------------------------

METRICS: tuple[MetricSpec, ...] = (
    {
        "kind": "metric",
        "name": "sales_amount",
        "display_name": "销售额",
        "definition": "统计周期内所有订单明细的实付金额之和，反映整体营收规模。",
        "formula": "SUM(orders.net_amount)",
        "supported_dimensions": ("日期", "区域", "商品", "客户会员等级"),
        "keywords": ("销售额", "销售金额", "销售收入", "营业额", "gmv", "实付金额"),
    },
    {
        "kind": "metric",
        "name": "order_count",
        "display_name": "订单数",
        "definition": "统计周期内的订单笔数，同一个订单号只记一次，反映交易频次。",
        "formula": "COUNT(DISTINCT orders.order_no)",
        "supported_dimensions": ("日期", "区域", "商品", "客户会员等级"),
        "keywords": ("订单数", "订单量", "订单数量", "订单笔数", "单量", "交易笔数"),
    },
    {
        "kind": "metric",
        "name": "average_order_value",
        "display_name": "客单价",
        "definition": "平均每笔订单的实付金额，等于销售额除以订单数，反映单笔交易价值。",
        "formula": "SUM(orders.net_amount) / COUNT(DISTINCT orders.order_no)",
        "supported_dimensions": ("日期", "区域", "客户会员等级"),
        "keywords": ("客单价", "笔单价", "平均订单金额", "单笔金额", "客单"),
    },
    {
        "kind": "metric",
        "name": "repurchase_rate",
        "display_name": "复购率",
        "definition": "统计周期内下单次数大于 1 的客户数占全部下单客户数的比例，反映客户粘性。",
        "formula": "COUNT(下单次数 > 1 的客户) / COUNT(DISTINCT orders.customer_id)",
        "supported_dimensions": ("日期", "区域", "客户会员等级"),
        "keywords": ("复购率", "复购", "重复购买率", "回购率", "二次购买"),
    },
)


# --------------------------------------------------------------------------
# 数据集目录
# --------------------------------------------------------------------------
# 字段用 dict[str, str]（字段名 -> 中文说明）而不是嵌套结构：
# 本阶段只要「有哪些字段、分别是什么意思」，够下游生成 SQL 时选列即可。
# 等真的建表后需要补数据类型、主外键时再升级结构。

DATASETS: tuple[DatasetSpec, ...] = (
    {
        "kind": "dataset",
        "name": "orders",
        "display_name": "订单明细",
        "description": "一行一条订单商品行，是销售额、订单数、客单价、复购率等指标的主要来源表。",
        "fields": {
            "order_no": "订单号，全表唯一；一行订单记录对应一笔订单，订单数用 COUNT(DISTINCT order_no) 统计",
            "date_id": "下单日期，关联 date_dim.date_id",
            "customer_id": "客户 ID，关联 customers.customer_id",
            "product_id": "商品 ID，关联 products.product_id",
            "region_id": "销售区域 ID，关联 regions.region_id",
            "quantity": "购买数量",
            "net_amount": "实付金额，已扣除优惠",
        },
        "keywords": (
            "订单",
            "订单明细",
            "销售额",
            "客单价",
            "复购",
            "购买",
            "下单",
            "交易",
            "销量",
        ),
    },
    {
        "kind": "dataset",
        "name": "customers",
        "display_name": "客户",
        "description": "客户主数据，提供会员等级等客户属性，用于按会员分层分析和复购计算。",
        "fields": {
            "customer_id": "客户 ID，关联 orders.customer_id",
            "member_level": "会员等级，取值仅四种：普通会员、银卡会员、金卡会员、黑金会员",
        },
        "keywords": ("客户", "会员", "用户", "复购", "会员等级", "等级"),
    },
    {
        "kind": "dataset",
        "name": "products",
        "display_name": "商品",
        "description": "商品主数据，提供商品名称和品类，用于商品维度的排行与下钻分析。",
        "fields": {
            "product_id": "商品 ID，关联 orders.product_id",
            "product_name": "商品名称",
            "category_name": "商品品类，例如家用电器、数码配件、厨房用品、服饰鞋帽、美妆个护、食品饮料",
        },
        "keywords": ("商品", "产品", "品类", "类目", "销量", "单品"),
    },
    {
        "kind": "dataset",
        "name": "regions",
        "display_name": "区域",
        "description": "销售区域主数据，提供大区名称，用于地区维度分析。",
        "fields": {
            "region_id": "区域 ID，关联 orders.region_id",
            "region_name": "区域名称，例如华东、华南、华北、华中",
        },
        "keywords": ("区域", "地区", "大区", "省份", "城市", "华东", "华南", "华北"),
    },
    {
        "kind": "dataset",
        "name": "date_dim",
        "display_name": "日期维度",
        "description": "日期维度表，用于把下单日期换算成年、季度、月，支撑时间趋势分析。",
        "fields": {
            "date_id": "日期 ID，主键，采用 YYYYMMDD 整数格式，关联 orders.date_id",
            "full_date": "具体日期",
            "year": "年份",
            "month": "月份",
            "quarter": "季度",
        },
        "keywords": ("日期", "时间", "月", "月份", "季度", "年", "趋势", "近六个月", "同比", "环比"),
    },
)


# --------------------------------------------------------------------------
# 纯函数：关键词匹配
# --------------------------------------------------------------------------


def match_keywords(keywords: tuple[str, ...], text: str) -> list[str]:
    """返回 text 里命中的关键词（保持 keywords 的登记顺序）。

    统一转小写是为了让 "GMV" / "gmv" 都能命中；中文不受影响。
    """
    lowered = text.lower()
    return [kw for kw in keywords if kw.lower() in lowered]


def search_metrics_in_catalog(query: str) -> list[MatchedAsset]:
    """在 METRICS 里按关键词检索，返回命中的指标（保持目录登记顺序）。"""
    text = (query or "").strip()
    if not text:
        return []

    hits: list[MatchedAsset] = []
    for metric in METRICS:
        matched = match_keywords(metric["keywords"], text)
        if matched:
            hits.append(
                {
                    "kind": "metric",
                    "name": metric["name"],
                    "reason": f"问题包含「{'、'.join(matched)}」，匹配「{metric['display_name']}」指标",
                }
            )
    return hits


def search_datasets_in_catalog(query: str) -> list[MatchedAsset]:
    """在 DATASETS 里按关键词检索，返回命中的数据集（保持目录登记顺序）。"""
    text = (query or "").strip()
    if not text:
        return []

    hits: list[MatchedAsset] = []
    for dataset in DATASETS:
        matched = match_keywords(dataset["keywords"], text)
        if matched:
            hits.append(
                {
                    "kind": "dataset",
                    "name": dataset["name"],
                    "reason": f"问题包含「{'、'.join(matched)}」，匹配「{dataset['display_name']}」数据集",
                }
            )
    return hits
