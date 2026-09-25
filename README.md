# InsightFlow 数据智能平台

一个可演示的数据分析项目：接入结构化业务数据与业务文档，使用自然语言完成安全问数、知识检索和经营分析，并展示从数据入库到结论生成的完整链路。

## 项目亮点

- 接入天猫 IJCAI 2015 真实公开数据，流式处理 5,587 万条原始记录。
- PostgreSQL 采用 Silver 明细层和 Gold 汇总层，智能问数只开放 Gold 表。
- 自然语言问题经过领域路由、资产检索、SQL 生成、双层安全校验和只读事务后查询数据库。
- 业务文档经过切片、Embedding、向量与关键词混合召回、RRF 融合和 Reranker 精排。
- 前端可展示问数结果、检索来源、执行过程和多步骤经营分析报告。
- Docker Compose 一键启动 PostgreSQL、FastAPI 和 Next.js。

## 系统架构

```text
结构化数据
  → 数据校验与稳定抽样
  → PostgreSQL Silver 明细层
  → PostgreSQL Gold 汇总层
  → 安全 SQL 查询
  → 数据结论与图表

业务文档
  → 标题与语义边界切片
  → Embedding
  → PostgreSQL + pgvector
  → 向量/关键词混合召回
  → RRF 融合与 Reranker 精排
  → 带来源的知识回答
```

数字只由 SQL 精确计算，向量知识库只负责解释指标口径、字段含义和数据限制。

## 已接入的数据

| 数据域 | 规模 | 可以分析什么 |
| --- | --- | --- |
| 零售样例 | 240 位客户、24 个商品、3,404 条订单明细 | 销售额、客单价、区域、商品和会员复购 |
| 天猫 IJCAI 2015 | 7,712 位用户、998,542 条行为、9,558 个复购样本 | 行为趋势、商家/类目排行、购买广度和历史复购 |
| 业务知识库 | 26 份文档、462 个切片 | 指标口径、数据字典、抽样规则和业务限制 |

天猫数据按 `user_id % 55 = 0` 做用户级稳定抽样。四个 CSV 使用同一规则，保证用户画像、行为日志和复购样本仍能正确关联。

### 天猫行为分布

| 行为 | 记录数 |
| --- | ---: |
| 点击 `click` | 881,857 |
| 加购 `cart` | 1,343 |
| 收藏 `favorite` | 55,306 |
| 购买 `buy` | 60,036 |

`buy` 表示购买行为记录，不等于一笔订单。数据没有金额、订单号和件数，因此不会回答 GMV、客单价或真实订单量。

## 数据库设计

### Silver 明细层

| 表 | 内容 |
| --- | --- |
| `tmall_users` | 用户画像 |
| `tmall_user_events` | 用户行为明细 |
| `tmall_repurchase_samples` | train/test 复购样本 |

### Gold 查询层

| 表 | 分析用途 |
| --- | --- |
| `tmall_daily_metrics` | 每日行为趋势 |
| `tmall_merchant_metrics` | 商家行为、购买用户和历史复购 |
| `tmall_category_metrics` | 类目行为与购买用户 |
| `tmall_user_metrics` | 用户活跃、购买广度和历史复购 |
| `tmall_funnel_metrics` | 四类行为的事件数与用户数 |
| `tmall_repurchase_metrics` | train/test 样本与标签分布 |

用户行为明细不进入问数白名单，避免模型查询单个用户的完整行为轨迹。零售表和天猫表也禁止跨领域 JOIN，防止产生可以执行但没有业务意义的结果。

## 已实现功能

| 功能 | 实现方式 |
| --- | --- |
| 真实数据导入 | ZIP 流式读取、逐行校验、用户级稳定抽样、asyncpg COPY |
| 导入可靠性 | 文件哈希幂等、运行台账、原子 `--replace`、失败回滚 |
| 数据汇总 | Silver 明细整表重算六张 Gold 表，并校验 Gold/Silver 一致性 |
| 智能问数 | LangGraph 编排领域识别、资产发现、SQL 生成、执行与解释 |
| SQL 安全 | sqlglot AST 校验、表字段白名单、行数限制、PostgreSQL 只读事务 |
| 知识问答 | 查询改写、向量与关键词混合召回、RRF、Reranker、来源引用 |
| 经营分析 | 多步骤工具调用、SSE 进度、Checkpoint 恢复和结构化报告 |
| Web 工作台 | Next.js 页面展示数据采集、知识问答、智能问数和经营分析 |

## 可以演示的问题

