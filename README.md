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

## 零售样例数据底座

数据中台阶段的第 1 小步：把空的 PostgreSQL 容器变成**可真实执行零售分析 SQL 的样例数据底座**。

### 五张表

四张维度表 + 一张订单事实表：

| 表 | 类型 | 主键 | 说明 |
| --- | --- | --- | --- |
| `customers` | 维度 | `customer_id` | 客户与会员等级（普通/银卡/金卡/黑金） |
| `products` | 维度 | `product_id` | 商品、品类、单价（`Numeric(12,2)`，不用浮点） |
| `regions` | 维度 | `region_id` | 区域，`region_name` 唯一 |
| `date_dim` | 维度 | `date_id`（YYYYMMDD） | 覆盖 2025 全年 365 天，`full_date` 唯一 |
| `orders` | 事实 | `order_id` | 订单明细，外键关联上面四张表 |

`orders` 只存订单明细这一层的原始粒度，**不存任何聚合结果**——月度、区域、商品、会员的汇总
全部由 SQL 现场算出来，这样数据中台才是「可真实分析」的。

金额口径（数据库层用 CHECK 约束钉死）：

```text
gross_amount    = quantity × unit_price
net_amount      = gross_amount - discount_amount
discount_amount ≤ gross_amount
```

### 初始化与验证

三个命令都在 `backend/` 目录下执行，且都会读取项目根 `.env` 里的 `DATABASE_URL`：

```powershell
cd backend

# 1. 建表（迁移）
python -m alembic upgrade head
python -m alembic current

# 2. 写入样例数据（幂等，可重复执行）
python scripts/seed_retail_data.py

# 3. 只读验证五类业务规律（不通过则退出码为 1）
python scripts/verify_retail_data.py
```

### 样例数据规模

| 表 | 行数 |
| --- | --- |
| `regions` | 4 |
| `customers` | 240 |
| `products` | 24（6 个品类） |
| `date_dim` | 365（2025-01-01 ~ 2025-12-31） |
| `orders` | 3404 |

### 业务规律由生成规则产生

样例数据不是随机数，也不是「生成后再手工改统计结果」：所有规律都来自
`app/services/retail_seed.py` 里的权重参数，固定随机种子，两次执行结果完全一致。

| 规律 | 产生方式 |
| --- | --- |
| 区域差异 | 区域权重 华东 0.38 > 华南 0.26 > 华北 0.20 > 华中 0.16 |
| 季节性 | 月份权重 11 月 2.10、12 月 2.50，普通月份约 1.0 |
| 热销商品 | `PRD005` / `PRD009` / `PRD013` 的抽样权重是普通商品的 8 倍 |
| 会员复购 | 分层抽样：黑金 0.95 > 金卡 0.84 > 银卡 0.62 > 普通 0.40 |

### 分析口径

```text
复购率 = 在统计周期内订单数 ≥ 2 的客户数 / 有订单的客户数
客单价 = 总净销售额 / 去重订单数
```

### 幂等性

`seed_retail_data.py` 写入时统一使用 `ON CONFLICT DO NOTHING`，且生成过程确定，
因此**重复执行不会产生重复数据**，第二次执行的「本次新增」应全部为 0。

### Alembic 与连接串

`backend/alembic.ini` 里**不含任何连接串**（`sqlalchemy.url` 一项被注释掉），
真实连接串只存在于项目根 `.env`，由 `backend/alembic/env.py` 在运行时通过
`app.core.config.get_settings()` 读取。

注意 `alembic.ini` 必须保持纯 ASCII：Alembic 会按操作系统区域编码读取该文件，
在中文 Windows 上按 GBK 解析，写入中文注释会直接抛 `UnicodeDecodeError`。

## 数据服务：受控只读查询接口

数据中台阶段的第 2 小步：提供一个受控的分析 SQL 查询服务，让调用方提交**经过严格限制的
只读 SELECT**，拿到结构化结果。它属于**数据中台**，与 AI 中台无关——
`app/services/safe_query.py` 不导入 `app.agent`、LangGraph 或任何模型 SDK，有测试用 AST 检查守住这条边界。

### 接口

```text
POST /api/v1/data/query
```

请求：

