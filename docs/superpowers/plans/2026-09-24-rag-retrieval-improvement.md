# 通用 RAG 检索增强 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** 为现有知识问答增加通用查询改写、动态检索元数据、混合召回、RRF 融合和 Reranker 精排。

**Architecture:** 保留现有 pgvector 检索与 RAG 回答接口，在其前面增加独立的 QueryRewriter、关键词召回、RRF 融合和 Reranker。每个外部调用均可注入测试替身并具备失败降级，最终只把 5 条切片交给回答模型。

**Tech Stack:** Python 3.14、FastAPI、Pydantic、SQLAlchemy 2 Async、PostgreSQL 16、pgvector、pg_trgm、LangChain、Alembic、pytest、Next.js 16、TypeScript。

**Spec:** docs/superpowers/specs/2026-09-24-rag-retrieval-improvement.md

## Global Constraints

- 开发分支：feature/rag-retrieval-improvement。
- 禁止硬编码具体业务领域同义词。
- 原问题最多扩展成 3 条查询；候选最多 20 条；最终上下文最多 5 条。
- 新增网络调用必须支持依赖注入、超时、失败降级和密钥清洗。
- 自动化测试不得访问真实网络，不得读取或输出 .env 的密钥。
- 不修改零售业务表，不删除知识数据，不执行 docker compose down -v。
- 每个任务测试通过后独立提交。

## Review Focus

- 改写返回重复、空白或超限时，必须规范化为不超过 3 条查询。
- 中文短关键词不足 3 字时，必须有精确包含匹配，不能只依赖 trigram。
- 同一切片多路命中时只能返回一次，融合排序必须稳定。
- 改写模型或 Reranker 超时、限流、畸形响应时必须安全降级。
- 旧切片尚未补充元数据时，仍可通过标题和正文参与检索。

---

### Task 0：分支与回归基线

**Files:** 无业务文件修改。

**Produces:** 干净的功能分支和测试基线。

- [ ] 确认分支与状态：

    git branch --show-current
    git status --short
    git log -3 --oneline --decorate

  Expected：当前分支是 feature/rag-retrieval-improvement，工作区只有本计划文档。

- [ ] 先提交设计和计划文档：

    git add docs/superpowers/specs/2026-09-24-rag-retrieval-improvement.md docs/superpowers/plans/2026-09-24-rag-retrieval-improvement.md
    git commit -m "docs: plan generic RAG retrieval improvements"

- [ ] 跑现有基线：

    pytest -q
    cd frontend
    npm run lint
    npx tsc --noEmit
    cd ..

  Expected：全部通过；既有失败需先单独报告。

---

### Task 1：通用 QueryRewriter

**Files:**
- Create: backend/app/services/query_rewrite.py
- Create: backend/tests/test_query_rewrite.py
- Modify: backend/app/core/config.py
- Modify: .env.example

**Produces:** async rewrite_query(question, llm=None) -> QueryRewriteResult。

- [ ] 写失败测试，覆盖原问题保留、最多两个改写、去空去重、关键词去重、空问题、模型异常与畸形输出回退。

    def test_rewrite_keeps_original_and_deduplicates():
        result = asyncio.run(rewrite_query("用户原问题", llm=fake_llm))
        assert result.search_queries[0] == "用户原问题"
        assert len(result.search_queries) <= 3
        assert len(result.search_queries) == len(set(result.search_queries))

- [ ] 运行测试确认失败：

    pytest backend/tests/test_query_rewrite.py -q

- [ ] 实现接口：

    @dataclass(frozen=True)
    class QueryRewriteResult:
        original_query: str
        rewritten_queries: tuple[str, ...]
        keywords: tuple[str, ...]

        @property
        def search_queries(self) -> tuple[str, ...]: ...

    async def rewrite_query(
        question: str,
        *,
        llm: BaseChatModel | None = None,
    ) -> QueryRewriteResult: ...

- [ ] 使用 Pydantic 结构化输出；Prompt 只允许生成搜索表达与关键词，不允许回答问题或假设业务领域。

- [ ] 增加配置：

    RAG_QUERY_REWRITE_ENABLED=true
    RAG_MAX_REWRITTEN_QUERIES=2

- [ ] 测试回退和原有服务：

    pytest backend/tests/test_query_rewrite.py backend/tests/test_rag_answer.py backend/tests/test_knowledge_search.py -q

- [ ] 提交：

    git add backend/app/services/query_rewrite.py backend/tests/test_query_rewrite.py backend/app/core/config.py .env.example
    git commit -m "feat: add generic RAG query rewriting"

