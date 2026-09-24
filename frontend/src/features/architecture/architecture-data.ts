import { PAGE_HREFS } from "../platform/platform-config";

export type ArchitectureLayerId =
  | "engineering"
  | "resources"
  | "capabilities"
  | "orchestration"
  | "delivery"
  | "applications";

export type ArchitectureLayer = {
  id: ArchitectureLayerId;
  order: number;
  title: string;
  eyebrow: string;
  description: string;
};

export type ArchitectureNodeKind =
  | "infrastructure"
  | "resource"
  | "capability"
  | "agent"
  | "interface"
  | "application";

export type TechnologyDetail = {
  role: string;
  technologies: string[];
  inputs: string[];
  outputs: string[];
  interfaces: string[];
  supports: string[];
  evidence: string;
};

export type ArchitectureNode = {
  id: string;
  layerId: ArchitectureLayerId;
  kind: ArchitectureNodeKind;
  title: string;
  subtitle: string;
  status: "current";
  href?: (typeof PAGE_HREFS)[keyof typeof PAGE_HREFS];
  detail: TechnologyDetail;
};

export type ArchitectureEdge = {
  id: string;
  source: string;
  target: string;
  label: string;
  direction: "forward" | "bidirectional";
};

export type WorkflowId = "document-rag" | "data-query" | "business-analysis";

export type WorkflowStep = {
  id: string;
  title: string;
  description: string;
  nodeIds: string[];
};

export type WorkflowDefinition = {
  id: WorkflowId;
  title: string;
  shortTitle: string;
  summary: string;
  outcome: string;
  color: string;
  lineStyle: "solid" | "dashed" | "double";
  lineLabel: string;
  nodeIds: string[];
  edgeIds: string[];
  steps: WorkflowStep[];
};

export type ArchitectureModel = {
  title: string;
  subtitle: string;
  layers: ArchitectureLayer[];
  nodes: ArchitectureNode[];
  edges: ArchitectureEdge[];
  workflows: WorkflowDefinition[];
  boundaries: string[];
};

export const FORBIDDEN_CURRENT_CAPABILITIES = [
  "个人办公 Agent",
  "日程管理 Agent",
  "邮件处理 Agent",
] as const;

const layers: ArchitectureLayer[] = [
  {
    id: "engineering",
    order: 1,
    title: "工程与运行环境",
    eyebrow: "RUN",
    description: "保障本地开发、容器运行、质量检查与配置管理。",
  },
  {
    id: "resources",
    order: 2,
    title: "数据与模型资源",
    eyebrow: "RESOURCE",
    description: "提供结构化数据、向量索引和 OpenAI-compatible 模型能力。",
  },
  {
    id: "capabilities",
    order: 3,
    title: "平台能力",
    eyebrow: "CAPABILITY",
    description: "把数据资源封装为可复用的解析、检索、查询和持久化能力。",
  },
  {
    id: "orchestration",
    order: 4,
    title: "Agent 编排",
    eyebrow: "ORCHESTRATE",
    description: "组织模型、工具、状态图和 Agent Loop，决定任务如何执行。",
  },
  {
    id: "delivery",
    order: 5,
    title: "API 与前端",
    eyebrow: "DELIVER",
    description: "通过类型化 API、实时事件和 Web 页面交付平台能力。",
  },
  {
    id: "applications",
    order: 6,
    title: "当前业务应用",
    eyebrow: "USE",
    description: "当前已经可以打开和演示的五个业务入口。",
  },
];