```json
{
  "sql": "SELECT date_dim.month, SUM(orders.net_amount) AS sales_amount FROM orders JOIN date_dim ON orders.date_id = date_dim.date_id GROUP BY date_dim.month ORDER BY date_dim.month LIMIT 12"
}
```

响应：

```json
{
  "columns": ["month", "sales_amount"],
  "rows": [{ "month": 1, "sales_amount": 140892.02 }],
  "row_count": 12,
  "source": "postgres"
}
```

`columns` 与 `rows` 中每个字典的键顺序一致，`row_count == len(rows)`，响应里**不含原始 SQL**。

### 两条防线

```text
调用方 SQL
→ 第 1 道：sqlglot AST 校验（validate_safe_select，纯函数）
→ 第 2 道：PostgreSQL 只读事务 + statement/lock timeout（run_readonly_query）
→ PostgreSQL
→ 限制行数的结构化结果
```

第 2 道不是摆设：即使绕过第 1 道直接把 `DELETE FROM orders` 交给执行层，
数据库也会以 `read_only_sql_transaction`（SQLSTATE 25006）拒绝，数据一行都不会变。

`SET TRANSACTION READ ONLY` 必须是事务里的第一条语句——PostgreSQL 规定它前面若已执行过查询，
只会发一个警告然后**静默忽略**只读设置，所以三条设置语句的顺序在代码里是固定的。

### 允许的内容

| 项 | 白名单 |
| --- | --- |
| 表 | `customers` `products` `regions` `date_dim` `orders` |
| 函数 | `COUNT` `SUM` `AVG` `MIN` `MAX`（含 `COUNT(DISTINCT ...)`） |
| 语句形态 | 单条 `SELECT`，`JOIN` / `WHERE` / `GROUP BY` / `ORDER BY` / `LIMIT` / `AS` 别名 |

字段白名单登记在 `safe_query.py` 的 `ALLOWED_COLUMNS`，字段必须写完整表名
（`orders.net_amount`，`net_amount` 会被拒绝）。`ORDER BY sales_amount` 这种引用输出别名的
标准写法是允许的——别名只能指向已经校验过的投影。

### 拒绝的内容

`INSERT` / `UPDATE` / `DELETE` / `MERGE` / `DROP` / `ALTER` / `CREATE` / `TRUNCATE` / `GRANT` /
`COPY` / `EXPLAIN`、多语句、SQL 注释、`SELECT *`、CTE、子查询、`UNION`、窗口函数、`CASE`、
未登记的表（含 `information_schema` / `pg_catalog`）、未登记的字段、未限定表名的字段、
白名单外的任何函数（`pg_sleep`、`current_setting`、`version()` 等）。

`LIMIT` **必须存在**且为 1~200 的整数字面量，缺失即拒绝——服务端不替调用方补 LIMIT，
否则调用方会误以为自己的查询没有上限。

### 状态码

| 场景 | 状态码 |
| --- | ---: |
| 合规查询执行成功 | 200 |
| 请求体缺少 `sql` 或长度非法 | 422 |
| SQL 未通过安全策略 | 422 |
| 已通过安全校验但语句执行失败（字段类型不符、超时被取消等） | 400 |
| 数据库不可用 | 503 |
| 服务端配置缺失、结果无法安全序列化 | 500 |

失败响应只回显**预定义的中文文案**（如「仅允许执行单条 SELECT 查询。」），
不回显原始 SQL、连接串、密码或数据库异常原文。

### 试一下

```powershell
# 趋势查询
curl -s -X POST http://localhost:8000/api/v1/data/query `
  -H "Content-Type: application/json" `
  -d '{\"sql\":\"SELECT date_dim.month, SUM(orders.net_amount) AS sales_amount FROM orders JOIN date_dim ON orders.date_id = date_dim.date_id GROUP BY date_dim.month ORDER BY date_dim.month LIMIT 12\"}'

# 危险语句：应返回 422
curl -s -X POST http://localhost:8000/api/v1/data/query `
  -H "Content-Type: application/json" -d '{\"sql\":\"DELETE FROM orders\"}'
