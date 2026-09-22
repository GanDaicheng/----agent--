/**
 * 平台信息架构的唯一数据源。
 *
 * 所有路由、模块名称、建设状态、能力说明与依赖关系都集中在这里，
 * 页面组件只负责渲染，不再各自硬编码。
 * 修改这里的状态，左侧导航、顶栏标题与模块页会同步更新。
 */

/** 模块建设状态。取值只有这三种，避免出现「部分完成」这类模糊说法。 */
export type ModuleStatus = "done" | "building" | "planned";

export const STATUS_LABEL: Record<ModuleStatus, string> = {
  done: "已完成",
  building: "建设中",
  planned: "待接入",
};

/** 模块页里的一组要点，例如数仓分层、指标目录。 */
export type ModuleBlock = {
  title: string;
  /** 对这组要点的补充说明，用于标明它还不是真实生产数据。 */
  caption?: string;
  items: { name: string; desc: string }[];
};

export type PlatformModule = {
  /** 路由末段，对应 app/<section>/[module] 的 [module]。 */
  slug: string;
  name: string;
  /** 一句职责说明。 */
  summary: string;
  status: ModuleStatus;
  /** 页面顶部的建设边界说明，写清楚「现在没有什么」。 */
  notice?: string;
  blocks?: ModuleBlock[];
  /** 已跑通的处理链路，逐步展示。 */
  workflow?: string[];
  /** 当前能力。 */
  current: string[];
  /** 后续接入内容。 */
  upcoming: string[];
  /** 依赖关系链路。 */
  dependencies: string[];
};

export type SectionId = "business" | "data" | "ai" | "applications";

export type PlatformSection = {
  id: SectionId;
  name: string;
  /** 所属层级的一句话职责，用于总览页的分层链路。 */
  duty: string;
  status: ModuleStatus;
  /** 层级状态的补充说明，避免把部分完成说成全部完成。 */
  statusNote: string;
  /** 总览页点击该层进入的模块入口。 */
  entry: string;
  entryLabel: string;
  modules: PlatformModule[];
};

export const PLATFORM_NAME = "零售企业智能化平台";
export const PLATFORM_TAGLINE =
  "从业务能力、数据资产到 AI 智能应用的一体化建设原型";

const BUSINESS: PlatformSection = {
  id: "business",
  name: "业务中台",
  duty: "统一客户、商品、订单和库存等核心业务能力",
  status: "planned",
  statusNote: "客户、商品、订单、库存模块尚未建立领域模型与数据。",
  entry: "/business/customers",
  entryLabel: "进入客户中心",
  modules: [
    {
      slug: "customers",
      name: "客户中心",
      summary: "统一管理客户档案、会员等级与消费行为标签。",
      status: "planned",
      notice: "尚未建立客户领域模型，也没有真实客户数据。",
      current: [
        "客户主数据、会员等级与标签体系均未建立",
        "平台内没有可查询的真实客户数据",
      ],
      upcoming: [
        "客户主表与会员等级表",
        "客户标签与分群规则",
        "客户维度进入数仓，支撑客户数与复购率指标",
      ],
      dependencies: [
        "客户中心 → 数据采集 → 客户维度表 → 客户数与复购率指标",
      ],
    },
    {
      slug: "products",
      name: "商品中心",
      summary: "统一管理商品、品类、价格与上下架状态。",
      status: "planned",
      notice: "尚未建立商品领域模型，也没有真实商品数据。",
      current: [
        "商品主数据与品类层级未建立",
        "价格与上下架状态没有统一维护入口",
      ],
      upcoming: [
        "商品主表与品类层级表",
        "价格与上下架状态管理",
        "商品维度进入数仓，支撑品类销售额指标",
      ],
      dependencies: [
        "商品中心 → 数据采集 → 商品维度表 → 品类销售额指标",
      ],
    },
    {
      slug: "orders",
      name: "订单中心",
      summary: "统一管理订单、订单明细、支付状态和售后状态。",
      status: "planned",
      notice: "尚未接入订单领域模型和订单数据。",
      current: [
        "订单表与订单明细表未建立",
        "订单状态流转与售后状态没有承载模块",
      ],
      upcoming: [
        "订单表与订单明细表",
        "订单创建和状态流转",
        "订单数据作为数仓的主要事实来源",
      ],
      dependencies: [
        "订单中心 → 数据采集 → 销售事实表 → 销售额与订单数指标",
      ],
    },
    {
      slug: "inventory",
      name: "库存中心",
      summary: "统一管理仓库、库存数量与出入库流水。",
      status: "planned",
      notice: "尚未建立库存领域模型，也没有真实库存数据。",
      current: [
        "仓库与库存表未建立",
        "出入库流水没有记录入口",
      ],
      upcoming: [
        "仓库表与库存表",
        "出入库流水与库存快照",
        "库存数据作为库存周转率指标的数据来源",
      ],
      dependencies: [
        "库存中心 → 数据采集 → 库存事实表 → 库存周转率指标",
      ],
    },
  ],
};