const nodes: ArchitectureNode[] = [
  {
    id: "runtime",
    layerId: "engineering",
    kind: "infrastructure",
    title: "Docker Compose",
    subtitle: "Python 3.14 · Uvicorn",
    status: "current",
    detail: {
      role: "统一启动前端、FastAPI 与 PostgreSQL，并通过健康检查控制服务依赖顺序。",
      technologies: ["Docker Compose", "Python 3.14", "Uvicorn", "环境变量", "健康检查"],
      inputs: ["服务配置", "模型与数据库环境变量", "应用源码"],
      outputs: ["可复现的本地运行环境", "服务健康状态"],
      interfaces: ["docker compose", "/api/health"],
      supports: ["全部业务页面", "后端 API", "PostgreSQL"],
      evidence: "仓库包含前后端与数据库编排、环境变量示例和健康检查配置。",
    },
  },
  {
    id: "quality",
    layerId: "engineering",
    kind: "infrastructure",
    title: "质量与类型检查",
    subtitle: "pytest · Vitest · ESLint",
    status: "current",
    detail: {
      role: "在提交和构建前验证 Python、TypeScript、组件逻辑与类型边界。",
      technologies: ["pytest", "Vitest", "ESLint", "TypeScript strict"],
      inputs: ["后端测试", "前端单元测试", "TypeScript 源码"],
      outputs: ["测试结果", "静态检查结果", "生产构建"],
      interfaces: ["pytest", "npm run test:unit", "npm run lint", "npx tsc --noEmit"],
      supports: ["持续验证", "回归保护", "类型安全"],
      evidence: "仓库已配置 pytest、Vitest、ESLint 与严格 TypeScript 检查。",
    },
  },
  {
    id: "postgres",
    layerId: "resources",
    kind: "resource",
    title: "PostgreSQL 16",
    subtitle: "pgvector · Async data access",
    status: "current",
    detail: {
      role: "同时承载零售星型模型、知识库、Agent 运行状态和长期记忆。",
      technologies: ["PostgreSQL 16", "pgvector", "SQLAlchemy Async", "asyncpg", "Alembic"],
      inputs: ["零售样例数据", "知识文档切片", "向量", "运行状态与偏好"],
      outputs: ["关系查询结果", "向量/关键词候选", "Checkpoint", "Store"],
      interfaces: ["SQLAlchemy AsyncSession", "asyncpg", "Alembic migrations"],
      supports: ["数据仓库", "知识问答", "智能问数", "AI 经营分析助手"],
      evidence: "数据库迁移包含零售数据、知识库及经营分析相关持久化结构。",
    },
  },
  {
    id: "model-services",
    layerId: "resources",
    kind: "resource",
    title: "模型服务",
    subtitle: "Chat · Embedding · Rerank",
    status: "current",
    detail: {
      role: "提供对话推理、查询改写、向量化、候选精排和答案生成。",
      technologies: [
        "DeepSeek / OpenAI-compatible Chat Model",
        "text-embedding-v4",
        "qwen3-rerank",
      ],
      inputs: ["Prompt", "文档文本", "检索候选", "工具执行结果"],
      outputs: ["模型消息", "1024 维向量", "精排分数", "结构化决策"],
      interfaces: ["OpenAI-compatible API", "DashScope-compatible API"],
      supports: ["混合检索", "智能问数", "AI 经营分析助手"],
      evidence: "模型配置通过兼容接口接入聊天、Embedding 与 Rerank 服务。",
    },
  },
  {
    id: "document-ingestion",
    layerId: "capabilities",
    kind: "capability",
    title: "文档解析与入库",
    subtitle: "Word / PDF → Markdown",
    status: "current",
    detail: {
      role: "解析四类知识文档，归一化为 Markdown，再按标题语义切片并提取元数据。",
      technologies: ["python-docx", "pdfplumber", "Markdown 归一化", "语义切片", "元数据提取"],
      inputs: ["md", "txt", "docx", "带文字层的 pdf"],
      outputs: ["规范化 Markdown", "文档切片", "来源与标题元数据"],
      interfaces: ["文档上传 API"],
      supports: ["数据采集", "知识问答", "RAG 知识底座"],
      evidence: "现有采集页支持文档上传、解析、幂等切片和向量入库。",
    },
  },
  {
    id: "hybrid-rag",
    layerId: "capabilities",
    kind: "capability",
    title: "混合检索 RAG",
    subtitle: "Rewrite · RRF · Rerank",
    status: "current",
    detail: {
      role: "先改写问题，再合并向量与关键词召回，经 RRF 融合和模型精排后生成带来源回答。",
      technologies: ["查询改写", "pgvector", "关键词召回", "RRF", "qwen3-rerank", "来源引用"],
      inputs: ["自然语言问题", "知识切片与向量"],
      outputs: ["融合候选", "精排上下文", "带来源答案"],
      interfaces: ["RAG answer API", "Agent RAG tool"],
      supports: ["知识问答", "智能问数解释", "AI 经营分析助手"],
      evidence: "检索链路包含查询改写、双路召回、RRF、Rerank 与来源返回。",
    },
  },
  {
    id: "safe-sql",
    layerId: "capabilities",
    kind: "capability",
    title: "安全 SQL 执行",
    subtitle: "sqlglot AST · Read only",
    status: "current",
    detail: {
      role: "在执行模型生成的 SQL 前完成 AST、表列函数白名单和 LIMIT 校验，并在只读事务中限时查询。",
      technologies: ["sqlglot AST", "白名单", "LIMIT 注入", "只读事务", "查询超时", "一次修复"],
      inputs: ["模型生成 SQL", "允许访问的数据资产元数据"],
      outputs: ["校验结果", "安全 SQL", "结构化查询结果"],
      interfaces: ["safe query service", "data query tool"],
      supports: ["智能问数", "AI 经营分析助手"],
      evidence: "智能问数链路对 SQL 做语法树校验并限制为只读查询。",
    },
  },
  {
    id: "agent-persistence",
    layerId: "capabilities",
    kind: "capability",
    title: "Agent 状态与记忆",
    subtitle: "Checkpoint · Store · Preferences",
    status: "current",
    detail: {
      role: "保存运行中状态、报告产物与跨会话长期偏好，让复杂分析可持续执行和恢复。",
      technologies: ["PostgreSQL Checkpoint", "LangGraph Store", "长期偏好", "报告与产物"],
      inputs: ["thread_id", "Agent 状态", "用户偏好", "报告内容"],
      outputs: ["可恢复运行", "持久化报告", "长期记忆上下文"],
      interfaces: ["thread API", "run API", "preference API"],
      supports: ["AI 经营分析助手"],
      evidence: "经营分析模块包含运行、线程、报告、产物及偏好持久化。",
    },
  },
  {
    id: "langchain",
    layerId: "orchestration",
    kind: "agent",
    title: "LangChain",
    subtitle: "模型与工具接口",
    status: "current",
    detail: {
      role: "统一 OpenAI-compatible 聊天模型、消息、Prompt 和工具调用接口。",
      technologies: ["LangChain", "ChatOpenAI", "Tool calling", "Prompt templates"],
      inputs: ["系统提示词", "用户消息", "工具定义", "模型配置"],
      outputs: ["模型消息", "工具调用请求", "结构化输出"],
      interfaces: ["LangChain Runnable", "BaseTool"],
      supports: ["智能问数", "AI 经营分析助手"],
      evidence: "模型和 Agent 工具通过 LangChain 标准接口接入。",
    },
  },
  {
    id: "langgraph-query",
    layerId: "orchestration",
    kind: "agent",
    title: "LangGraph 智能问数",
    subtitle: "StateGraph · Conditional route",
    status: "current",
    detail: {
      role: "把意图识别、资产发现、SQL 生成、校验修复、查询和解释组织为可追踪状态图。",
      technologies: ["LangGraph", "StateGraph", "条件路由", "一次 SQL 修复"],
      inputs: ["自然语言问题", "会话上下文", "数据资产描述"],
      outputs: ["SQL", "查询结果", "业务结论", "图表建议"],
      interfaces: ["data query API", "business analysis data-query tool"],
      supports: ["智能问数", "AI 经营分析助手"],
      evidence: "智能问数以状态图编排生成、校验、修复、执行与解释步骤。",
    },
  },
  {
    id: "deep-agents",
    layerId: "orchestration",
    kind: "agent",
    title: "Deep Agents 主管",
    subtitle: "Agent Loop · Multi-tool",
    status: "current",
    detail: {
      role: "接收复杂经营目标，自主拆解任务，在 Agent Loop 中选择智能问数、RAG 和报告工具。",
      technologies: ["Deep Agents 0.7.18", "Agent Loop", "Tool calling", "Prompt engineering", "Context management"],
      inputs: ["复杂经营目标", "长期偏好", "工具描述", "历史状态"],
      outputs: ["任务计划", "工具调用序列", "证据链", "经营分析报告"],
      interfaces: ["data-query tool", "RAG tool", "report tool"],
      supports: ["AI 经营分析助手"],
      evidence: "经营分析使用 Deep Agents 主管调用既有问数与知识检索能力。",
    },
  },
  {
    id: "sse-events",
    layerId: "orchestration",
    kind: "interface",
    title: "SSE 执行事件",
    subtitle: "Status · Tool · Report delta",
    status: "current",
    detail: {
      role: "把运行状态、工具调用和报告增量按事件持续推送到浏览器。",
      technologies: ["Server-Sent Events", "流式响应", "AbortController"],
      inputs: ["Agent 运行事件", "报告文本增量", "错误事件"],
      outputs: ["实时执行时间线", "流式报告", "可见错误状态"],
      interfaces: ["text/event-stream"],
      supports: ["AI 经营分析助手"],
      evidence: "经营分析运行接口以 SSE 返回 status、tool 和 report_delta 等事件。",
    },
  },
  {
    id: "fastapi",
    layerId: "delivery",
    kind: "interface",
    title: "FastAPI 服务",
    subtitle: "Pydantic · REST · SSE",
    status: "current",
    detail: {
      role: "向前端提供文档、RAG、问数、经营分析和健康检查接口，并用 Pydantic 校验输入输出。",
      technologies: ["FastAPI", "Pydantic", "REST", "SSE", "CORS"],
      inputs: ["HTTP 请求", "上传文件", "自然语言问题", "经营分析目标"],
      outputs: ["JSON 响应", "文件处理结果", "SSE 事件流"],
      interfaces: ["/api/documents", "/api/rag", "/api/data-query", "/api/business-analysis"],
      supports: ["全部当前业务应用"],
      evidence: "后端以 FastAPI 路由交付平台能力，并提供流式经营分析接口。",
    },
  },
  {
    id: "nextjs",
    layerId: "delivery",
    kind: "interface",
    title: "Web 交互层",
    subtitle: "Next.js 16 · React 19",
    status: "current",
    detail: {
      role: "承载平台导航、数据表格、对话、Agent 执行过程与架构说明页面。",
      technologies: ["Next.js 16", "React 19", "TypeScript", "CSS Modules"],
      inputs: ["REST 数据", "SSE 事件", "用户操作"],
      outputs: ["业务页面", "交互反馈", "数据与报告展示"],
      interfaces: ["App Router", "typed fetch clients"],
      supports: ["数据采集", "数据仓库", "知识问答", "智能问数", "AI 经营分析助手"],
      evidence: "前端使用 Next.js App Router 和 React 组件实现五个当前业务入口。",
    },
  },
  {
    id: "app-data-sources",
    layerId: "applications",
    kind: "application",
    title: "数据采集",
    subtitle: "知识文档入库",
    status: "current",
    href: PAGE_HREFS.dataSources,
    detail: {
      role: "上传并管理知识文档，触发解析、切片、向量化和幂等入库。",
      technologies: ["Next.js upload", "FastAPI multipart", "文档解析", "Embedding"],
      inputs: ["md / txt / docx / pdf"],
      outputs: ["可检索知识文档", "切片与入库统计"],
      interfaces: [PAGE_HREFS.dataSources],
      supports: ["知识库建设"],
      evidence: "当前已有可操作的数据采集页面。",
    },
  },
  {
    id: "app-warehouse",
    layerId: "applications",
    kind: "application",
    title: "数据仓库",
    subtitle: "零售星型模型",
    status: "current",
    href: PAGE_HREFS.dataWarehouse,
    detail: {
      role: "查看零售样例数据模型、表结构和基础数据资产。",
      technologies: ["PostgreSQL", "星型模型", "事实表", "维度表"],
      inputs: ["客户、商品、地区、日期与订单数据"],
      outputs: ["数据资产概览", "供问数查询的结构化数据"],
      interfaces: [PAGE_HREFS.dataWarehouse],
      supports: ["智能问数", "经营分析"],
      evidence: "当前已有零售样例数据与数据仓库页面。",
    },
  },
  {
    id: "app-knowledge-qa",
    layerId: "applications",
    kind: "application",
    title: "知识问答",
    subtitle: "带来源 RAG 对话",
    status: "current",
    href: PAGE_HREFS.knowledgeQa,
    detail: {
      role: "基于已入库文档回答问题，并返回可核验的来源片段。",
      technologies: ["Hybrid RAG", "RRF", "Rerank", "Grounded answer"],
      inputs: ["自然语言问题", "知识库"],
      outputs: ["回答", "来源与相关片段"],
      interfaces: [PAGE_HREFS.knowledgeQa],
      supports: ["制度、口径和业务知识查询"],
      evidence: "当前已有知识问答页面和完整检索 API。",
    },
  },
  {
    id: "app-data-query",
    layerId: "applications",
    kind: "application",
    title: "智能问数",
    subtitle: "NL2SQL + 解释",
    status: "current",
    href: PAGE_HREFS.dataQuery,
    detail: {
      role: "把自然语言问题转成经过安全校验的 SQL，返回结果、结论和图表建议。",
      technologies: ["LangGraph", "NL2SQL", "sqlglot", "RAG explanation"],
      inputs: ["自然语言数据问题"],
      outputs: ["SQL", "表格结果", "业务结论", "图表建议"],
      interfaces: [PAGE_HREFS.dataQuery],
      supports: ["自助数据分析"],
      evidence: "当前已有智能问数页面和安全查询链路。",
    },
  },
  {
    id: "app-business-analysis",
    layerId: "applications",
    kind: "application",
    title: "AI 经营分析助手",
    subtitle: "复杂目标 → 分析报告",
    status: "current",
    href: PAGE_HREFS.businessAnalysis,
    detail: {
      role: "针对复杂经营目标自主拆解、调用问数与知识工具，并实时生成带证据的分析报告。",
      technologies: ["Deep Agents", "Tool calling", "Agent Loop", "Checkpoint / Store", "SSE"],
      inputs: ["复杂经营目标", "默认分析区域", "历史偏好"],
      outputs: ["实时执行过程", "经营分析报告", "持久化产物"],
      interfaces: [PAGE_HREFS.businessAnalysis],
      supports: ["零售经营诊断与报告生成"],
      evidence: "当前已有经营分析页面、主管 Agent、工具链、持久化与流式报告。",
    },
  },
];

