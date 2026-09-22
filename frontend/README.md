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
| `/applications/[module]` | 经营驾驶舱、智能问数 |

四个 `/xxx/[module]` 路由段共用同一个页面模板，合法 `module` 由配置决定；
配置里没有的模块返回 404。

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
    globals.css                    # 全局设计令牌（分层色 / 状态色）
  components/platform/             # 平台外壳与可复用展示组件
    PlatformShell.tsx              # 顶栏 + 侧栏 + 内容区（唯一客户端组件）
    Sidebar.tsx / Topbar.tsx
    LayerFlow.tsx                  # 总览页的分层能力链路
    ModulePage.tsx                 # 二级模块页面模板
    ModuleRoutePage.tsx            # 动态路由参数 → 模块配置
    CapabilityCard.tsx / StatusBadge.tsx / WorkflowChain.tsx
    DataSourceNote.tsx             # 静态数据标记
  features/platform/
    platform-config.ts             # 路由、状态、能力说明、依赖关系的唯一数据源
  mocks/
    platform-overview.ts           # 总览页的静态展示数据
  lib/api/
    contracts.ts                   # 未来数据服务的类型边界（本阶段不发请求）
legacy-static/
  index.html                       # 初始化 Next.js 之前使用的静态聊天页，保留备查
```

## 当前状态与数据边界

本工程处于**阶段 1：全平台前端骨架**。

- 页面不调用任何后端接口，不连接数据库，也不调用 Agent。
  源码中没有 `fetch` 或其他网络请求。
- 所有展示内容来自 `features/platform/platform-config.ts` 与 `src/mocks/` 的静态配置，
  凡是渲染静态数据的位置都会显示「静态数据 · 非实时运行数据」标记。
- 模块状态只有三种：已完成 / 建设中 / 待接入。只有 AI 中台的 Agent 中心标记为已完成，
  且页面明确说明它当前使用模拟资产与模拟查询结果。
- `lib/api/contracts.ts` 只声明将来要对接的数据结构，为后续接入 FastAPI 预留边界。

后端启动方式见项目根目录的 `README.md`。