---

### Task 2：知识切片检索元数据表结构

**Files:**
- Modify: backend/app/models/knowledge.py
- Create: backend/alembic/versions/a4c2e9f18b7d_add_rag_search_metadata.py
- Modify: backend/tests/test_knowledge_models.py
- Create: backend/tests/test_rag_search_metadata_migration.py

**Produces:** keywords、aliases、search_text 三列及 pg_trgm。

- [ ] 写失败测试：列类型与默认值、down_revision=69e6c2579c1b、upgrade 启用 pg_trgm、回填 search_text、创建 GIN 索引，downgrade 只删除本迁移对象。

- [ ] 运行并确认失败：

    pytest backend/tests/test_knowledge_models.py backend/tests/test_rag_search_metadata_migration.py -q

- [ ] 修改模型：

    keywords: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list, server_default="[]")
    aliases: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list, server_default="[]")
    search_text: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")

- [ ] 编写迁移：创建扩展、新增列、使用文档标题+小节标题+正文回填、创建 GIN trigram 索引。downgrade 不删除共享扩展。

- [ ] 在测试库演练 upgrade/downgrade/upgrade；文档数、切片数、非空向量数必须不变。

- [ ] 提交：

    git add backend/app/models/knowledge.py backend/alembic/versions/a4c2e9f18b7d_add_rag_search_metadata.py backend/tests/test_knowledge_models.py backend/tests/test_rag_search_metadata_migration.py
    git commit -m "feat: add knowledge search metadata schema"

---

### Task 3：动态 keywords、aliases 和 search_text

**Files:**
- Create: backend/app/services/knowledge_metadata.py
- Create: backend/tests/test_knowledge_metadata.py
- Modify: backend/app/services/knowledge_ingestion.py
- Modify: backend/tests/test_knowledge_ingestion.py
- Create: backend/scripts/backfill_knowledge_metadata.py
- Create: backend/tests/test_backfill_knowledge_metadata.py

**Produces:** extract_search_metadata()、build_search_text() 和幂等回填脚本。

> 实现落地时把 search_text 拆成了两个函数：`build_base_search_text()`（标题+小节+正文，
> 与迁移里 concat_ws 的输出逐字节一致，用于降级与「是否已处理」判据）和
> `build_enriched_search_text()`（在基础版之上补关键词与同义表达标记，那两个标记是
> 「已提取过」的唯一凭据）。回填脚本靠「search_text 是否仍等于基础版」判断待处理项。

- [ ] 写失败测试：任意领域文本提取、去重、数量/长度上限、空输出、模型异常、Prompt 不含零售硬编码。

- [ ] 实现接口：

    @dataclass(frozen=True)
    class KnowledgeSearchMetadata:
        keywords: tuple[str, ...]
        aliases: tuple[str, ...]
        search_text: str

    async def extract_search_metadata(
        document_title: str,
        section_title: str,
        content: str,
        *,
        llm: BaseChatModel | None = None,
    ) -> KnowledgeSearchMetadata: ...

- [ ] 上限设为 keywords 12 个、aliases 12 个；失败时数组为空，但 search_text 仍包含标题和正文。

- [ ] 接入知识入库：insert/update 写元数据；skip 不调用元数据模型或 Embedding。

- [ ] 实现 backfill_knowledge_metadata.py，支持 --dry-run、批次和 --refresh；默认不覆盖已存在元数据，重复运行必须 skip。

- [ ] 测试：

    pytest backend/tests/test_knowledge_metadata.py backend/tests/test_knowledge_ingestion.py backend/tests/test_backfill_knowledge_metadata.py -q

- [ ] 提交：

    git add backend/app/services/knowledge_metadata.py backend/app/services/knowledge_ingestion.py backend/scripts/backfill_knowledge_metadata.py backend/tests/test_knowledge_metadata.py backend/tests/test_knowledge_ingestion.py backend/tests/test_backfill_knowledge_metadata.py
    git commit -m "feat: enrich knowledge chunks for retrieval"

---

### Task 4：关键词召回与 RRF 融合

**Files:**
- Create: backend/app/services/knowledge_keyword_search.py
- Create: backend/app/services/retrieval_fusion.py
- Create: backend/tests/test_knowledge_keyword_search.py
- Create: backend/tests/test_retrieval_fusion.py
- Modify: backend/app/services/knowledge_search.py
- Modify: backend/tests/test_knowledge_search.py

**Produces:** hybrid_search(query_plan, candidate_limit=20) -> list[RetrievalCandidate]。