```

接口与请求/响应模型可以在 http://localhost:8000/docs 中查看。

### 安全边界（务必阅读）

这是**本地开发原型**：接口**没有身份认证、没有权限控制、没有行级数据权限**，
任何能访问 8000 端口的人都可以查询这五张表的白名单字段。

生产环境必须补齐：身份认证、按用户/角色的表与字段授权、行级数据权限过滤、
按调用方的限流与配额，以及把 SQL 审计写入独立通道（而不是普通应用日志）。
本服务目前**故意不在普通日志里记录 SQL 原文**。

## 智能问数 Agent 的数据来源

数据中台阶段的第 3 小步：把 LangGraph 智能问数 Agent 的默认查询执行器从
「模拟数据」换成「数据中台安全查询服务」，让它读真实 PostgreSQL。

### 完整链路

```text
用户自然语言问题
→ intake / understand_question（LLM 识别意图）
→ discover_assets（检索已登记资产）
→ generate_sql（LLM 生成 SQL 草稿）
→ validate_sql（Agent 第 1 层 AST 校验）
→ execute_query（await 执行器）
     → query_execution.execute_real_query
     → app.services.safe_query.execute_safe_query（第 2 层 AST 校验 + 只读事务）
     → PostgreSQL 真实零售样例数据
→ explain_result（LLM 解读结果）
→ suggest_visualization（纯规则给出图表建议）
→ finish
```

### 三条边界

| 边界 | 做法 |
| --- | --- |
| Agent 不直接连数据库 | 不导入 SQLAlchemy / asyncpg / repository，只调用 `execute_safe_query` |
| 不经 HTTP 调用自己 | 同进程内直接调服务函数，不走 `localhost:8000` |
| 两层 SQL 校验都保留 | Agent 的 `validate_sql` 管工作流与 repair；数据服务的校验管数据库 |

有测试用 **AST 扫描** agent 包的全部 import 语句，确认它没有引入数据库驱动、
HTTP 客户端或第二套连接；并确认整个 agent 包只有 `query_execution.py`
一个模块接入数据服务。

### 异步集成

`execute_safe_query` 是异步的，所以 `execute_query` 是全图**唯一**的异步节点。
LangGraph 只要图里有一个异步节点，就拒绝同步 `invoke()`：

```text
TypeError: No synchronous function provided to "execute_query"
```

因此图必须用 `await graph.ainvoke(...)` 驱动。其余节点保持同步不动——
只把真正需要 I/O 的那个节点异步化，比把整张图改成 async 改动面小得多。
测试端把 `asyncio.run(...)` 收在**唯一一个** `run_graph` 辅助函数里，
不散落到几百个测试中（测试入口本身不在事件循环里，所以这样用是安全的）。

### 数据来源标记

`QueryResult.source` 只有两个取值：

```text
mock     内置模拟数据（结论会追加「基于模拟数据」说明）
postgres 数据中台安全查询服务返回的真实数据（不追加该说明）
```

解释节点的系统提示词也按来源选择：真实数据那一版不会说「这些是模拟数据」，
避免对着真实数据说出误导性的话。

### 模拟执行器仍在

`mock_query.py` 没有被删除，`execute_mock_query()` 也保持不变。它现在只用于
单元测试和无数据库时的演示，入口是显式的：

```python
build_graph()                    # 生产：execute_real_query，读真实数据
build_mock_data_query_graph()    # 演示/测试：execute_mock_query_async
```

生产图**不会**悄悄回退到 mock。

### 真实数据库冒烟验证

```powershell
cd backend
python tests/smoke_agent_real_query.py
```

脚本名不以 `test_` 开头，所以 pytest 不会收集它——**默认测试套件不依赖数据库**。
它会用假的分类器 / SQL 生成器 / 解释器（因此不调用任何真实 LLM）+ 真实的
`execute_safe_query` 跑完整条链路，并在前后各统计一次 orders 的行数与净销售额，
证明整个过程没有改动样例数据。

### 已知限制

Agent 的 `validate_sql` 要求每个字段都带表名，因此 `ORDER BY <输出别名>`
（例如 `ORDER BY sales_amount DESC`）会被判成「未限定表名」而拒绝——
而数据服务那一层是允许别名引用的。模型很自然会写出这种写法，
第一次校验会被拒、用掉唯一一次修复机会。

绕过方式：把 `ORDER BY sales_amount` 写成 `ORDER BY SUM(orders.net_amount)`。
本阶段按边界要求没有修改 Agent 的校验器，这条差异有专门的测试记录在案
（`test_agent_validator_still_rejects_an_order_by_alias`）。

## 智能问数接口（自然语言）

第 4 小步：给前端提供自然语言问数入口。

```text
POST /api/v1/agent/data-query     ← 自然语言，给前端用
POST /api/v1/data/query           ← 受控 SQL，给程序化调用方用
```

两者不是一回事：前者只收一句自然语言问题，SQL 的生成与校验全在 Agent 内部；
后者直接收 SQL，由数据服务做白名单校验。

### 完整链路

```text
浏览器 / 未来的 Next.js 页面
→ FastAPI 路由（只做 HTTP 适配）
→ await get_data_query_graph().ainvoke({"question": ...})
→ LangGraph Agent（意图 → 资产 → 生成 SQL → 校验 → 执行 → 解释 → 图表）
→ 数据中台 execute_safe_query()
→ PostgreSQL 真实零售样例数据
→ 路由筛选出安全字段
→ JSON 响应
```

### 请求与响应

请求：

```json
{ "question": "华东地区近六个月销售额趋势怎么样？" }
```

成功响应（HTTP 200）：

```json
{
  "status": "ok",
  "answer": "销售额整体呈上升趋势……",
  "query_result": {
    "columns": ["month", "sales_amount"],
    "rows": [{ "month": 1, "sales_amount": 140892.02 }],
    "row_count": 12,
    "source": "postgres"
  },
  "chart_suggestion": {
    "chart_type": "line",
    "title": "销售额趋势",
    "x_field": "month",
    "y_field": "sales_amount",
    "series_field": null,
    "value_format": "currency",
    "reason": "结果包含时间维度和销售额。"
  },
  "events": ["已接收问题", "已识别问题类型", "已匹配可用数据资产"]
}
```

### 状态码

| 场景 | HTTP | status |
| --- | ---: | --- |
| Agent 正常完成（含未知意图、无匹配资产、查询 0 行） | 200 | `ok` |
| Agent 写入受控 `error`（意图识别失败、数据服务不可用等） | 200 | `error` |
| 请求体不合法（缺 `question`、纯空白、超 500 字） | 422 | — |
| 图执行抛异常 / 结果契约不合法 | 500 | — |

**`error` 也是 200**：那是一个安全的、可以展示给用户的业务结果，不是 HTTP 层故障。
只有「服务本身给不出任何回答」才是 500。

### 不返回什么

路由采用**白名单式**取字段，只读 `answer` / `query_result` / `chart_suggestion` / `events`。
Agent State 里的这些一律不外发：

| 字段 | 不外发的原因 |
| --- | --- |
| `sql_draft` | SQL 原文含表名字段名，属于实现细节 |
| `sql_validation` | 校验问题原文同上 |
| `matched_assets` | 内部资产目录结构 |
| `retry_count` | 内部重试计数 |
| `intent` | 内部意图枚举 |
| `error` | 内部错误字段；它的安全文案已并入 `answer` |
| `question` | 用户原始输入 |

### events 为什么要重新映射

Agent 内部事件形如 `"节点名：细节"`，细节里可能带用户问题全文、SQL 片段、
字段名甚至异常类名——**不能假设它适合公开**。所以路由不复制原文，
只按节点名查一张固定映射表：

```text
intake → 已接收问题        execute_query → 已完成数据查询
understand_question → 已识别问题类型    explain_result → 已生成分析结论
discover_assets → 已匹配可用数据资产    suggest_visualization → 已生成图表建议
generate_sql → 已生成查询方案           finish → 分析流程已完成
validate_sql → 已完成查询安全校验       repair_sql → 已尝试修复查询方案
```

未知前缀直接丢弃；保持原顺序；同一步骤重复出现（例如修复后再次校验）照原样保留。

### 手动验证（会花一次模型调用，请自行决定）

自动化测试**不调用真实 LLM**。想验证整条真实链路时：

1. 打开 http://localhost:8000/docs
2. 找到 `POST /api/v1/agent/data-query`，点 **Try it out**
3. 输入 `{"question":"华东地区近六个月销售额趋势怎么样？"}`
4. 点 **Execute**

预期：HTTP 200、`status = ok`、`query_result.source = postgres`、
`chart_suggestion.chart_type = line`、`answer` 里没有「模拟数据」说明，
`events` 是上面那串简短流程文案。

如果模型配置不可用，会返回 `status = error` 加一句受控说明，
不会泄露配置内容。

## 智能问数页面

页面上线后可访问：

```text
http://localhost:3000/applications/data-query
```

输入一句中文问题，页面会调用 `POST /api/v1/agent/data-query`，展示分析结论、
执行过程、明细表和图表建议。

### 跨端启动（必须前后端同时在跑）

页面要拿到数据，两个服务都得在：

```powershell
# 1. 数据库 + 后端 + 前端
docker compose up -d