const DATA: PlatformSection = {
  id: "data",
  name: "数据中台",
  duty: "采集、治理、沉淀和服务数据资产",
  status: "building",
  statusNote:
    "PostgreSQL 运行环境已就绪；分层数仓、指标口径与数据服务尚未建立。",
  entry: "/data/warehouse",
  entryLabel: "进入数据仓库",
  modules: [
    {
      slug: "sources",
      name: "数据采集",
      summary: "把业务系统与外部数据源的数据稳定地汇入数据中台。",
      status: "planned",
      notice: "尚无采集任务、调度与数据接入记录。",
      current: [
        "PostgreSQL 16 容器已运行并通过健康检查",
        "采集任务、调度与失败重试机制尚未建立",
      ],
      upcoming: [
        "业务库抽取任务与调度配置",
        "采集任务运行状态与失败重试",
        "数据接入明细与延迟监控",
      ],
      dependencies: ["业务中台（客户 / 商品 / 订单 / 库存）→ 数据采集 → ODS 层"],
    },
    {
      slug: "governance",
      name: "数据治理",
      summary: "定义数据标准、质量规则与元数据，保证数据可信可用。",
      status: "planned",
      notice: "数据标准、质量规则与血缘关系均未建立。",
      current: [
        "尚未定义命名规范与字段标准",
        "没有质量校验规则与稽核结果",
      ],
      upcoming: [
        "数据标准与命名规范",
        "质量校验规则与稽核报告",
        "表级与字段级血缘关系",
      ],
      dependencies: ["数据采集 → 数据治理 → 数据仓库分层建模"],
    },
    {
      slug: "warehouse",
      name: "数据仓库",
      summary: "按 ODS / DWD / DWS / ADS 分层建模，沉淀可复用的数据资产。",
      status: "planned",
      notice:
        "当前 PostgreSQL 已完成运行环境；分层表、迁移和零售样例数据尚未建立。",
      blocks: [
        {
          title: "规划中的分层结构",
          caption: "以下为分层规划，尚未建表，也没有存放数据。",
          items: [
            {
              name: "ODS · 原始数据层",
              desc: "与源系统结构基本一致的落地数据，保留原始明细。",
            },
            {
              name: "DWD · 明细数据层",
              desc: "清洗与标准化后的明细事实表和维度表。",
            },
            {
              name: "DWS · 主题汇总层",
              desc: "按主题聚合的宽表，供指标计算复用。",
            },
            {
              name: "ADS · 应用数据层",
              desc: "面向报表与问数场景的结果表。",
            },
          ],
        },
      ],
      current: [
        "PostgreSQL 16 容器已运行并通过健康检查",
        "后端服务与数据库的连接已打通",
        "分层表结构、迁移脚本与零售样例数据尚未建立",
      ],
      upcoming: [
        "ODS / DWD / DWS / ADS 建表与迁移脚本",
        "零售样例数据（客户、商品、订单、库存）",
        "维度建模与缓慢变化维处理",
      ],
      dependencies: ["数据治理 → 数据仓库分层建模 → 指标中心 → 数据服务"],
    },
    {
      slug: "metrics",
      name: "指标中心",
      summary: "统一管理指标定义、计算口径与可用维度。",
      status: "building",
      notice:
        "当前为 Agent 演示用模拟指标目录；尚未实现真实指标口径管理与计算服务。",
      blocks: [
        {
          title: "演示用模拟指标目录",
          caption:
            "仅用于智能问数 Agent 演示的指标目录，不是真实计算出来的业务数据。",
          items: [
            { name: "销售额", desc: "统计周期内的订单金额合计。" },
            { name: "订单数", desc: "统计周期内的订单笔数。" },
            { name: "客单价", desc: "销售额 ÷ 订单数。" },
            { name: "复购率", desc: "统计周期内重复购买客户占比。" },
          ],
        },
      ],
      current: [
        "Agent 可识别的模拟指标目录：销售额、订单数、客单价、复购率",
        "指标口径尚未落到真实表与计算逻辑",
      ],
      upcoming: [
        "指标定义与口径管理",
        "基于 DWS / ADS 的指标计算任务",
        "指标与可用维度的绑定关系",
      ],
      dependencies: ["数据仓库 → 指标中心 → 数据服务 → 智能问数应用"],
    },
    {
      slug: "services",
      name: "数据服务",
      summary: "以统一接口对外提供指标与明细数据的查询能力。",
      status: "building",
      notice:
        "当前只有 Agent 内部的模拟查询，没有对外的数据服务接口，前端不会请求任何接口。",
      current: [
        "Agent 内部使用模拟查询结果，未对外暴露接口",
        "数据服务 API、鉴权与配额均未实现",
      ],
      upcoming: [
        "指标查询 API 与明细查询 API",
        "查询鉴权、配额与审计日志",
        "为智能问数应用提供数据出口",
      ],
      dependencies: ["指标中心 → 数据服务 → 智能问数应用"],
    },
  ],
};