- [ ] 定义候选类型并写失败测试：

    @dataclass(frozen=True)
    class RetrievalCandidate:
        result: KnowledgeSearchResult
        vector_rank: int | None
        keyword_rank: int | None
        rrf_score: float
        matched_queries: tuple[str, ...]
        rerank_score: float | None = None

> 实现落地时改成了 `chunk: ChunkContent` + 可空的 distance/similarity/keyword_score：
> 关键词独占的候选**没有**向量距离，套用 KnowledgeSearchResult 就得给它编一个
> distance，而下游会把这个编出来的数当成真分数用。公共部分（这一段的文字）抽成了
> ChunkContent，两种召回结果都能通过 `.chunk` 取到。

- [ ] 实现参数化关键词 SQL：标题/aliases 精确包含优先，其次 search_text trigram；少于 3 字的查询必须使用 ILIKE。

- [ ] 实现 RRF：

    def reciprocal_rank_fusion(
        ranked_lists: Sequence[Sequence[KnowledgeSearchResult]],
        *,
        k: int = 60,
        limit: int = 20,
    ) -> list[RetrievalCandidate]: ...

  使用 chunk_id 去重；多路命中累加；平分时以最优单路排名和 chunk id 稳定排序。

- [ ] 原问题和改写问题分别向量召回，查询和关键词分别关键词召回；任一路失败保留另一路，两路都失败才抛受控错误。

- [ ] 测试并提交：

    pytest backend/tests/test_knowledge_keyword_search.py backend/tests/test_retrieval_fusion.py backend/tests/test_knowledge_search.py -q
    git add backend/app/services/knowledge_keyword_search.py backend/app/services/retrieval_fusion.py backend/app/services/knowledge_search.py backend/tests/test_knowledge_keyword_search.py backend/tests/test_retrieval_fusion.py backend/tests/test_knowledge_search.py
    git commit -m "feat: add hybrid knowledge retrieval"

---

### Task 5：可插拔 Reranker

**Files:**
- Create: backend/app/services/reranker.py
- Create: backend/tests/test_reranker.py
- Modify: backend/app/core/config.py
- Modify: .env.example
- Modify: requirements.txt only if the verified provider requires a direct dependency.

**Produces:** rerank_candidates(query, candidates, top_n=5, reranker=None)。

- [ ] 实现前查当前供应商官方文档，确认 endpoint、模型名、输入上限、鉴权和响应字段；模型名仅存在配置中。

- [ ] 写失败测试：正确重排、稳定排序、空候选不联网、top_n 上限、超时/401/429/5xx/畸形响应回退、错误文本不含密钥。

- [ ] 定义接口：

    class Reranker(Protocol):
        async def rerank(
            self,
            query: str,
            documents: Sequence[str],
            *,
            top_n: int,
        ) -> Sequence[RerankItem]: ...

- [ ] 文档输入包含文档标题、小节标题和正文；返回索引必须校验范围、唯一性和数量。

- [ ] 增加配置：

    RAG_RERANK_ENABLED=true
    RAG_RETRIEVAL_CANDIDATE_LIMIT=20
    RAG_FINAL_TOP_K=5
    RERANK_PROVIDER=dashscope
    RERANK_MODEL=qwen3-rerank
    RERANK_API_KEY=sk-xxxxxxxxxxxxxxxx
    RERANK_BASE_URL=https://your-workspace-id.cn-beijing.maas.aliyuncs.com/compatible-api/v1
    RERANK_TIMEOUT_SECONDS=10

> 模型名在实现前查过官方文档确认：qwen3-rerank 走独立的 `/reranks` 路径，
> 响应里 `results` 在**顶层**（与 gte-rerank-v2 的 `output.results` 不同），
> 且不支持 `return_documents`。单条文档上限 4,000 token、单次最多 500 条。

- [ ] Reranker 关闭、配置缺失或调用失败时返回 RRF 顺序，不影响 RAG 回答。

- [ ] 测试并提交：

    pytest backend/tests/test_reranker.py -q
    git add backend/app/services/reranker.py backend/tests/test_reranker.py backend/app/core/config.py .env.example requirements.txt
    git commit -m "feat: add configurable RAG reranking"

---

### Task 6：接入 RAG 回答服务

**Files:**
- Create: backend/app/services/knowledge_retrieval.py
- Create: backend/tests/test_knowledge_retrieval.py
- Modify: backend/app/services/rag_answer.py
- Modify: backend/tests/test_rag_answer.py
- Modify: backend/app/api/routes.py only for backward-compatible retrieval summary.

