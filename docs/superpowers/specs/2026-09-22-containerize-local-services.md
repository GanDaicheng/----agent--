# 第 2 步规格：本地三服务容器化

## 目标

将已有的 PostgreSQL、FastAPI 后端和 Next.js 前端统一交给 Docker Compose 编排。开发者在项目根目录执行 `docker compose up --build` 后，可通过宿主机端口访问前端、后端文档和后端统一健康检查。

## 已有基础

- 根目录 `docker-compose.yml` 已有 `postgres` 服务、具名数据卷和健康检查。
- FastAPI 位于 `backend/app`；数据库自检端点为 `GET /health/db`。
- Next.js 位于 `frontend`，使用 Next.js 16、TypeScript、App Router，目前不调用后端。
- 根目录 `.env` 存放真实模型密钥与本机数据库连接配置，不能复制到镜像或提交到 Git。

## 本阶段交付物与约束

1. 创建后端和前端生产 Dockerfile，并在 Compose 中加入 `backend`、`frontend` 服务。
2. 新增 `GET /api/v1/health`；数据库可用时 200，不可用时 503；保留 `/health/db`。
3. 后端等待 `postgres` healthy，前端等待 `backend` healthy。
4. 容器内后端使用主机名 `postgres`，宿主机后端继续使用 `localhost`。
5. 不复制 `.env`，不加入 CORS、前端 API 调用、业务表、迁移或 Agent 功能。