### 数据分析

- 天猫每天的点击、收藏、加购和购买趋势如何？
- 哪一天购买行为最多？双十一前后有什么变化？
- 购买用户数最多的前 10 个商家有哪些？
- 哪些商家的历史复购率最高？
- 购买用户数最多的类目有哪些？
- train 中正样本有多少，正样本率是多少？

### 口径与规则

- 哪些数据进入普通数据库，哪些进入向量数据库？
- 为什么按 `user_id` 取模抽样？
- `buy` 为什么不能直接叫订单？
- 历史复购、购买广度和 train 标签有什么区别？
- 为什么 test 的 `probability` 是空值？
- 为什么天猫数据和零售数据不能跨领域 JOIN？

## 技术栈

| 层次 | 技术 |
| --- | --- |
| 前端 | Next.js 16、React 19、TypeScript |
| 后端 | FastAPI、SQLAlchemy 2、asyncpg |
| 流程编排 | LangChain、LangGraph、Deep Agents |
| 数据库 | PostgreSQL 16、pgvector、Alembic |
| SQL 安全 | sqlglot、只读事务、白名单与超时控制 |
| RAG | text-embedding-v4、混合检索、RRF、qwen3-rerank |
| 部署 | Docker Compose |

## 快速启动

### 1. 配置环境变量

```powershell
Copy-Item .env.example .env
```

在 `.env` 中填写对话模型、Embedding 和 Reranker 的 API Key。

### 2. 启动全部服务

```powershell
docker compose up --build -d
docker compose ps
```

访问地址：

- 前端：http://localhost:3000
- 后端 API 文档：http://localhost:8000/docs
- 健康检查：http://localhost:8000/api/v1/health

### 3. 初始化数据库

```powershell
cd backend
python -m alembic upgrade head
python scripts/seed_retail_data.py
python scripts/ingest_knowledge.py
```

### 4. 导入天猫数据

```powershell
python scripts/ingest_tmall_data.py --zip "<data_format1.zip 路径>" --dry-run
python scripts/ingest_tmall_data.py --zip "<data_format1.zip 路径>" --sample-modulus 55 --sample-residue 0
python scripts/verify_tmall_data.py
```

## 核心接口

| 接口 | 用途 |
| --- | --- |
| `POST /api/v1/data/query` | 执行受控只读 SQL |
| `POST /api/v1/agent/data-query` | 自然语言智能问数 |
| `POST /api/v1/rag/answer` | 知识库问答 |
| `POST /api/v1/rag/documents` | 上传并向量化知识文档 |
| 经营分析接口 | 多步骤分析、SSE 过程和报告生成 |

## 项目结构

```text
backend/
  app/api/              FastAPI 路由
  app/agent/            LangGraph 与经营分析编排
  app/models/           零售、天猫和知识库 ORM
  app/services/         数据导入、安全查询、RAG 与业务服务
  alembic/              数据库迁移
  knowledge_seed/       零售与天猫知识文档
  scripts/              导入、验证和冒烟脚本
  tests/                后端自动化测试
frontend/
  src/app/              Next.js 页面
  src/features/         平台、架构与业务功能
docker-compose.yml      PostgreSQL、后端和前端编排
```

## 面试时重点说明

1. 结构化数据需要精确聚合，因此进入 PostgreSQL；业务口径需要语义检索，因此进入 pgvector。
2. 用户级稳定抽样保证跨文件关联和单个用户行为完整，比随机行抽样更适合多表数据。
3. 智能问数只查询 Gold 表，并通过双层 AST 校验和数据库只读事务限制模型生成的 SQL。
4. `--replace` 的清空、COPY 和 Gold 重算在同一真实事务中，任何阶段失败都会整体回滚。
5. RAG 使用向量与关键词双路召回，RRF 解决分数量纲差异，Reranker 再判断候选是否真正能回答问题。

## 详细文档

- [天猫数据接入运行手册](docs/tmall-data-pipeline-runbook.md)
- [天猫数据接入面试讲解](docs/tmall-data-pipeline-interview.md)
- [天猫数据与可询问问题清单](docs/天猫数据导入与可询问问题清单.docx)
- [前端说明](frontend/README.md)

## 当前边界

- 项目使用公开数据与本地样例数据，不是企业生产系统。
- 尚未接入企业身份认证、租户隔离和细粒度数据权限。
- 天猫数据没有金额、订单号、商品名称、地区和 session，相关问题不会强行推断。
- 外部模型调用需要自行配置 API Key，并可能产生费用。
