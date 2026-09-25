/**
 * 平台信息架构的唯一数据源。
 *
 * 所有路由、模块名称、建设状态、能力说明与依赖关系都集中在这里，
 * 页面组件只负责渲染，不再各自硬编码。
 * 修改这里的状态，左侧导航、顶栏标题与模块页会同步更新。
 *
 * **维护约定**：这里的每一句「当前能力」都必须能在代码或接口里找到对应物。
 * 只登记已经真实可用的能力——这个平台的定位是可演示的最小可用版本，
 * 规划中的东西不进这份清单，写进侧边栏就更不行（那会变成点不出东西的入口）。
 */

/** 平台身份。全站只有这一处，其它页面一律引用，不重复写字面量。 */
export const PLATFORM_NAME = "InsightFlow 数据智能 Agent 平台";
export const PLATFORM_TAGLINE = "面向多业务场景的数据资产与智能应用平台";
/** 首页 Hero 上的小标签。 */
export const PLATFORM_BADGE = "作品集演示 · 多业务可扩展";

/**
 * 演示数据的口径说明。
 *
 * 零售只是当前用来把链路跑通的演示业务，不是这个平台的能力边界。
 * 凡是展示零售样例数据的位置都应该带上这句话。
 */
export const RETAIL_DATA_NOTE =
  "当前使用零售样例数据，后续可扩展到其他业务场景。";

/**
 * 真实功能页的路径。
 *
 * 多个页面要互相跳转（首页 → 功能页、数据仓库 → 知识问答、架构页 → 各功能），
 * 路径写在一处，改路由时不会漏掉某个引用点。
 */
export const PAGE_HREFS = {
  dataSources: "/data/sources",
  dataWarehouse: "/data/warehouse",
  knowledgeQa: "/applications/knowledge-qa",
  dataQuery: "/applications/data-query",
  businessAnalysis: "/applications/business-analysis",
  architecture: "/architecture",
} as const;

/** 模块建设状态。取值只有这三种，避免出现「部分完成」这类模糊说法。 */
export type ModuleStatus = "done" | "building" | "planned";

export const STATUS_LABEL: Record<ModuleStatus, string> = {
  done: "已完成",
  building: "建设中",
  planned: "待接入",
};

/**
 * 该模块已有的真实可交互页面。
 *
 * 没有这个字段 = 当前没有可前往的功能页。模块页据此决定要不要渲染入口按钮——
 * 这样就不会出现「按钮在，点了没反应」或者「跳到一个还是说明页的页面」。
 */
export type LivePage = {
  href: string;
  /** 功能名，用作首页功能卡与模块页入口的标题。 */
  label: string;
  /** 一句话说明这个功能能干什么。 */
  desc: string;
};

export type PlatformModule = {
  /** 路由末段，对应 app/<section>/[module] 的 [module]。 */
  slug: string;
  name: string;
  /** 一句职责说明。 */
  summary: string;
  status: ModuleStatus;
  /**
   * 建设边界：写清楚「现在没有什么」。
   * 有独立页面的模块，这句话会渲染在该页的使用边界里；
   * 由模板页渲染的模块，它会作为「建设边界」提示出现。
   */
  notice?: string;
  /** 已跑通的处理链路，逐步展示。 */
  workflow?: string[];
  /** 当前能力。必须与实现一致，首页与模块页都会展示它。 */
  current: string[];
  /** 后续可扩展的方向。只有模板页会渲染，所以按需填写，不必每个模块都有。 */
  upcoming?: string[];
  /** 该模块在平台中的上下游位置。 */
  dependencies?: string[];
  livePage?: LivePage;
};

/** 业务中台已从导航中移除，因此只剩三层。 */
export type SectionId = "data" | "ai" | "applications";

export type PlatformSection = {
  id: SectionId;
  name: string;
  /** 所属层级的一句话职责。 */
  duty: string;
  status: ModuleStatus;
  /** 层级状态的补充说明。 */
  statusNote: string;
  modules: PlatformModule[];
};

