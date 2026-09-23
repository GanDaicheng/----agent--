# 零售样例数仓数据字典

> 文档类型：数据字典
> 适用范围：零售样例数仓
> 使用对象：数据分析、智能问数 Agent、取数开发

## 1. 数据模型总览

零售样例数仓采用「一张事实表 + 四张维度表」的星型结构，共五张表：

| 表名 | 类型 | 说明 |
| --- | --- | --- |
| `orders` | 订单事实表 | 订单商品行明细，所有销售类指标的来源 |
| `customers` | 客户维表 | 客户属性，含会员等级 |
| `products` | 商品维表 | 商品属性，含品类与单价 |
| `regions` | 区域维表 | 销售区域属性 |
| `date_dim` | 日期维表 | 日期属性，支持年 / 季度 / 月 / 周分析 |

四张维度表描述「谁、买了什么、在哪里、什么时候」，事实表 `orders` 记录「发生了多少交易」。数仓中不存储任何预先聚合的汇总结果，月度、区域、商品、会员等所有汇总均通过 SQL 在查询时现场计算，以保证分析口径可追溯、可调整。

当前样例数据的时间范围为 2025 全年，客户约 240 位，订单规模在三千笔以上。

## 2. customers 客户维表

记录客户主数据，是会员分析的基础。

| 字段 | 含义 |
| --- | --- |
| `customer_id` | 客户 ID，主键，订单通过该字段关联到客户 |
| `customer_name` | 客户名称，样例数据中为占位名称 |
| `member_level` | 会员等级，取值受约束，仅允许固定几档 |
| `registered_at` | 客户注册日期，可用于分析客户存续时长 |
| `created_at` | 记录写入时间，属于技术字段 |

`member_level` 的合法取值由数据库约束限定，任何分析中出现的等级名称都应与该字段的实际取值保持一致，不允许使用未登记的等级名称做筛选条件。

## 3. products 商品维表

记录商品主数据，用于商品维度与品类维度的下钻分析。

| 字段 | 含义 |
| --- | --- |
| `product_id` | 商品 ID，主键 |
| `product_name` | 商品名称 |
| `category_name` | 商品品类，商品分析的主要分组字段 |
| `unit_price` | 商品标准单价，取值必须为正 |
| `created_at` | 记录写入时间，属于技术字段 |

商品分析通常按 `category_name` 分组，或按 `product_id` 做单品排行。需要注意 `products.unit_price` 是商品的标准单价，而 `orders` 表中也保存了一份下单时的 `unit_price`，两者含义不同，金额计算应使用订单表上的单价。

## 4. regions 区域维表

记录销售区域主数据。

| 字段 | 含义 |
| --- | --- |
| `region_id` | 区域 ID，主键 |
| `region_name` | 区域名称，唯一 |
| `region_level` | 区域层级，样例数据中为大区 |
| `created_at` | 记录写入时间，属于技术字段 |

区域维表的数据量固定且很小，每个区域一条记录。区域销售额、区域订单数等指标均由 `orders` 按 `region_id` 关联本表后汇总得出。

## 5. date_dim 日期维表

日期维表把下单日期换算成便于分析的层级属性，是时间趋势分析的基础。

| 字段 | 含义 |
| --- | --- |
| `date_id` | 日期 ID，主键，采用 YYYYMMDD 整数格式 |
| `full_date` | 完整日期 |
| `year` | 年份 |
| `quarter` | 季度，取值 1 至 4 |
| `month` | 月份，取值 1 至 12 |
| `month_name` | 月份中文名，如「11月」 |
| `day_of_month` | 当月第几天 |
| `week_of_year` | 当年第几周 |
| `is_weekend` | 是否周末 |

`date_id` 采用 YYYYMMDD 整数格式，使得按年月排序和切片可以直接在数值上完成，不需要额外的日期函数转换。时间趋势分析统一通过 `orders.date_id` 关联本表，再按 `year`、`quarter`、`month` 分组。

## 6. orders 订单事实表

`orders` 是**订单事实表**，一行记录对应一个订单中的一个商品。所有销售类指标都以本表为唯一数据来源。

| 字段 | 含义 |
| --- | --- |
| `order_id` | 自增主键，技术字段，业务分析中一般不使用 |
| `order_no` | 订单号，唯一，订单笔数统计的依据 |
| `customer_id` | 客户 ID，关联 `customers.customer_id` |
| `product_id` | 商品 ID，关联 `products.product_id` |
| `region_id` | 销售区域 ID，关联 `regions.region_id` |
| `date_id` | 下单日期 ID，关联 `date_dim.date_id` |
| `quantity` | 购买数量，必须大于 0 |
| `unit_price` | 下单时单价 |
| `gross_amount` | 应收金额 |
| `discount_amount` | 折扣金额 |
| `net_amount` | 实付金额 |

金额字段之间存在数据库层强制保证的约束关系：`quantity > 0`、`discount_amount <= gross_amount`、`net_amount = gross_amount - discount_amount`。这三个金额字段是原始记录而非聚合结果，冗余存储的目的是让分析口径在查询语句中直接可读。

销售额指标使用 `net_amount`；订单数指标使用去重后的 `order_no`。

## 7. 表关联关系

`orders` 位于模型中心，通过四个外键分别关联四张维度表：

- `orders.customer_id` → `customers.customer_id`：用于按会员等级等客户属性分析
- `orders.product_id` → `products.product_id`：用于按商品与品类分析
- `orders.region_id` → `regions.region_id`：用于按区域分析
- `orders.date_id` → `date_dim.date_id`：用于按时间维度分析

**订单分析通常通过 `orders` 关联维表完成**：以 `orders` 为驱动表，按分析主题 JOIN 对应的维表，再按维表字段分组汇总。销售额、订单数、客单价、复购率等全部指标都遵循这一模式。维表之间不存在直接关联关系，跨维度分析需要通过 `orders` 中转。

## 8. 字段命名与使用约定

- 事实表金额字段统一以 `_amount` 结尾，`gross` 表示应收、`discount` 表示折扣、`net` 表示实付。
- 金额字段使用精确数值类型存储，累加计算不会产生浮点偏差，因此可以直接参与汇总与比较。
- 各表均包含 `created_at` 技术字段，仅用于数据写入审计，不参与业务分析。
- 外键字段统一以 `_id` 结尾，与所关联维表的主键同名，便于识别关联关系。