# 2. 确认三端都能访问
http://localhost:3000/applications/data-query   前端页面
http://localhost:8000/docs                      后端接口文档
http://localhost:8000/api/v1/health             后端与数据库状态
```

### 为什么需要 CORS

前端在 `localhost:3000`、后端在 `localhost:8000`，**端口不同就是跨域**。
浏览器会在真正发请求之前先发一个 `OPTIONS` 预检，后端不明确放行就会整个被拦掉，
页面连一个字节的响应都拿不到。

后端只放行本地开发的两个来源：

```text
http://localhost:3000
http://127.0.0.1:3000
```

刻意**不用 `["*"]`**（通配符等于允许任意站点带着浏览器里的凭据调用本服务），
方法只开 `GET/POST/OPTIONS`，请求头只开 `Content-Type`，且不开
`allow_credentials`。这份名单是本地开发用的，生产环境应由部署配置或
受控的允许列表管理。

### 前端如何定位后端

前端不写死 IP，而是拿当前页面的协议和主机名拼上 8000 端口：

```text
在 http://localhost:3000   打开 → 请求 http://localhost:8000/api/v1/agent/data-query
在 http://127.0.0.1:3000   打开 → 请求 http://127.0.0.1:8000/api/v1/agent/data-query
```

这样既不会把某台机器的 IP 固化进代码，也顺带满足了上面的 CORS 白名单
（按来源逐个列出，写死 IP 反而会被拦）。

### 页面边界

```text
当前使用本地零售样例数据，不是企业真实生产数据
每次提问都会调用配置的模型服务，请不要输入敏感信息
尚未接入 RAG 知识库、用户权限与会话记忆
```

页面首次打开**不会**发起任何请求；只有点击「开始分析」或按
`Ctrl / Cmd + Enter` 才会提交。请求可以取消，取消、失败、空结果各有独立展示。

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
- embedding（RAG 用）与对话模型**分开配置**，走 `EMBEDDING_*` 五个变量，默认指向
  阿里云百炼的 OpenAI 兼容模式（`text-embedding-v4`）。`EMBEDDING_DIMENSION`
  必须同时与 `EMBEDDING_MODEL` 的实际输出维度和 pgvector 建表时的 `vector(N)` 一致，
  改任一处都要同步改另外两处，否则会在入库或建索引时才报错。
  配置是否调得通，用 `python backend/scripts/smoke_embedding.py` 验证。

## 开发路线

- [x] 阶段一：最小可运行后端（FastAPI + Agent + 模型接入）
- [x] 阶段二：工程骨架整理，分层目录落地
- [x] 阶段三：Docker Compose 与 PostgreSQL 本地环境
- [x] 阶段三·补：SQLAlchemy 异步引擎接入与数据库连接自检（`/health/db`）
- [x] 阶段四：Next.js + TypeScript 前端工程初始化（占位首页）
- [x] 阶段四·补：三服务容器化（后端/前端生产镜像 + Compose 健康依赖链 + 统一健康检查 `/api/v1/health`）
- [x] 阶段五：Alembic 初始化配置与零售样例数仓（五张表 + 幂等种子数据 + 只读验证脚本）
- [x] 阶段五·补：数据服务受控只读查询接口（AST 安全校验 + 只读事务 + 结构化结果，POST `/api/v1/data/query`）
- [x] 阶段五·补：智能问数 Agent 接入真实数据（默认执行器改为数据中台服务，mock 保留供测试）
- [x] 阶段五·补：自然语言智能问数接口（POST `/api/v1/agent/data-query`，await 生产 Agent 图）
- [x] 阶段九：前端问数工作台（`/applications/data-query`：输入、加载、取消、结论、执行过程、明细表、SVG/CSS 图表）
- [ ] 阶段六：数据目录与指标语义层
- [ ] 阶段七：安全 SQL 生成与查询执行
- [ ] 阶段八：运行记录与可观测性