const edges: ArchitectureEdge[] = [
  { id: "runtime-postgres", source: "runtime", target: "postgres", label: "编排", direction: "forward" },
  { id: "runtime-fastapi", source: "runtime", target: "fastapi", label: "运行", direction: "forward" },
  { id: "runtime-nextjs", source: "runtime", target: "nextjs", label: "运行", direction: "forward" },
  { id: "postgres-ingestion", source: "postgres", target: "document-ingestion", label: "写入", direction: "bidirectional" },
  { id: "postgres-rag", source: "postgres", target: "hybrid-rag", label: "向量/关键词", direction: "bidirectional" },
  { id: "postgres-sql", source: "postgres", target: "safe-sql", label: "只读查询", direction: "bidirectional" },
  { id: "postgres-memory", source: "postgres", target: "agent-persistence", label: "持久化", direction: "bidirectional" },
  { id: "models-ingestion", source: "model-services", target: "document-ingestion", label: "Embedding", direction: "forward" },
  { id: "models-rag", source: "model-services", target: "hybrid-rag", label: "改写/精排/生成", direction: "forward" },
  { id: "models-langchain", source: "model-services", target: "langchain", label: "Chat API", direction: "forward" },
  { id: "ingestion-rag", source: "document-ingestion", target: "hybrid-rag", label: "切片与元数据", direction: "forward" },
  { id: "safe-query-graph", source: "safe-sql", target: "langgraph-query", label: "安全执行", direction: "bidirectional" },
  { id: "rag-query-graph", source: "hybrid-rag", target: "langgraph-query", label: "口径解释", direction: "forward" },
  { id: "rag-deep-agents", source: "hybrid-rag", target: "deep-agents", label: "RAG 工具", direction: "bidirectional" },
  { id: "memory-deep-agents", source: "agent-persistence", target: "deep-agents", label: "状态/记忆", direction: "bidirectional" },
  { id: "langchain-query-graph", source: "langchain", target: "langgraph-query", label: "模型/工具", direction: "forward" },
  { id: "langchain-deep-agents", source: "langchain", target: "deep-agents", label: "模型/工具", direction: "forward" },
  { id: "query-graph-deep-agents", source: "langgraph-query", target: "deep-agents", label: "问数工具", direction: "bidirectional" },
  { id: "deep-agents-sse", source: "deep-agents", target: "sse-events", label: "运行事件", direction: "forward" },
  { id: "query-fastapi", source: "langgraph-query", target: "fastapi", label: "REST", direction: "forward" },
  { id: "rag-fastapi", source: "hybrid-rag", target: "fastapi", label: "REST", direction: "forward" },
  { id: "ingestion-fastapi", source: "document-ingestion", target: "fastapi", label: "REST", direction: "forward" },
  { id: "sse-fastapi", source: "sse-events", target: "fastapi", label: "event-stream", direction: "forward" },
  { id: "fastapi-nextjs", source: "fastapi", target: "nextjs", label: "REST / SSE", direction: "bidirectional" },
  { id: "nextjs-data-sources", source: "nextjs", target: "app-data-sources", label: "页面", direction: "forward" },
  { id: "nextjs-warehouse", source: "nextjs", target: "app-warehouse", label: "页面", direction: "forward" },
  { id: "nextjs-knowledge-qa", source: "nextjs", target: "app-knowledge-qa", label: "页面", direction: "forward" },
  { id: "nextjs-data-query", source: "nextjs", target: "app-data-query", label: "页面", direction: "forward" },
  { id: "nextjs-business-analysis", source: "nextjs", target: "app-business-analysis", label: "页面", direction: "forward" },
];