const DATA: PlatformSection = {
  id: "data",
  name: "数据中台",
  duty: "把业务文档与数据汇入平台，沉淀为可检索的资产",
  status: "building",
  statusNote:
    "知识文档的采集链路已跑通，PostgreSQL 里也已有可供真实查询的样例数据。业务数据文件导入与完整的数仓分层建模尚未建立。",
  modules: [
    {
      slug: "sources",
      name: "数据采集",
      summary: "上传知识文档，自动完成解析、切片、向量化并写入知识库。",
      status: "building",
      notice:
        "业务数据文件（Excel / CSV）的导入、采集任务调度与失败重试尚未建立；扫描件 PDF（没有文字层）需要 OCR，暂不支持。",
      current: [
        "上传 md / txt / docx / pdf 四种格式的知识文档",
        "docx 按段落样式、PDF 按字号还原出标题层级，再复用同一套切片逻辑",
        "文本按二级标题切片、计算向量并写入 PostgreSQL + pgvector",
        "入库幂等：内容未变时整体跳过，不重复消耗向量计算",
      ],
      livePage: {
        href: PAGE_HREFS.dataSources,
        label: "数据采集",
        desc: "上传知识文档，完成解析、切片、向量化和入库。",
      },
    },
    {
      slug: "warehouse",
      name: "数据仓库",
      summary:
        "PostgreSQL 中的零售样例数据底座，为智能问数与知识问答提供数据基础。",
      status: "building",
      notice:
        "这里建的是样例表，不是完整的 ODS / DWD / DWS / ADS 分层数仓——五张表直接建成，没有经过分层加工。",
      current: [
        "PostgreSQL 16 承载四张维度表 + 一张订单事实表，共五张样例表",
        "样例数据由固定种子的生成规则产生，重复执行结果一致",
        "金额口径在数据库层用 CHECK 约束钉死：应收 = 数量 × 单价，实付 = 应收 − 折扣",
        "事实表只存订单明细原始粒度，汇总全部由 SQL 现场计算",
      ],
      livePage: {
        href: PAGE_HREFS.dataWarehouse,
        label: "数据仓库",
        desc: "查看五张样例表的结构、数据规模和它们之间的关系。",
      },
    },
  ],
};

const AI: PlatformSection = {
  id: "ai",
  name: "AI 中台",
  duty: "把知识、模型与 Agent 能力沉淀为可复用的平台能力",
  status: "building",
  statusNote:
    "知识库与 RAG 已建成并接入 Agent，受控问数 Agent 已跑通并查询真实数据。模型与 Prompt 的可视化配置、通用工作流编排仍待建立。",
  modules: [
    {
      slug: "knowledge",
      name: "知识库与 RAG",
      summary: "把业务文档沉淀为可检索的知识，供知识问答与 Agent 引用。",
      status: "building",
      notice:
        "文档删除、重命名、重建索引等知识库管理操作尚未提供，也没有检索质量评测与人工反馈入口。",
      current: [
        "文档按二级标题切片，逐片计算 1024 维向量后写入 PostgreSQL + pgvector",
        "用余弦距离做相似度检索，回答附带命中的文档、小节与原文片段",
        "回答只依据检索到的资料；资料不足时明确说明「没有足够信息」，不用模型自身知识补全",
        "已接入 Agent：口径与归因类问题由知识库直接作答，问数结果会附上命中的文档小节",
      ],
      dependencies: [
        "上传文档 → 文件解析 → 文本切片 → Embedding → pgvector → 相似度检索 → 知识问答",
      ],
      livePage: {
        href: PAGE_HREFS.knowledgeQa,
        label: "知识问答",
        desc: "基于已入库文档回答业务口径和规则问题。",
      },
    },
    {
      slug: "agents",
      name: "Agent 中心",
      summary:
        "用 LangGraph 编排受控问数流程，把自然语言问题转成可解释的查询结果。",
      status: "done",
      notice:
        "尚未接入多轮上下文与用户权限。本页只展示流程与能力边界，不展示模型密钥、连接串、SQL 原文或内部异常。",
      workflow: [
        "问题理解",
        "数据资产发现",
        "SQL 生成",
        "SQL 安全校验",
        "查询执行",
        "RAG 辅助解释",
        "图表建议",
      ],
      current: [
        "基于 LangGraph 编排的受控工作流，共 11 个节点",
        "SQL 经两层 AST 安全校验：Agent 层挡工作流，数据服务层独立守护数据库",
        "校验不通过时最多自动修复一次，仍失败则明确返回失败原因",
        "查询真实 PostgreSQL 样例数据；需要解释口径时检索知识库，检索失败不影响数据结论",
      ],
      dependencies: [
        "数据服务 + 知识库与 RAG → Agent 中心 → 智能问数应用",
      ],
      livePage: {
        href: PAGE_HREFS.dataQuery,
        label: "智能问数",
        desc: "用中文提问，Agent 查询真实样例数据并返回分析结果。",
      },
    },
  ],
};

