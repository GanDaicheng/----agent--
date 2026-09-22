# 数据中台 Agent 智能问数工作台

一个作品集级的数据中台 Agent 项目：用自然语言提问（例如“近六个月销售额趋势如何”），
系统检索指标口径与数据目录、生成安全 SQL、查询数据仓库，最后返回结论与图表。

## 项目目标

把「问数」这件事做成一条可观测、可追溯的链路：

1. 理解用户问题，识别涉及的指标与维度
2. 检索指标语义层和数据目录，确定口径与可用表
3. 生成受约束的安全 SQL（只读、限定表、限定行数）
4. 执行查询，取回数据
5. 输出结论文本和图表，并记录本次运行过程

## 当前技术栈

| 层次 | 技术 | 状态 |
| --- | --- | --- |
| 后端服务 | FastAPI + Uvicorn | 已接入 |
| Agent 编排 | LangChain / LangGraph | 已接入 |
| 模型接入 | OpenAI 兼容接口（DeepSeek / Qwen / OpenAI） | 已接入 |
| 数据存储 | PostgreSQL 16 | 已接入，尚未创建零售业务表 |
| 数据访问 | SQLAlchemy 2.x（异步）+ asyncpg | 已接入，目前仅连接自检 |
| 前端工作台 | Next.js 16 + TypeScript（App Router） | 已容器化，尚未调用后端 API |
| 本地环境 | Docker Compose | 已接入：PostgreSQL + FastAPI + Next.js 三服务一键启动 |

## 目录结构

```
backend/
  app/
    main.py           # FastAPI 应用入口，负责组装和挂载路由
    api/              # HTTP 路由层，协议定义与请求校验
    agent/            # LangGraph 编排、工具注册、提示词
    core/             # 配置、日志、异常、路径等基础设施
    models/           # 数据库 ORM 模型（待填充）
    services/         # 业务服务层：database_health.py 提供数据库连接自检
    repositories/     # 数据访问层：database.py 管理异步引擎与连接，不含表结构
  Dockerfile          # 后端生产镜像：python:3.14-slim + requirements.txt + app/
  tests/              # 后端自动化测试（健康检查接口）
  requirements-dev.txt# 仅开发/测试依赖，不进生产镜像
frontend/
  src/app/            # Next.js App Router：layout.tsx、page.tsx 与样式
  public/             # 静态资源目录（当前为空，占位保留）
  legacy-static/      # 初始化 Next.js 之前的静态聊天页，保留备查
  Dockerfile          # 前端生产镜像：多阶段构建 + standalone 产物
  package.json
docker-compose.yml    # 三服务编排：postgres + backend + frontend
.dockerignore         # 构建上下文排除清单，确保 .env 不进镜像
requirements.txt
.env.example
```

分层约定：`api` 只处理 HTTP，`services` 承担业务逻辑，`repositories` 只碰数据库，
`agent` 负责编排模型与工具。跨层调用方向为 `api → services → repositories`。

## 一键启动全部服务（Docker）

三个服务——PostgreSQL、FastAPI 后端、Next.js 前端——都由 Docker Compose 编排，
一条命令即可全部启动。**所有命令都要在项目根目录执行。**

启动顺序不是「一起启动」，而是由健康检查串成一条链，每一环都等前一环真的可用：

```
postgres healthy  →  backend healthy  →  frontend healthy
```

所以后端不会比数据库先起来，前端也不会在后端就绪前启动。

### 首次启动，或依赖有变化时

```powershell
docker compose up --build
```

`--build` 表示先重新构建镜像。**凡是改了 `requirements.txt`、`frontend/package.json`
或任何 Dockerfile，都必须带上它**，否则容器里跑的还是旧镜像。

这条命令会把三个服务的日志持续输出到当前终端。按 `Ctrl+C` 停止服务，
**数据 volume 会保留**，下次启动数据还在。

### 后台启动

```powershell
docker compose up --build -d
```

`-d` 是 detached，服务在后台运行，终端立刻可以继续用。

### 查看服务与健康状态

```powershell
docker compose ps
```

正常情况下 `postgres`、`backend`、`frontend` 的 `STATUS` 列都应该显示 `healthy`。
刚启动时可能显示 `starting`，等十几秒再看。

### 查看日志

```powershell
docker compose logs -f backend
docker compose logs -f frontend
docker compose logs -f postgres
```

`-f` 持续跟踪输出；按 `Ctrl+C` 只退出日志查看，**不会停掉服务**。

### 停止服务但保留数据

```powershell
docker compose down
```

`down` 会**删除容器和网络，但不会删除 PostgreSQL 数据卷** `postgres_data`。
下次 `docker compose up` 时数据仍然在。平时收工用这条就够了。