const workflows: WorkflowDefinition[] = [
  {
    id: "document-rag",
    title: "文档入库与 RAG",
    shortTitle: "RAG",
    summary: "把非结构化文档变成可追溯、可混合检索的知识回答。",
    outcome: "用户得到带来源引用的回答，文档切片与向量可重复利用。",
    color: "#0f766e",
    lineStyle: "solid",
    lineLabel: "实线 · 文档知识流",
    nodeIds: ["model-services", "postgres", "document-ingestion", "hybrid-rag", "fastapi", "nextjs", "app-data-sources", "app-knowledge-qa"],
    edgeIds: ["models-ingestion", "postgres-ingestion", "ingestion-rag", "models-rag", "postgres-rag", "ingestion-fastapi", "rag-fastapi", "fastapi-nextjs", "nextjs-data-sources", "nextjs-knowledge-qa"],
    steps: [
      { id: "rag-upload", title: "上传与解析", description: "上传文档，由 python-docx / pdfplumber 提取内容并归一化为 Markdown。", nodeIds: ["app-data-sources", "document-ingestion"] },
      { id: "rag-index", title: "切片与索引", description: "按标题切片、提取元数据，调用 text-embedding-v4 后写入 PostgreSQL + pgvector。", nodeIds: ["document-ingestion", "model-services", "postgres"] },
      { id: "rag-retrieve", title: "改写与双路召回", description: "改写查询，同时执行 pgvector 相似度检索与关键词召回。", nodeIds: ["hybrid-rag", "model-services", "postgres"] },
      { id: "rag-answer", title: "融合、精排与回答", description: "用 RRF 合并候选，经 qwen3-rerank 精排后生成带来源回答。", nodeIds: ["hybrid-rag", "model-services", "fastapi", "nextjs", "app-knowledge-qa"] },
    ],
  },
  {
    id: "data-query",
    title: "智能问数",
    shortTitle: "NL2SQL",
    summary: "把业务问题转换为安全 SQL，并输出可解释的数据结论。",
    outcome: "用户得到经过安全约束的 SQL、查询结果、结论和图表建议。",
    color: "#2563eb",
    lineStyle: "dashed",
    lineLabel: "虚线 · 结构化数据流",
    nodeIds: ["model-services", "postgres", "safe-sql", "hybrid-rag", "langchain", "langgraph-query", "fastapi", "nextjs", "app-data-query", "app-warehouse"],
    edgeIds: ["models-langchain", "langchain-query-graph", "postgres-sql", "safe-query-graph", "rag-query-graph", "query-fastapi", "fastapi-nextjs", "nextjs-data-query", "nextjs-warehouse"],
    steps: [
      { id: "query-understand", title: "理解问题", description: "识别数据意图并发现可用表、字段与指标口径。", nodeIds: ["langchain", "langgraph-query"] },
      { id: "query-generate", title: "生成与校验 SQL", description: "生成 SQL，以 sqlglot AST 和白名单校验；失败时最多修复一次。", nodeIds: ["langgraph-query", "safe-sql", "model-services"] },
      { id: "query-execute", title: "只读执行", description: "在只读事务和查询超时约束内访问零售星型模型。", nodeIds: ["safe-sql", "postgres", "app-warehouse"] },
      { id: "query-explain", title: "解释与建议", description: "结合必要的 RAG 口径补充，输出结论、表格与图表建议。", nodeIds: ["hybrid-rag", "langgraph-query", "fastapi", "nextjs", "app-data-query"] },
    ],
  },
  {
    id: "business-analysis",
    title: "AI 经营分析",
    shortTitle: "Agent",
    summary: "由主管 Agent 自主拆解复杂目标并组合问数与知识工具。",
    outcome: "用户可实时看到证据收集过程，并获得可追溯、可恢复的经营分析报告。",
    color: "#c2410c",
    lineStyle: "double",
    lineLabel: "双线 · Agent 决策流",
    nodeIds: ["model-services", "postgres", "hybrid-rag", "safe-sql", "agent-persistence", "langchain", "langgraph-query", "deep-agents", "sse-events", "fastapi", "nextjs", "app-business-analysis"],
    edgeIds: ["models-langchain", "langchain-deep-agents", "postgres-sql", "safe-query-graph", "postgres-memory", "memory-deep-agents", "rag-deep-agents", "query-graph-deep-agents", "deep-agents-sse", "sse-fastapi", "fastapi-nextjs", "nextjs-business-analysis"],
    steps: [
      { id: "analysis-objective", title: "接收经营目标", description: "加载用户目标、默认区域和长期偏好，形成当前分析上下文。", nodeIds: ["app-business-analysis", "agent-persistence"] },
      { id: "analysis-plan", title: "主管拆解任务", description: "Deep Agents 在 Agent Loop 中规划子任务并选择合适工具。", nodeIds: ["deep-agents", "langchain", "model-services"] },
      { id: "analysis-tools", title: "调用问数与 RAG", description: "复用 LangGraph 智能问数和混合检索能力收集数据与知识证据。", nodeIds: ["langgraph-query", "safe-sql", "hybrid-rag", "postgres"] },
      { id: "analysis-report", title: "持久化并流式生成", description: "Checkpoint / Store 保存状态，SSE 增量返回执行过程和最终报告。", nodeIds: ["agent-persistence", "sse-events", "fastapi", "nextjs", "app-business-analysis"] },
    ],
  },
];

