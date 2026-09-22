# 数据中台 Agent · 前端

智能问数工作台的前端工程，基于 Next.js + TypeScript（App Router）。

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

## 目录说明

```
src/app/
  layout.tsx          # 根布局，定义全局 metadata 与 <html lang>
  page.tsx            # 首页占位页
  page.module.css     # 首页样式（CSS Modules）
  globals.css         # 全局样式与设计变量
legacy-static/
  index.html          # 初始化 Next.js 之前使用的静态聊天页，保留备查
```

## 当前状态

本工程**只完成初始化**：尚未接入后端接口，没有配置跨域，也没有实现聊天、
图表与数据库相关功能。后续会改为调用 FastAPI 的 `/chat` 与 `/health/db`。

后端启动方式见项目根目录的 `README.md`。
