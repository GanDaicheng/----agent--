/**
 * 平台总览页的展示数据。
 *
 * 这些全部是前端静态配置，不是来自后端、数据库或 Agent 的实时数据。
 * 页面渲染时必须同时显示 MOCK_NOTICE，避免被误认为真实运行数据。
 *
 * 这里刻意不存放任何「在线人数」「今日调用量」「增长率」这类看起来
 * 像实时指标的数字：阶段 1 没有任何真实的运行时数据源。
 */

import type { SectionId } from "@/features/platform/platform-config";

/** 凡是展示本文件数据的位置都要带上这句话。 */
export const MOCK_NOTICE = "静态配置数据 · 非实时运行数据";

/** 欢迎区右侧的静态状态，不使用任何伪造的实时数字。 */
export const HERO_FACTS = [
  { label: "平台阶段", value: "原型建设中" },
  { label: "核心 Agent", value: "已完成" },
];

/** 分层链路最左侧的来源说明。业务系统不属于平台自身，因此没有建设状态。 */
export const SOURCE_NODE = {
  name: "业务系统",
  duty: "零售门店、电商与仓储等业务系统，是平台的数据来源",
};

/** 各层级的下一步计划。层级名称、状态与说明来自 platform-config，避免重复维护。 */
export const SECTION_NEXT_STEP: Record<SectionId, string> = {
  business: "先建立订单与商品主数据，作为数仓事实与维度的来源。",
  data: "建立 ODS / DWD / DWS / ADS 分层与零售样例数据。",
  ai: "让 Agent 接入真实数据服务与 RAG 知识库，替换模拟资产与模拟查询。",
  applications: "数据服务就绪后，开放经营驾驶舱与智能问数应用入口。",
};

/**
 * 已完成能力清单。文案刻意区分三件事：
 * 已完成的基础设施、已完成的 Agent 原型、以及尚未接入的真实业务数据。
 */
export const COMPLETED_GROUPS = [
  {
    key: "infrastructure",
    title: "已完成 · 基础设施",
    caption: "可以一键启动并自检，但还没有承载业务数据。",
    items: [
      "Docker Compose 三服务（前端 / 后端 / 数据库）一键启动",
      "PostgreSQL 16 容器运行并通过健康检查",
      "FastAPI 服务与数据库连通性检查接口",
      "Next.js + TypeScript 前端工程",
      "核心链路的自动化测试",
    ],
  },
  {
    key: "agent",
    title: "已完成 · 受控智能问数 Agent",
    caption: "流程完整可演示，但查询结果来自模拟数据。",
    items: [
      "LangGraph 受控问数工作流",
      "问题理解与资产发现",
      "SQL 生成与 AST 安全校验",
      "模拟查询执行（非真实数据库查询）",
      "结果解释与图表类型建议",
    ],
  },
  {
    key: "not-yet",
    title: "尚未接入 · 真实业务数据",
    caption: "以下能力目前都不存在，页面中不会展示它们的任何数据。",
    items: [
      "客户、商品、订单、库存真实业务数据",
      "ODS / DWD / DWS / ADS 分层数仓",
      "真实指标口径与指标计算服务",
      "对外数据服务 API",
      "RAG 知识库与 MCP 工具",
      "智能问数前端应用",
    ],
  },
];

/** 推荐下一步：按依赖顺序排列，不写营销话术。 */
export const ROADMAP = [
  {
    step: "建立零售业务核心数据",
    detail: "客户、商品、订单、库存的领域模型与样例数据。",
  },
  {
    step: "建立分层数仓与指标体系",
    detail: "ODS / DWD / DWS / ADS 分层，以及销售额、订单数、客单价、复购率的口径。",
  },
  {
    step: "将 Agent 接入真实数据服务",
    detail: "用数据服务替换模拟资产与模拟查询，安全校验保持不变。",
  },
  {
    step: "接入 RAG 知识库",
    detail: "让 Agent 能检索指标口径与业务文档，提升资产发现准确率。",
  },
  {
    step: "完成经营驾驶舱和智能问数应用",
    detail: "把数据与 AI 能力交付给业务人员使用。",
  },
];
