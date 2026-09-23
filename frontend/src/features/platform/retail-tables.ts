/**
 * 零售样例数据底座的表结构说明。
 *
 * 数据源是 PostgreSQL 里真实存在的五张表，字段名与 app/models/retail.py 一一对应；
 * 行数是实测值（2026-09 通过受控查询接口逐表 COUNT 得到），不是估算。
 *
 * 为什么单独一个文件？数据仓库页要用它渲染表卡片，架构页要用它画 ER 图。
 * 两份页面各写一遍表清单，早晚会出现「一边说 240、一边说 240 条样例」这种漂移。
 *
 * 注意这里是**静态配置**，不是实时统计：页面渲染时必须标明「演示数据」，
 * 不能让人以为这是实时从数据库查出来的数字。
 */

export type RetailTable = {
  /** 物理表名，与数据库一致。 */
  name: string;
  /** 中文职责，例如「客户维度」。 */
  role: string;
  kind: "dimension" | "fact";
  /** 实测行数。 */
  rows: number;
  /** 行数的中文表述，页面直接显示。 */
  rowsLabel: string;
  primaryKey: string;
  /** 关键字段。不列全部列，只列理解这张表所需的那些。 */
  fields: { name: string; desc: string }[];
  /** 这张表在平台里承担什么。 */
  purpose: string;
};

const CUSTOMERS: RetailTable = {
  name: "customers",
  role: "客户维度",
  kind: "dimension",
  rows: 240,
  rowsLabel: "240 条样例数据",
  primaryKey: "customer_id",
  fields: [
    { name: "customer_id", desc: "客户 ID，主键" },
    { name: "member_level", desc: "会员等级：普通 / 银卡 / 金卡 / 黑金" },
    { name: "registered_at", desc: "注册日期" },
  ],
  purpose: "提供会员等级，支撑按会员分层分析与复购计算。",
};

const PRODUCTS: RetailTable = {
  name: "products",
  role: "商品维度",
  kind: "dimension",
  rows: 24,
  rowsLabel: "24 个商品样例",
  primaryKey: "product_id",
  fields: [
    { name: "product_id", desc: "商品 ID，主键" },
    { name: "product_name", desc: "商品名称" },
    { name: "category_name", desc: "品类，共 6 类" },
    { name: "unit_price", desc: "单价，精确小数类型" },
  ],
  purpose: "提供商品与品类，支撑商品排行与品类维度的下钻分析。",
};

const REGIONS: RetailTable = {
  name: "regions",
  role: "区域维度",
  kind: "dimension",
  rows: 4,
  rowsLabel: "4 个区域",
  primaryKey: "region_id",
  fields: [
    { name: "region_id", desc: "区域 ID，主键" },
    { name: "region_name", desc: "华东、华南、华北、华中" },
    { name: "region_level", desc: "区域层级" },
  ],
  purpose: "提供大区名称，支撑地区维度的对比分析。",
};

const DATE_DIM: RetailTable = {
  name: "date_dim",
  role: "日期维度",
  kind: "dimension",
  rows: 365,
  rowsLabel: "覆盖 2025 年全年 365 天",
  primaryKey: "date_id",
  fields: [
    { name: "date_id", desc: "日期 ID，主键，YYYYMMDD 整数" },
    { name: "full_date", desc: "具体日期，2025-01-01 ~ 2025-12-31" },
    { name: "month", desc: "月份" },
    { name: "quarter", desc: "季度" },
    { name: "is_weekend", desc: "是否周末" },
  ],
  purpose: "把下单日期换算成年、季度、月，支撑月度、季度与周末分析。",
};

const ORDERS: RetailTable = {
  name: "orders",
  role: "订单事实表",
  kind: "fact",
  rows: 3404,
  rowsLabel: "3404 条订单明细",
  primaryKey: "order_id",
  fields: [
    { name: "order_no", desc: "订单号，订单数按它去重统计" },
    { name: "customer_id / product_id / region_id / date_id", desc: "四个外键，指向上面四张维度表" },
    { name: "quantity", desc: "购买数量" },
    { name: "gross_amount / discount_amount / net_amount", desc: "应收 / 折扣 / 实付金额" },
  ],
  purpose:
    "保存订单明细的原始粒度。月度、区域、商品和会员等级的汇总全部由 SQL 现场计算，表里不存任何预聚合结果。",
};

/** 四张维度表。ER 图与表卡片都按这个顺序展示。 */
export const RETAIL_DIMENSIONS: RetailTable[] = [
  CUSTOMERS,
  PRODUCTS,
  REGIONS,
  DATE_DIM,
];

/** 唯一的事实表。 */
export const RETAIL_FACT: RetailTable = ORDERS;

/** 五张表，维度在前、事实在后。 */
export const RETAIL_TABLES: RetailTable[] = [...RETAIL_DIMENSIONS, RETAIL_FACT];

/**
 * 表之间的关联关系。
 *
 * ER 图**不能只靠颜色和连线表达关系**——色觉障碍或黑白打印下连线就失效了。
 * 所以每条关系都配一句文字：左边是外键、右边是主键，中间是业务含义。
 */
export type RetailRelation = {
  /** 事实表一侧的字段。 */
  from: string;
  /** 维度表一侧的字段。 */
  to: string;
  /** 这条关联的业务含义。 */
  label: string;
};

export const RETAIL_RELATIONS: RetailRelation[] = [
  {
    from: "orders.customer_id",
    to: "customers.customer_id",
    label: "这笔订单由哪个客户下单",
  },
  {
    from: "orders.product_id",
    to: "products.product_id",
    label: "这笔订单卖的是哪个商品",
  },
  {
    from: "orders.region_id",
    to: "regions.region_id",
    label: "这笔订单发生在哪个区域",
  },
  {
    from: "orders.date_id",
    to: "date_dim.date_id",
    label: "这笔订单在哪一天发生",
  },
];
