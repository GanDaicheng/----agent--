/**
 * 未来数据服务接口的类型边界。
 *
 * 阶段 1 不发起任何网络请求：这里只声明前端将来需要的数据形状，
 * 供后续接入 FastAPI 数据服务时对照实现，因此只有类型、没有运行时代码。
 *
 * 约定：真实接口就绪后返回这些结构；在此之前页面一律使用
 * src/mocks/ 下的静态数据，并明确标注为静态配置数据。
 */

/** 数仓分层编码，与数据仓库模块的分层说明保持一致。 */
export type WarehouseLayerCode = "ODS" | "DWD" | "DWS" | "ADS";

export type WarehouseLayer = {
  code: WarehouseLayerCode;
  name: string;
  /** 该层已建立的表数量。 */
  tableCount: number;
};

export type MetricSummary = {
  code: string;
  name: string;
  unit: string;
  /** 指标口径说明。 */
  definition: string;
};

/** 服务与数据库的可用状态，用于顶栏「环境状态」展示。 */
export type ServiceHealth = "unknown" | "up" | "down";

export type PlatformHealth = {
  backend: ServiceHealth;
  database: ServiceHealth;
};
