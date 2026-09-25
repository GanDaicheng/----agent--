# InsightFlow 数据智能 Agent 平台 · 前端

面向多业务场景的数据资产与智能应用平台。四个真实功能页，其余是说明页。

基于 Next.js 16 + React 19 + TypeScript（App Router）。

## 启动

```powershell
npm install      # 首次克隆后执行一次
npm run dev
```

访问 http://localhost:3000

## 常用命令

| 命令 | 说明 |
| --- | --- |
| `npm run dev` | 启动开发服务（默认 3000 端口，支持热更新） |
| `npm run build` | 生产构建 |
| `npm run start` | 以生产模式启动，需先执行 `build` |
| `npm run lint` | 运行 ESLint 检查（Next 16 用 ESLint CLI，没有 `next lint`） |
| `npx tsc --noEmit` | 只做类型检查，不产出文件 |
| `npx next typegen` | 重新生成路由类型（删改路由后 `.next/types` 会过期，用它刷新） |

## 路由

| 路径 | 页面 | 是否调后端 |
| --- | --- | :---: |
| `/` | 平台总览：三个核心功能、三层能力、两条链路 | 否 |
| `/data/sources` | **数据采集**：上传知识文档、看已入库列表 | 是 |
| `/data/warehouse` | **数据仓库**：五张样例表、表关系、数据入口 | 否 |
| `/ai/knowledge` | 知识库与 RAG 说明页 | 否 |
| `/ai/agents` | Agent 中心说明页 | 否 |
| `/applications/data-query` | **智能问数**：中文提问，查业务数据 | 是 |
| `/applications/knowledge-qa` | **知识问答**：问业务口径，检索知识文档 | 是 |
| `/applications/business-analysis` | **经营分析**：多轮 Agent Loop、工具调用、历史恢复 | 是 |
| `/architecture` | **技术栈与架构**：技术栈、系统结构、数据流转 | 否 |

两个说明页（`/ai/knowledge`、`/ai/agents`）由同一个模板
`components/platform/ModulePage.tsx` 渲染，内容来自配置，动态路由段是
`app/ai/[module]/`；配置里没有的 slug 返回 404。

四个功能页各自有独立静态路由（`app/<section>/<slug>/page.tsx`），
不再走动态路由段——它们的内容形态和模板页差别太大，硬套一个模板只会互相迁就。

## 目录说明

```
src/
  app/
    layout.tsx                     # 根布局：全局 metadata + 平台外壳
    page.tsx                       # 平台总览
    not-found.tsx                  # 404
    globals.css                    # 全局设计令牌（见下）
    ai/[module]/page.tsx           # 说明页的动态路由段（模板页）
    data/sources/                  # 数据采集：路由 + 工作台
    data/warehouse/                # 数据仓库：路由 + 样式
    applications/data-query/       # 智能问数：路由（组件在 components/data-query/）
    applications/knowledge-qa/     # 知识问答：路由 + 工作台
    architecture/                  # 技术栈与架构
  components/
    ui/                            # 跨页面复用的轻量组件
      Button.tsx                   # Button + LinkButton（共用同一个样式模块）
      Notice.tsx                   # 五档语义提示（info/success/warning/danger/neutral）
      EmptyState.tsx               # 空态
      LoadingIndicator.tsx         # 不确定进度 + 可选取消
      PageHeader.tsx               # 面包屑 + 标题 + 使用边界
    platform/                      # 平台外壳与展示组件
      PlatformShell.tsx            # 顶栏 + 侧栏 + 内容区（外壳层唯一客户端组件）
      Sidebar.tsx / Topbar.tsx
      ServiceHealthCheck.tsx       # 顶栏的「检查服务」按钮（客户端）
      ModulePage.tsx               # 说明页模板
      ModuleRoutePage.tsx          # 动态路由参数 → 模块配置
      FlowDiagram.tsx              # 竖向流程图（架构页用，支持并列分支）
      ErDiagram.tsx                # 简化 ER 图 + 关系文字说明
      CapabilityCard.tsx / StatusBadge.tsx / WorkflowChain.tsx
      DataSourceNote.tsx           # 静态数据标记
    data-query/                    # 智能问数组件
      DataQueryWorkspace.tsx       # 唯一持有状态的客户端组件
      QuestionInput.tsx            # 输入、计数、示例、快捷键
      QueryResultPanel.tsx         # 结果区编排（结论→图表→表格→执行记录→知识资料）
      ResultTable.tsx              # 明细表
      ResultChart.tsx              # SVG 折线 / CSS 柱状，含安全降级
      AgentEventTimeline.tsx       # 公开执行步骤
      format.ts                    # 数值格式化（表格与图表共用）
  features/platform/
    platform-config.ts             # 信息架构的唯一数据源（导航、模块、能力、路由常量）
    retail-tables.ts               # 样例数仓的表结构与关系（数据仓库页 + 架构页共用）
  mocks/
    platform-overview.ts           # 首页两条链路的步骤文案
  lib/api/
    http.ts                        # 共用请求基础设施：URL 构造、取消判断、对象判断
    health.ts                      # 健康检查（GET /api/v1/health）
    agent-data-query.ts            # 智能问数（POST /api/v1/agent/data-query）
    rag-answer.ts                  # 知识问答（POST /api/v1/rag/answer）
    rag-documents.ts               # 文档上传与列表（POST/GET /api/v1/rag/documents）
legacy-static/
  index.html                       # 初始化 Next.js 之前使用的静态聊天页，保留备查
```