### 清空本地数据库（危险命令）

```powershell
docker compose down -v
```

> **警告**：`-v` 会连同具名 volume `postgres_data` 一起删除，
> **本地数据库的所有数据都会丢失**，下次启动是一个全新的空库。

只有在明确需要从头初始化时才使用——例如改了 `POSTGRES_USER` 或 `POSTGRES_PASSWORD`，
因为这两个变量只在 volume 首次创建时生效。

### 访问地址

```text
前端：        http://localhost:3000
后端文档：    http://localhost:8000/docs
后端健康检查：http://localhost:8000/api/v1/health
```

两个健康接口的分工：

- `/api/v1/health` 是 **Docker Compose 的后端就绪检查**。Compose 用它判断 backend
  容器能否对外服务，前端容器也要等它通过才会启动。
- `/health/db` 是**保留的数据库连接自检接口**，适合后端跑在 Windows 宿主机时排查数据库连接。

两者在数据库可用时返回 `200`，代表后端与 PostgreSQL 都能正常通信；
数据库不可用时返回 `503`。

### 容器里的数据库连接串

backend 容器用的连接串是 `DATABASE_URL_DOCKER`，它的主机名是 Compose 服务名 `postgres`。
**不能用 `DATABASE_URL`**——那是给宿主机上的后端用的，主机名是 `localhost`，
而容器里的 `localhost` 只代表容器自己。

这两个变量都从项目根目录的 `.env` 读取。`.env.example` 只提供**不含真实密钥的安全示例**，
复制成 `.env` 后再填自己的值。**`.env` 已被 `.gitignore` 忽略，不要提交到 Git。**

## 本地启动后端

> **启动顺序：先启动 PostgreSQL，再启动 FastAPI。**
> 数据库没起来后端一样能启动（连接是懒加载的），但 `/health/db` 会返回 503。
> 完整的启动顺序是：
>
> ```powershell
> docker compose up -d postgres    # 1. 先在项目根目录起数据库
> docker compose ps                # 2. 等到 STATUS 显示 healthy
> cd backend                       # 3. 再起后端
> uvicorn app.main:app --reload
> ```

### 1. 准备虚拟环境

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

### 2. 配置模型

```powershell
Copy-Item .env.example .env
```

编辑 `.env`，把 `OPENAI_API_KEY` 换成真实密钥。默认指向 DeepSeek，
换成通义千问或 OpenAI 只需改 `OPENAI_BASE_URL` 和 `MODEL_NAME`，代码不用动。

### 3. 启动服务

必须在 `backend/` 目录下启动，保证 `app` 是根级包：

```powershell
cd backend
uvicorn app.main:app --reload
```

接口地址：

- 服务说明：http://127.0.0.1:8000/ （返回 JSON，**不再提供 HTML 页面**）
- 接口文档：http://127.0.0.1:8000/docs
- 健康检查：http://127.0.0.1:8000/api/v1/health
- 数据库自检：http://127.0.0.1:8000/health/db

### 4. 数据库连接自检

`GET /health/db` 只执行一条 `SELECT 1`，用来确认「Python 驱动 → 连接串 → 账号密码 →
宿主机端口映射 → PostgreSQL 容器」这条链路是通的。它不读任何业务表。

连接正常时返回 `200`：

```json
{
  "status": "ok",
  "database": "connected"
}
```

数据库连不上时返回 `503`，并给出结构化的错误，不会带上连接串或密码：

```json
{
  "status": "error",
  "database": "unavailable",
  "error_type": "ConnectionRefusedError",
  "message": "无法连接数据库，请确认 PostgreSQL 容器已启动且 DATABASE_URL 配置正确。"
}
```

如果是 `DATABASE_URL` 本身没配或格式不对，会返回 `500` 并在 `detail` 里说明该怎么改。
响应中的 `error_type` 是异常类名（如 `ConnectionRefusedError`、`InvalidPasswordError`），
足够定位问题，同时避免把凭据信息带出去。

## 本地 PostgreSQL（只用 Docker 跑数据库）

> 这一节是**宿主机开发**用的：只把数据库放进容器，后端仍跑在 Windows 宿主机上，
> 两者通过 `localhost:5432` 通信。想三个服务全在容器里跑，用上面的
> 「一键启动全部服务（Docker）」。
>
> 之所以保留这条路：改后端代码时 `uvicorn --reload` 的热重载比重建镜像快得多。

所有命令都要在**项目根目录**执行。

### 启动

```powershell
docker compose up -d postgres
```

首次启动会初始化数据库，大约十秒后进入健康状态。

### 检查状态

```powershell
docker compose ps
```