const AI: PlatformSection = {
  id: "ai",
  name: "AI 中台",
  duty: "统一模型、知识、工具、工作流和 Agent 能力",
  status: "building",
  statusNote:
    "核心 Agent 已完成受控问数流程：问题理解、资产发现、SQL 生成与安全校验、模拟查询、结果解释、图表建议；模型管理、知识库、工作流与 AI 运营仍待接入。",
  entry: "/ai/agents",
  entryLabel: "进入 Agent 中心",
  modules: [
    {
      slug: "models",
      name: "模型与 Prompt",
      summary: "统一管理模型接入配置与 Prompt 模板。",
      status: "building",
      notice:
        "当前 Agent 使用代码内固定的 Prompt 逻辑，没有统一的模型与模板管理，也不在本页展示任何密钥或连接信息。",
      current: [
        "Agent 内已固化问数流程所需的 Prompt 逻辑",
        "尚无模型配置中心与 Prompt 版本管理",
      ],
      upcoming: [
        "模型接入配置与切换",
        "Prompt 模板与版本管理",
        "调用量、耗时与失败率统计",
      ],
      dependencies: ["模型与 Prompt → Agent 中心 → 智能问数应用"],
    },
    {
      slug: "knowledge",
      name: "知识库与 RAG",
      summary: "把业务文档与指标口径沉淀为可检索的知识，供 Agent 引用。",
      status: "planned",
      notice: "知识库与检索链路均未建立，Agent 当前不检索任何文档。",
      current: [
        "没有文档接入与切分流程",
        "没有向量化与检索能力",
      ],
      upcoming: [
        "文档接入与切分",
        "向量化与相似度检索",
        "检索结果作为 Agent 生成 SQL 的依据",
      ],
      dependencies: ["知识库 → RAG 检索 → Agent 中心"],
    },
    {
      slug: "agents",
      name: "Agent 中心",
      summary: "编排受控智能问数 Agent，把自然语言问题转成可解释的查询结果。",
      status: "done",
      notice:
        "当前使用模拟资产与模拟查询结果；尚未接入真实数仓、RAG 或用户问数 API。本页只展示流程与能力边界，不展示模型密钥、连接串、SQL 原文或内部异常。",
      workflow: [
        "问题理解",
        "资产发现",
        "SQL 生成",
        "SQL 安全校验",
        "最多修复一次",
        "模拟查询",
        "结果解释",
        "图表建议",
      ],
      current: [
        "基于 LangGraph 的受控问数工作流已跑通",
        "SQL 经 AST 安全校验：只允许只读查询，拦截危险语句",
        "校验不通过时最多自动修复一次，仍失败则明确返回失败原因",
        "查询结果为模拟数据，输出包含结果解释与图表类型建议",
        "核心链路已有自动化测试覆盖",
      ],
      upcoming: [
        "接入真实数仓与数据服务，替换模拟资产与模拟查询",
        "接入 RAG 知识库提升资产发现准确率",
        "对外提供问数 API，供前端应用调用",
        "多轮追问与上下文管理",
      ],
      dependencies: ["数据服务 + 知识库与 RAG → Agent 中心 → 智能问数应用"],
    },
    {
      slug: "workflows",
      name: "工作流与工具",
      summary: "把可复用的工具与流程沉淀为平台能力。",
      status: "planned",
      notice:
        "除智能问数 Agent 内部的固定流程外，尚未提供通用工作流编排与工具接入。",
      current: [
        "仅智能问数 Agent 内部有固定流程",
        "没有工具注册与工作流编排能力",
      ],
      upcoming: [
        "MCP 工具接入与工具注册",
        "工作流编排与定时任务",
        "工具调用审计日志",
      ],
      dependencies: ["Agent 中心 → 工作流与工具 → 其他智能应用"],
    },
    {
      slug: "operations",
      name: "AI 运营",
      summary: "观测 AI 能力的调用质量与成本，支撑持续优化。",
      status: "planned",
      notice: "尚无调用日志、效果评估与成本统计。",
      current: [
        "没有调用日志与链路追踪",
        "没有效果评估与人工反馈入口",
      ],
      upcoming: [
        "调用日志与链路追踪",
        "效果评估与人工反馈",
        "Token 成本与配额统计",
      ],
      dependencies: ["Agent 中心 + 模型与 Prompt → AI 运营"],
    },
  ],
};