## 设计令牌

全部集中在 `src/app/globals.css` 的 `:root`，分三层，不要混用：

| 组 | 令牌 | 用途 |
| --- | --- | --- |
| 中性色 | `--bg` `--surface` `--border` `--text` `--text-muted` … | 页面底色、卡片、边框、文字 |
| 主操作色 | `--primary` `--primary-hover` `--primary-soft` `--primary-border` | 全站唯一的「可以点这里」颜色：主按钮、链接、焦点环、当前导航项 |
| 语义状态色 | `--success` `--warning` `--danger` `--info`（各带 `-soft` / `-border`） | 表达「好 / 注意 / 出错 / 提示」 |
| 分层色 | `--layer-business` `--layer-data` `--layer-ai` `--layer-app` | **只用于类别识别**：数据中台绿、AI 中台紫、智能应用深蓝 |
| 建设状态色 | `--status-done` `--status-building` `--status-planned` | 模块的已完成 / 建设中 / 待接入 |
| 间距与字号 | `--space-1..8`、`--text-xs..title` | 统一尺度，避免各页面手写 px 漂移 |

两条约定：

- **语义状态色与建设状态色是两回事。** 一个模块「已建成」不叫「成功」，
  一个模块「待接入」也不是「出错」。它们刻意分开取名。
- **本轮只做浅色主题。** 唯一例外是架构页的系统架构图——那是一块深色面板，
  作为整页的视觉重点，配色写在 `FlowDiagram.module.css` 的 `[data-tone="dark"]` 里，
  没有引入全局暗色模式。

## 当前状态与数据边界

四个页面会真实调用后端，其余页面是静态配置驱动的说明页。

| 页面 | 接口 | 说明 |
| --- | --- | --- |
| `/data/sources` | `POST` / `GET /api/v1/rag/documents` | 上传会真实调用 embedding 并写库 |
| `/applications/knowledge-qa` | `POST /api/v1/rag/answer` | 每次提问花一次 embedding + 一次模型调用 |
| `/applications/data-query` | `POST /api/v1/agent/data-query` | 每次提问花一次模型调用并读数据库 |
| `/applications/business-analysis` | `POST /api/v1/agent/business-analysis/runs`（SSE） | 多步调用问数、知识检索和报告工具 |

共同约定（改造时请保留）：

- 后端地址由当前页面的协议 + 主机名 + `8000` 端口拼出，不写死 IP
  （见 `lib/api/http.ts`）。因此后端必须允许来自 `http://localhost:3000`
  与 `http://127.0.0.1:3000` 的跨域请求，见项目根 `README.md` 的 CORS 说明。
- **页面首次打开不发起任何请求。** 只有用户点了按钮（或按 `Ctrl / Cmd + Enter`）
  才发出去。文档上传成功后自动刷新一次列表，那是用户上传操作的延续。
- 请求用 `AbortController` 取消，组件卸载时清理；取消、失败、空结果**各有独立展示**。
- 响应在客户端做结构校验，形状不对就报「内容无法识别」，不把野数据渲染出去。
- 模型输出一律按**纯文本**渲染（`white-space: pre-wrap`），从不使用
  `dangerouslySetInnerHTML`。
- 不展示 SQL 原文、表名字段名、内部状态、异常堆栈或连接信息。
- 每个状态都是**颜色 + 文字**双通道表达，不靠颜色单独传达信息。

### 顶栏的「检查服务」

点击后调用 `GET /api/v1/health`，只探测**后端进程与 PostgreSQL 连接**两件事，
**不自动轮询**。它不覆盖模型服务与 embedding 服务——那两个是外部供应商，
后端不探测它们。这个状态与侧边栏的「已完成 / 建设中 / 待接入」也不是一回事：
前者是实时探测结果，后者是人工维护的功能建设进度。

### 静态说明页

- 不调用任何后端接口，也不连接数据库。
- 展示内容来自 `features/platform/platform-config.ts` 与
  `features/platform/retail-tables.ts` 的静态配置，
  凡是渲染静态数据的位置都会显示「静态数据 · 非实时运行数据」标记。
- 「零售」只是当前用来把链路跑通的演示业务。凡是展示零售样例数据的位置
  都带一句「当前使用零售样例数据，后续可扩展到其他业务场景」
  （统一取自配置里的 `RETAIL_DATA_NOTE`）。
- **维护提示**：`platform-config.ts` 里每一句「当前能力」都必须能在代码或接口里
  找到对应物。只登记已经真实可用的能力——写进侧边栏就等于承诺一个能点开的页面。
  曾经出现过的偏差都是同一类：功能还没上线，配置先写了，于是页面在说谎。

后端启动方式见项目根目录的 `README.md`。