**Produces:** retrieve_knowledge(question, final_top_k=5) -> RetrievalResult。

- [ ] 写编排失败测试：rewrite → hybrid → rerank；回答模型收到原问题和最终 top-k；三个外部环节分别失败时按设计降级。

- [ ] 定义结果：

    @dataclass(frozen=True)
    class RetrievalResult:
        original_query: str
        search_queries: tuple[str, ...]
        candidates_considered: int
        rerank_applied: bool
        results: tuple[RetrievalCandidate, ...]

- [ ] 将 rag_answer 的单一 searcher 替换为检索编排器，保留测试注入兼容层。build_knowledge_block、preview、Prompt 不承担检索职责。

- [ ] 后端全量回归：

    pytest -q

- [ ] 提交：

    git add backend/app/services/knowledge_retrieval.py backend/app/services/rag_answer.py backend/app/api/routes.py backend/tests/test_knowledge_retrieval.py backend/tests/test_rag_answer.py
    git commit -m "feat: integrate hybrid retrieval into RAG answers"

---

### Task 7：前端检索摘要

**Files:**
- Modify: frontend/src/lib/api/rag-answer.ts
- Modify: frontend/src/app/applications/knowledge-qa/KnowledgeAnswerPanel.tsx
- Modify: frontend/src/app/applications/knowledge-qa/knowledge-qa.module.css

**Produces:** 兼容旧响应的折叠检索摘要。

- [ ] 更新类型和校验，仅允许展示：是否改写、查询数、候选数、是否重排、最终来源数。字段缺失时页面照常工作。

- [ ] 增加折叠区，禁止显示 Prompt、向量、密钥、内部主键和模型原始输出。

- [ ] 验证：

    cd frontend
    npm run lint
    npx tsc --noEmit
    npm run build
    cd ..

- [ ] 提交：

    git add frontend/src/lib/api/rag-answer.ts frontend/src/app/applications/knowledge-qa/KnowledgeAnswerPanel.tsx frontend/src/app/applications/knowledge-qa/knowledge-qa.module.css
    git commit -m "feat: show RAG retrieval summary"

---

### Task 8：迁移、回填、容器和最终验收

**Files:**
- Modify: README.md

**Produces:** Docker 环境可运行、可降级、可回滚的完整功能。

- [ ] 记录数据库基线：文档数、切片数、非空 embedding 数、Alembic revision；不得输出连接串。

- [ ] 执行迁移和幂等回填：

    cd backend
    alembic upgrade head
    python scripts/backfill_knowledge_metadata.py --dry-run
    python scripts/backfill_knowledge_metadata.py
    cd ..

  第二次运行必须全部 skip。

- [ ] 分别关闭查询改写、关键词检索和 Reranker，确认剩余链路仍可回答；恢复配置后再验收。

- [ ] 重建容器：

    docker compose up -d --build backend frontend
    docker compose ps

  三个服务必须 healthy；禁止 down -v。

- [ ] 浏览器验收知识问答、知识上传、智能问数和健康检查。使用原句、口语改写、精确字段名及一份非零售文档验证通用性。

- [ ] 更新 README 并提交：

    git add README.md
    git commit -m "docs: document hybrid RAG retrieval"

- [ ] 最终检查：

    git status --short
    git log --oneline --decorate main..HEAD
    pytest -q
    cd frontend
    npm run lint
    npx tsc --noEmit
    npm run build
    cd ..

  Expected：工作区干净，所有提交只与本功能相关，测试全部通过。

---

## 完成后合并回 main

先确认功能分支已提交、工作区干净：

    git switch feature/rag-retrieval-improvement
    git status --short
    git push -u origin feature/rag-retrieval-improvement

然后切回主线并同步：

    git switch main
    git pull --ff-only origin main

如果 pull 成功且没有新的冲突来源，合并功能分支：

    git merge --no-ff feature/rag-retrieval-improvement

合并后必须在 main 再跑一次：

    pytest -q
    cd frontend
    npm run lint
    npx tsc --noEmit
    npm run build
    cd ..

全部通过后推送主线：

    git push origin main

确认远端 main 正常后，可删除已合并分支：

    git branch -d feature/rag-retrieval-improvement
    git push origin --delete feature/rag-retrieval-improvement

如果 git pull --ff-only origin main 显示远端 main 有新提交，先不要强行合并。返回功能分支同步 main：

    git switch feature/rag-retrieval-improvement
    git merge main

解决冲突、完整测试并提交后，再重新执行“切回 main 并合并”的步骤。禁止使用 reset --hard 或强推。