const APPLICATIONS: PlatformSection = {
  id: "applications",
  name: "智能应用",
  duty: "将数据和 AI 能力交付给业务人员",
  status: "planned",
  statusNote: "经营驾驶舱与智能问数均未接入真实数据服务，尚未对业务人员开放。",
  entry: "/applications/dashboard",
  entryLabel: "进入经营驾驶舱",
  modules: [
    {
      slug: "dashboard",
      name: "经营驾驶舱",
      summary: "面向管理者的经营指标看板，展示销售与客户核心指标趋势。",
      status: "planned",
      notice: "依赖指标中心与数据服务，当前没有真实指标可以展示。",
      current: [
        "依赖的指标中心与数据服务尚未就绪",
        "没有可展示的真实经营指标",
      ],
      upcoming: [
        "核心经营指标看板",
        "趋势与同环比分析",
        "从指标下钻到明细数据",
      ],
      dependencies: ["指标中心 + 数据服务 → 经营驾驶舱"],
    },
    {
      slug: "data-query",
      name: "智能问数",
      summary: "用自然语言提问，得到可解释的查询结果与图表建议。",
      status: "building",
      notice:
        "智能问数应用正在接入数据服务。本页是建设状态说明，不是可用的问数界面。",
      current: [
        "后端已完成受控智能问数 Agent 核心：问题理解 → 资产发现 → SQL 生成 → SQL 安全校验 → 模拟查询 → 结果解释 → 图表建议",
        "SQL AST 安全校验与自动化测试已完成",
        "前端尚未接入：本阶段不提供输入框，也不返回任何模拟回答",
      ],
      upcoming: [
        "智能问数 API",
        "真实数据服务",
        "前端输入与结果展示",
      ],
      dependencies: ["Agent 中心 + 数据服务 → 智能问数应用"],
    },
  ],
};

/** 左侧导航按此顺序渲染，同时决定总览页分层链路的顺序。 */
export const PLATFORM_SECTIONS: PlatformSection[] = [
  BUSINESS,
  DATA,
  AI,
  APPLICATIONS,
];

export const OVERVIEW_NAV_ITEM = {
  name: "平台总览",
  href: "/",
  desc: "平台整体架构、建设进度与下一步路线",
};

/** 动态路由 app/<section>/[module] 需要的分段参数，供 generateStaticParams 使用。 */
export function getSection(id: string): PlatformSection | undefined {
  return PLATFORM_SECTIONS.find((section) => section.id === id);
}

export function getModule(
  sectionId: string,
  slug: string,
): PlatformModule | undefined {
  return getSection(sectionId)?.modules.find((item) => item.slug === slug);
}

export function getModuleHref(
  section: PlatformSection,
  moduleConfig: PlatformModule,
) {
  return `/${section.id}/${moduleConfig.slug}`;
}

/** 顶栏据此判断「当前页面」。找不到时返回 undefined，由调用方给出兜底文案。 */
export function resolveActiveModule(pathname: string) {
  for (const section of PLATFORM_SECTIONS) {
    for (const moduleConfig of section.modules) {
      if (getModuleHref(section, moduleConfig) === pathname) {
        return { section, module: moduleConfig };
      }
    }
  }
  return undefined;
}