const APPLICATIONS: PlatformSection = {
  id: "applications",
  name: "智能应用",
  duty: "把数据与 AI 能力交付给业务人员使用",
  status: "done",
  statusNote:
    "两个应用都已可交互：智能问数查业务数据，知识问答查业务文档。两者都基于本地零售样例数据。",
  modules: [
    {
      slug: "data-query",
      name: "智能问数",
      summary: "用自然语言提问，得到可解释的查询结果与图表建议。",
      status: "done",
      notice:
        "尚未接入企业真实生产数据、用户权限与会话记忆；每次提问会调用配置的模型服务。",
      current: [
        "输入中文问题，由后端 Agent 查询真实 PostgreSQL 样例数据",
        "结果包含分析结论、明细表与图表建议（折线 / 柱状 / 表格）",
        "口径与归因类问题会附带命中的知识库小节作为解释依据",
        "接口经过安全映射：不返回 SQL、表名字段名、内部状态或异常原文",
      ],
      livePage: {
        href: PAGE_HREFS.dataQuery,
        label: "智能问数",
        desc: "用中文提问，Agent 查询真实样例数据并返回分析结果。",
      },
    },
    {
      slug: "knowledge-qa",
      name: "知识问答",
      summary: "针对业务口径与规则类问题，检索知识库并给出带来源的回答。",
      status: "done",
      notice:
        "检索与生成尚未做人工评测，也未接入企业真实文档；每次提问会调用 embedding 与模型服务。",
      current: [
        "用 pgvector 余弦距离检索已入库的知识切片",
        "回答只依据检索到的知识库资料，并附带参考来源",
        "来源含文档、小节、片段位置、原文摘要与相似度",
        "资料不足时如实说明，不编造；与智能问数是两条独立链路",
      ],
      livePage: {
        href: PAGE_HREFS.knowledgeQa,
        label: "知识问答",
        desc: "基于已入库文档回答业务口径和规则问题。",
      },
    },
    {
      slug: "business-analysis",
      name: "AI 经营分析",
      summary: "由主管 Agent 多轮调用问数和知识库工具，生成带证据的经营分析报告。",
      status: "building",
      notice:
        "当前使用零售样例数据和匿名浏览器会话；企业登录、租户隔离与生产数据权限尚未接入。",
      workflow: [
        "理解经营目标",
        "动态调用数据分析工具",
        "根据异常继续下钻",
        "检索业务规则与指标口径",
        "生成结构化经营报告",
      ],
      current: [
        "基于 Deep Agents 的主管 Agent",
        "复用现有智能问数 LangGraph 和 RAG 工具",
        "通过 SSE 实时展示工具调用与报告生成过程",
        "支持线程状态恢复和匿名用户偏好记忆",
      ],
      dependencies: [
        "智能问数 + 知识库与 RAG → Deep Agents 主管 → AI 经营分析应用",
      ],
      livePage: {
        href: PAGE_HREFS.businessAnalysis,
        label: "AI 经营分析",
        desc: "让主管 Agent 多步分析销售、会员、品类和业务规则。",
      },
    },
  ],
};

/** 左侧导航按此顺序渲染。 */
export const PLATFORM_SECTIONS: PlatformSection[] = [
  DATA,
  AI,
  APPLICATIONS,
];

export const OVERVIEW_NAV_ITEM = {
  name: "平台总览",
  href: "/",
  desc: "平台已完成的真实能力与两条处理链路",
};

/**
 * 不属于任何层级的独立页面，渲染在侧边栏最底部。
 *
 * 它们没有建设状态点——状态点表示「这个模块建到哪一步了」，
 * 而技术栈与架构是讲解性质的一页，没有建设进度可言。
 */
export const EXTRA_NAV_ITEMS = [
  {
    name: "技术栈与架构",
    href: PAGE_HREFS.architecture,
    desc: "平台用到的技术栈、系统结构与数据流转",
  },
];

/**
 * 首页顶部的三个核心功能卡，按展示顺序排列。
 *
 * 只登记「哪个模块」，标题与说明从模块配置里的 livePage 取——
 * 在这里再写一遍文案，就等于同一个功能有了两份会各自漂移的描述。
 */
export const OVERVIEW_ENTRY_KEYS = [
  { sectionId: "data", slug: "sources" },
  { sectionId: "applications", slug: "knowledge-qa" },
  { sectionId: "applications", slug: "data-query" },
  { sectionId: "applications", slug: "business-analysis" },
] as const;

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

/**
 * 顶栏与侧边栏据此判断「当前在哪个页面」。
 *
 * 覆盖三种情况：总览、某个模块、不属于任何层级的独立页面。
 * 都不匹配时返回 undefined，由调用方给出兜底文案——不猜、不假装这是个正常页面。
 */
export function resolveNav(
  pathname: string,
): { pageName: string; sectionName?: string } | undefined {
  if (pathname === OVERVIEW_NAV_ITEM.href) {
    return { pageName: OVERVIEW_NAV_ITEM.name };
  }

  const extra = EXTRA_NAV_ITEMS.find((item) => item.href === pathname);
  if (extra) {
    return { pageName: extra.name };
  }

  for (const section of PLATFORM_SECTIONS) {
    for (const moduleConfig of section.modules) {
      if (getModuleHref(section, moduleConfig) === pathname) {
        return { pageName: moduleConfig.name, sectionName: section.name };
      }
    }
  }

  return undefined;
}

/**
 * 解析首页的功能卡。
 *
 * 配置里登记了模块但模块没有 livePage（说明还没有真实页面）时会跳过它，
 * 而不是渲染一个点了没反应的卡片。
 */
export function getOverviewEntries(): Array<
  LivePage & { key: string; moduleName: string; sectionName: string }
> {
  const entries: Array<
    LivePage & { key: string; moduleName: string; sectionName: string }
  > = [];

  for (const { sectionId, slug } of OVERVIEW_ENTRY_KEYS) {
    const section = getSection(sectionId);
    const moduleConfig = section ? getModule(sectionId, slug) : undefined;
    if (!section || !moduleConfig?.livePage) continue;

    entries.push({
      key: `${sectionId}/${slug}`,
      moduleName: moduleConfig.name,
      sectionName: section.name,
      ...moduleConfig.livePage,
    });
  }

  return entries;
}
