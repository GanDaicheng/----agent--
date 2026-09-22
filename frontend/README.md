# 零售企业智能化平台 · 前端

业务中台 / 数据中台 / AI 中台 / 智能应用 四层架构的前端控制台，
基于 Next.js + TypeScript（App Router）。

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
| `npm run lint` | 运行 ESLint 检查 |

## 路由

| 路径 | 页面 |
| --- | --- |
| `/` | 平台总览：分层链路、建设进度、已完成能力、下一步路线 |
| `/business/[module]` | 客户中心、商品中心、订单中心、库存中心 |
| `/data/[module]` | 数据采集、数据治理、数据仓库、指标中心、数据服务 |
| `/ai/[module]` | 模型与 Prompt、知识库与 RAG、Agent 中心、工作流与工具、AI 运营 |
| `/applications/[module]` | 经营驾驶舱 |
| `/applications/data-query` | 智能问数（独立静态路由，见下） |

四个 `/xxx/[module]` 路由段共用同一个页面模板，合法 `module` 由配置决定；
配置里没有的模块返回 404。

`/applications/data-query` 有**自己的静态路由**（`app/applications/data-query/page.tsx`），
因为它是一个可交互的真实页面，不是通用的建设说明页。静态路由优先于动态路由，
所以 `applications/[module]/page.tsx` 的 `generateStaticParams` 把它排除了——
否则同一条路径会被两边各预渲染一遍。

## 目录说明

```
src/
  app/
    layout.tsx                     # 根布局：全局 metadata + 平台外壳
    page.tsx                       # 平台总览
    not-found.tsx                  # 404
    business/[module]/page.tsx     # 四个路由段，各自只做参数解析
    data/[module]/page.tsx
    ai/[module]/page.tsx
    applications/[module]/page.tsx
    applications/data-query/page.tsx  # 智能问数：独立静态路由，唯一可交互页面
    globals.css                    # 全局设计令牌（分层色 / 状态色）
  components/platform/             # 平台外壳与可复用展示组件
    PlatformShell.tsx              # 顶栏 + 侧栏 + 内容区（唯一客户端组件）
    Sidebar.tsx / Topbar.tsx
    LayerFlow.tsx                  # 总览页的分层能力链路
    ModulePage.tsx                 # 二级模块页面模板
    ModuleRoutePage.tsx            # 动态路由参数 → 模块配置
    CapabilityCard.tsx / StatusBadge.tsx / WorkflowChain.tsx
    DataSourceNote.tsx             # 静态数据标记
  components/data-query/           # 智能问数页面组件
    DataQueryWorkspace.tsx         # 唯一持有状态的客户端组件
    QuestionInput.tsx              # 输入、计数、示例、快捷键
    QueryLoadingState.tsx          # 分步加载状态 + 取消
    QueryResultPanel.tsx           # 结果区编排
    ResultTable.tsx                # 明细表
    ResultChart.tsx                # SVG 折线 / CSS 柱状，含安全降级
    AgentEventTimeline.tsx         # 公开执行步骤
    format.ts                      # 数值格式化（表格与图表共用）
    data-query.module.css
  features/platform/
    platform-config.ts             # 路由、状态、能力说明、依赖关系的唯一数据源
  mocks/
    platform-overview.ts           # 总览页的静态展示数据
  lib/api/
    contracts.ts                   # 数据中台侧的类型边界
    agent-data-query.ts            # 智能问数接口客户端（类型 + fetch + 错误映射）
legacy-static/
  index.html                       # 初始化 Next.js 之前使用的静态聊天页，保留备查
```

## 当前状态与数据边界

平台骨架页面仍全部是静态配置驱动的，**只有智能问数页面会发网络请求**。

### 智能问数页面（`/applications/data-query`）

这是本工程唯一会调用后端的页面：

- 请求发往 `POST /api/v1/agent/data-query`（后端 FastAPI）。
- 后端地址由当前页面的协议 + 主机名 + `8000` 端口拼出，不写死 IP。
  因此后端必须允许来自 `http://localhost:3000` 与 `http://127.0.0.1:3000`
  的跨域请求，见项目根 `README.md` 的 CORS 说明。
- **页面首次打开不发起任何请求**，只有点击「开始分析」或按 `Ctrl / Cmd + Enter`
  才提交；不保存问题历史，也不使用 localStorage。
- 每次有效提问都会**真实调用模型服务**，请不要输入敏感信息，
  也不要在自动化验证里随便提交问题。
- 页面展示的结论、明细表和图表**全部来自接口返回**。前端不生成 SQL、
  不推断执行步骤、不猜字段；字段对不上时图表安全降级为只显示明细表。
- 图表用原生 SVG（折线）和 CSS（横向柱状）实现，没有引入任何图表库。

### 其余页面

- 不调用任何后端接口，也不连接数据库。
- 展示内容来自 `features/platform/platform-config.ts` 与 `src/mocks/` 的静态配置，
  凡是渲染静态数据的位置都会显示「静态数据 · 非实时运行数据」标记。
- 模块状态只有三种：已完成 / 建设中 / 待接入。
- `lib/api/contracts.ts` 声明的是数据中台侧的类型边界；
  智能问数用的类型在同目录的 `lib/api/agent-data-query.ts`。

后端启动方式见项目根目录的 `README.md`。