`STATUS` 列显示 `Up ... (healthy)` 即表示已能接受连接。
如果显示 `starting`，等几秒再看；显示 `unhealthy` 则用下面的日志命令排查。

```powershell
docker compose logs postgres        # 查看日志
docker compose exec postgres pg_isready -U data_platform -d data_platform
```

想直接连进数据库执行 SQL：

```powershell
docker compose exec postgres psql -U data_platform -d data_platform
```

### 停止

```powershell
docker compose stop postgres    # 只停容器，数据完整保留
docker compose down             # 删除容器和网络，数据仍然保留
```

日常开发用 `stop` 就够，下次 `docker compose up -d postgres` 会接着用原来的数据。

### 清空本地数据

```powershell
docker compose down -v
```

`-v` 会连同具名 volume 一起删除，**数据库里的所有数据都会丢失**，下次启动是全新的空库。
只有在想从头重来（比如改了初始化配置、想重跑建表脚本）时才用它。

### 数据库连接信息

| 项 | 值 |
| --- | --- |
| 主机 | `localhost` |
| 端口 | `5432` |
| 数据库 | `POSTGRES_DB`，默认 `data_platform` |
| 用户名 | `POSTGRES_USER`，默认 `data_platform` |
| 密码 | `POSTGRES_PASSWORD`，默认 `data_platform_dev` |

这三个变量在 `.env` 中配置，会被 `docker-compose.yml` 读取。
**注意它们只在 volume 首次创建时生效**：想改用户名或密码，必须先 `docker compose down -v`
清空数据再启动，否则改不动。

## 本地启动前端

前端是独立的 Next.js 工程，与后端分开启动。

```powershell
cd frontend
npm install      # 首次克隆后执行一次
npm run dev
```

访问 http://localhost:3000，开发服务默认使用 3000 端口，支持热更新。

停止服务：在运行 `npm run dev` 的终端按 `Ctrl+C`。

生产构建：

```powershell
npm run build    # 生成产物到 .next/
npm run start    # 以生产模式启动，需先 build
```

### 当前前端状态

前端**已完成工程初始化并容器化**（见 `frontend/Dockerfile`），首页仍是占位页面。
它目前**不会请求后端接口**，因此不需要先启动 FastAPI 或 PostgreSQL 也能正常打开。

尚未做的事（属于后续阶段）：调用后端接口、配置跨域（CORS）、聊天界面、
图表展示。后端接口清单见本文档「本地启动后端」一节。

## 本地环境注意事项

- 项目使用 `zoneinfo` 处理时区，Windows 系统不自带时区数据库，
  因此 `requirements.txt` 中显式依赖 `tzdata`，请勿删除。
- `.env` 已被 `.gitignore` 忽略，请勿提交真实密钥或数据库密码。
- 数据库密码如果含有 `$` 符号，在 `.env` 中要写成 `$$`，
  否则 Docker Compose 会把它当成变量插值而解析出错。
- `DATABASE_URL` 的驱动部分必须写成 `postgresql+asyncpg://`，**不能只写 `postgresql://`**。
  后端用的是异步 SQLAlchemy，环境里只装了 asyncpg；写成 `postgresql://` 时 SQLAlchemy
  会去找从未安装的同步驱动 psycopg2，报错信息也不会指向真正原因。
- 数据库主机名取决于后端跑在哪里，**两种跑法用的是两个不同的变量**：

  后端跑在 Windows 宿主机时使用 `DATABASE_URL`，数据库主机名为 `localhost`；
  后端跑在 Docker Compose 时使用 `DATABASE_URL_DOCKER`，数据库主机名为 `postgres`。
  两者不能混用，因为容器中的 `localhost` 只代表容器自身。

  两个变量都写在项目根目录的 `.env` 里，`.env.example` 只提供不含真实密钥的示例值。
  `.env` 已被 `.gitignore` 忽略，请勿提交。

## 开发路线

- [x] 阶段一：最小可运行后端（FastAPI + Agent + 模型接入）
- [x] 阶段二：工程骨架整理，分层目录落地
- [x] 阶段三：Docker Compose 与 PostgreSQL 本地环境
- [x] 阶段三·补：SQLAlchemy 异步引擎接入与数据库连接自检（`/health/db`）
- [x] 阶段四：Next.js + TypeScript 前端工程初始化（占位首页）
- [x] 阶段四·补：三服务容器化（后端/前端生产镜像 + Compose 健康依赖链 + 统一健康检查 `/api/v1/health`）
- [ ] 阶段五：Alembic 初始化配置与零售样例数仓
- [ ] 阶段六：数据目录与指标语义层
- [ ] 阶段七：安全 SQL 生成与查询执行
- [ ] 阶段八：运行记录与可观测性
- [ ] 阶段九：前端问数工作台（图表与交互）