export const ARCHITECTURE_MODEL: ArchitectureModel = {
  title: "AI 数据智能平台技术与业务全景",
  subtitle: "从工程底座、数据与模型资源到 Agent 编排和当前业务应用",
  layers,
  nodes,
  edges,
  workflows,
  boundaries: [
    "当前业务数据为零售样例，用于完整演示数据、知识与 Agent 链路。",
    "会话使用匿名浏览器标识，不包含企业级统一身份认证。",
    "当前未实现生产级租户隔离、细粒度数据权限和审计治理。",
  ],
};

export function validateArchitecture(model: ArchitectureModel): string[] {
  const errors: string[] = [];
  const layerIds = new Set<string>();
  const layerOrders = new Set<number>();
  const nodeIds = new Set<string>();
  const edgeIds = new Set<string>();
  const workflowIds = new Set<string>();

  for (const layer of model.layers) {
    if (layerIds.has(layer.id)) errors.push(`Duplicate layer id: ${layer.id}`);
    if (layerOrders.has(layer.order)) errors.push(`Duplicate layer order: ${layer.order}`);
    layerIds.add(layer.id);
    layerOrders.add(layer.order);
  }

  for (const node of model.nodes) {
    if (nodeIds.has(node.id)) errors.push(`Duplicate node id: ${node.id}`);
    nodeIds.add(node.id);
    if (!layerIds.has(node.layerId)) {
      errors.push(`Unknown layer ${node.layerId} for node ${node.id}`);
    }
  }

  for (const edge of model.edges) {
    if (edgeIds.has(edge.id)) errors.push(`Duplicate edge id: ${edge.id}`);
    edgeIds.add(edge.id);
    if (!nodeIds.has(edge.source)) errors.push(`Unknown source ${edge.source} for edge ${edge.id}`);
    if (!nodeIds.has(edge.target)) errors.push(`Unknown target ${edge.target} for edge ${edge.id}`);
  }

  for (const workflow of model.workflows) {
    if (workflowIds.has(workflow.id)) errors.push(`Duplicate workflow id: ${workflow.id}`);
    workflowIds.add(workflow.id);
    const workflowNodeIds = new Set(workflow.nodeIds);
    const connectedNodeIds = new Set<string>();
    const stepIds = new Set<string>();

    for (const nodeId of workflow.nodeIds) {
      if (!nodeIds.has(nodeId)) errors.push(`Unknown node ${nodeId} in workflow ${workflow.id}`);
    }
    for (const edgeId of workflow.edgeIds) {
      if (!edgeIds.has(edgeId)) {
        errors.push(`Unknown edge ${edgeId} in workflow ${workflow.id}`);
        continue;
      }
      const edge = model.edges.find((candidate) => candidate.id === edgeId);
      if (!edge) continue;
      if (!workflowNodeIds.has(edge.source) || !workflowNodeIds.has(edge.target)) {
        errors.push(`Edge ${edgeId} leaves workflow ${workflow.id}`);
        continue;
      }
      connectedNodeIds.add(edge.source);
      connectedNodeIds.add(edge.target);
    }
    for (const step of workflow.steps) {
      if (stepIds.has(step.id)) {
        errors.push(`Duplicate step id ${step.id} in workflow ${workflow.id}`);
      }
      stepIds.add(step.id);
      for (const nodeId of step.nodeIds) {
        if (!nodeIds.has(nodeId)) {
          errors.push(`Unknown node ${nodeId} in workflow step ${step.id}`);
        }
        if (!workflowNodeIds.has(nodeId)) {
          errors.push(`Node ${nodeId} in step ${step.id} is not part of workflow ${workflow.id}`);
        }
      }
    }
    for (const nodeId of workflow.nodeIds) {
      if (nodeIds.has(nodeId) && !connectedNodeIds.has(nodeId)) {
        errors.push(`Node ${nodeId} is disconnected in workflow ${workflow.id}`);
      }
    }
  }

  return errors;
}
