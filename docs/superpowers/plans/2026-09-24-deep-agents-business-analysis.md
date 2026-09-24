# Deep Agents 经营分析助手 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在现有 AI 数据智能平台中新增一个基于 LangChain Deep Agents 的经营分析助手，由上层 Agent 动态调用已有智能问数、RAG 和报告工具，并通过 SSE、Checkpoint、长期偏好记忆和上下文治理交付一个可演示、可恢复、可解释的复杂分析工作台。

**Architecture:** Deep Agent 只负责目标拆解、工具选择和循环控制；现有问数 LangGraph 继续负责 NL2SQL、安全校验和数据查询，现有 RAG 继续负责知识检索。FastAPI 新增独立的经营分析 SSE 接口，Next.js 新增经营分析页面，PostgreSQL 保存线程、Checkpoint、偏好、报告和大型工具结果。

**Tech Stack:** Python 3.14、FastAPI、LangChain、LangGraph、`deepagents==0.7.18`、OpenAI-compatible Chat Model、PostgreSQL 16、SQLAlchemy 2 async、pgvector、Next.js 16、React 19、TypeScript、SSE、pytest、Vitest/现有前端检查工具。

**Spec:** `docs/superpowers/specs/2026-09-24-deep-agents-business-analysis-design.md`

## Global Constraints

- 只安装并使用 `deepagents==0.7.18`；不集成 `deepagents-code`、`dcode` 或官方终端 UI。
- 保留 `/api/v1/agent/data-query` 及现有智能问数页面，新增功能不能改变其响应契约。
- Deep Agent 不得直接导入 SQLAlchemy、asyncpg、数据库 engine 或 HTTP 客户端执行自有查询。
- 所有数据查询必须继续经过现有 LangGraph 和 `safe_query` 双层安全边界。
- 对外事件和响应不得包含原始 SQL、连接串、密钥、完整异常、内部 Prompt 或模型思维内容。
- 每次运行必须有最大 Agent 步数、最大工具调用次数、工具结果大小限制和超时。
- 浏览器 UUID 只作为作品集阶段的匿名用户标识，不能宣称为生产身份认证。
- 新模块使用独立目录，避免把经营分析主管逻辑塞进现有 `data_query` 图。
- 每个任务先写失败测试，再写最小实现；每个任务结束后运行任务范围测试并提交一次。

## Review Focus

- 工具返回大量行时，系统是否只把摘要和 Artifact ID 放进上下文；由 Task 9 的上下文测试覆盖。
- SSE 客户端断开或重复连接时，是否能取消当前请求并从 Checkpoint 恢复；由 Task 8 和 Task 10 覆盖。
- Agent 选择了危险或不存在的工具名时，是否被固定白名单拒绝；由 Task 6 的 Agent 配置测试覆盖。
- RAG 暂时不可用时，是否仍能返回数据结论并标记来源不可用；由 Task 4 的工具契约测试覆盖。
- 相同 `thread_id` 并发运行时，是否拒绝第二个运行而不覆盖第一个状态；由 Task 8 的服务测试覆盖。

## 文件地图

### 后端新增文件

- `backend/app/agent/business_analysis/schemas.py`：工具结果、运行状态、SSE 事件、报告和记忆的数据契约。
- `backend/app/agent/business_analysis/tools.py`：四个业务工具及其边界适配器。
- `backend/app/agent/business_analysis/prompts.py`：经营分析系统提示词和报告格式约束。
- `backend/app/agent/business_analysis/context.py`：消息摘要、大结果裁剪和 Artifact 引用。
- `backend/app/agent/business_analysis/memory.py`：短期线程配置和长期用户偏好。
- `backend/app/agent/business_analysis/agent.py`：Deep Agent 创建、工具白名单和持久化依赖注入。
- `backend/app/agent/business_analysis/events.py`：内部 Agent 事件到公开 SSE 事件的安全映射。
- `backend/app/services/analysis_report.py`：报告、运行记录和 Artifact 的持久化服务。
- `backend/app/api/business_analysis_routes.py`：FastAPI 请求模型和 SSE 路由。
- `backend/alembic/versions/20260924_create_business_analysis_tables.py`：新增数据表迁移。

### 后端修改文件

- `requirements.txt`：加入 `deepagents==0.7.18` 和经兼容性探针确认的 PostgreSQL Checkpoint/Store 依赖。
- `backend/app/main.py` 或现有路由挂载位置：挂载经营分析路由。
- `backend/app/core/config.py`：增加 Agent 步数、工具调用、超时和上下文大小配置。
- `backend/app/repositories/database.py`：提供迁移后服务需要的异步数据库连接入口（若现有入口已满足，则只写测试不改实现）。

### 后端测试新增文件

- `backend/tests/test_business_analysis_schemas.py`
- `backend/tests/test_business_analysis_tools.py`
- `backend/tests/test_business_analysis_context.py`
- `backend/tests/test_business_analysis_events.py`
- `backend/tests/test_business_analysis_agent.py`
- `backend/tests/test_business_analysis_service.py`
- `backend/tests/test_business_analysis_api.py`
- `backend/tests/test_business_analysis_integration.py`

### 前端新增/修改文件

- `frontend/src/lib/api/business-analysis.ts`：SSE 请求和事件解析。
- `frontend/src/app/applications/business-analysis/page.tsx`：页面入口。
- `frontend/src/app/applications/business-analysis/business-analysis.module.css`：页面布局。
- `frontend/src/components/business-analysis/BusinessAnalysisWorkspace.tsx`：页面状态和请求控制。
- `frontend/src/components/business-analysis/AnalysisThreadList.tsx`：会话列表。
- `frontend/src/components/business-analysis/AnalysisMessageList.tsx`：消息和报告增量。
- `frontend/src/components/business-analysis/AnalysisEventTimeline.tsx`：执行时间线。
- `frontend/src/components/business-analysis/AnalysisReportPanel.tsx`：结构化报告、表格、图表和来源。
- `frontend/src/features/platform/platform-config.ts`：登记新页面、模块说明和导航入口。

---

### Task 1: 建立依赖和兼容性基线

**Files:**
- Modify: `requirements.txt`
- Modify: `backend/app/core/config.py`
- Create: `backend/tests/test_business_analysis_config.py`
- Create: `backend/scripts/probe_deepagents.py`

**Interfaces:**
- Produces: `Settings.business_analysis_max_steps: int`、`Settings.business_analysis_max_tool_calls: int`、`Settings.business_analysis_run_timeout_seconds: int`、`Settings.business_analysis_context_char_limit: int`。

- [ ] **Step 1: 写依赖探针失败测试**

```python
def test_deepagents_package_is_importable():
    import deepagents

    assert getattr(deepagents, "__version__", None) in {None, "0.7.18"}
    assert callable(deepagents.create_deep_agent)
```

- [ ] **Step 2: 运行测试确认当前环境状态**

运行：`pytest backend/tests/test_business_analysis_config.py -q`

预期：在尚未安装依赖时，测试失败并显示 `ModuleNotFoundError`；如果开发环境已经安装，则确认导入成功并记录实际版本。

- [ ] **Step 3: 固定核心依赖并写配置字段**

在 `requirements.txt` 增加：

```text
deepagents==0.7.18
```

在 `Settings` 中增加带默认值的字段：

```python
business_analysis_max_steps: int = 12
business_analysis_max_tool_calls: int = 8
business_analysis_run_timeout_seconds: int = 90
business_analysis_context_char_limit: int = 12000
```

探针脚本只负责打印 `deepagents.create_deep_agent` 的签名和可用版本，不修改项目源码。

- [ ] **Step 4: 安装并重新运行探针**

运行：`python -m pip install -r requirements.txt`；再运行：`python backend/scripts/probe_deepagents.py`。

预期：包可导入，`create_deep_agent` 可调用；如果 0.7.18 与当前 LangChain/LangGraph 不兼容，停止后续实现并在依赖文件中锁定经过验证的兼容版本组合。

- [ ] **Step 5: 运行配置测试并提交**

运行：`pytest backend/tests/test_business_analysis_config.py -q`

提交：`git add requirements.txt backend/app/core/config.py backend/tests/test_business_analysis_config.py backend/scripts/probe_deepagents.py`；`git commit -m "chore: add deep agents compatibility baseline"`。

---

### Task 2: 定义后端公开契约和 SSE 事件

**Files:**
- Create: `backend/app/agent/business_analysis/__init__.py`
- Create: `backend/app/agent/business_analysis/schemas.py`
- Create: `backend/tests/test_business_analysis_schemas.py`

**Interfaces:**
- Produces: `BusinessAnalysisRequest(thread_id, message, user_id)`、`ToolResult`、`AnalysisEvent`、`AnalysisReport`、`BusinessAnalysisResponse`。

- [ ] **Step 1: 写契约测试**

```python
def test_request_strips_message_and_requires_thread_id():
    request = BusinessAnalysisRequest(thread_id="thread-1", message="  分析销售额  ")
    assert request.message == "分析销售额"


def test_public_event_never_contains_raw_sql():
    event = AnalysisEvent.tool_completed(
        tool="analyze_business_data",
        summary="返回趋势摘要",
        metadata={"sql": "SELECT * FROM orders"},
    )
    assert "SELECT" not in event.to_sse_payload()
```

- [ ] **Step 2: 运行测试确认契约尚不存在**

运行：`pytest backend/tests/test_business_analysis_schemas.py -q`

预期：FAIL，显示契约类型或工厂方法不存在。

- [ ] **Step 3: 实现 Pydantic 契约**

定义固定事件类型：`run_started`、`status`、`tool_started`、`tool_completed`、`report_delta`、`run_completed`、`error`。`AnalysisEvent.to_sse_payload()` 只序列化白名单字段；禁止把原始工具参数放进公开 payload。

工具结果至少包含：`status`、`summary`、`data`、`sources`、`artifact_id`；`data` 必须限制为 JSON 可序列化对象。

- [ ] **Step 4: 运行契约测试并提交**

运行：`pytest backend/tests/test_business_analysis_schemas.py -q`

预期：PASS。

提交：`git add backend/app/agent/business_analysis backend/tests/test_business_analysis_schemas.py`；`git commit -m "feat: define business analysis contracts"`。

---

### Task 3: 实现数据分析工具适配器

**Files:**
- Create: `backend/app/agent/business_analysis/tools.py`
- Create: `backend/tests/test_business_analysis_tools.py`
- Reference: `backend/app/agent/data_query/graph.py`
- Reference: `backend/app/api/routes.py`

**Interfaces:**
- Consumes: `get_data_query_graph().ainvoke({"question": str})`。
- Produces: `async def analyze_business_data(question: str) -> ToolResult`。

- [ ] **Step 1: 写工具适配器测试**

```python
@pytest.mark.anyio
async def test_analyze_business_data_calls_existing_graph(monkeypatch):
    calls = []

    class FakeGraph:
        async def ainvoke(self, state):
            calls.append(state)
            return {
                "answer": "华东销售额下降",
                "query_result": {"columns": ["month"], "rows": [], "row_count": 0, "source": "postgres"},
                "chart_suggestion": None,
                "knowledge_sources": [],
            }

    monkeypatch.setattr("app.agent.business_analysis.tools.get_data_query_graph", lambda: FakeGraph())
    result = await analyze_business_data.ainvoke({"question": "分析华东销售额"})

    assert calls == [{"question": "分析华东销售额"}]
    assert result["status"] == "ok"
    assert result["summary"] == "华东销售额下降"
```

- [ ] **Step 2: 写安全边界测试**

```python
def test_business_analysis_tools_do_not_import_database_drivers():
    source = Path("backend/app/agent/business_analysis/tools.py").read_text(encoding="utf-8")
    assert "sqlalchemy" not in source
    assert "asyncpg" not in source
    assert "get_engine" not in source
```

- [ ] **Step 3: 实现工具适配器**

使用现有 `get_data_query_graph()`，只读取公开 State 字段；对 `answer`、`query_result`、`chart_suggestion` 和 `knowledge_sources` 做大小限制和 JSON 序列化，丢弃 SQL、内部事件和异常原文。

- [ ] **Step 4: 运行工具测试并提交**

运行：`pytest backend/tests/test_business_analysis_tools.py -q`

提交：`git add backend/app/agent/business_analysis/tools.py backend/tests/test_business_analysis_tools.py`；`git commit -m "feat: adapt safe data query as agent tool"`。

---

### Task 4: 接入知识检索和指标定义工具

**Files:**
- Modify: `backend/app/agent/business_analysis/tools.py`
- Create: `backend/tests/test_business_analysis_tools.py`（追加用例）
- Reference: `backend/app/services/knowledge_search.py`
- Reference: `backend/app/services/rag_answer.py`

**Interfaces:**
- Produces: `async def search_business_knowledge(query: str, top_k: int = 4) -> ToolResult`、`async def get_metric_definition(metric: str) -> ToolResult`。

- [ ] **Step 1: 写成功和降级测试**

```python
@pytest.mark.anyio
async def test_knowledge_failure_does_not_crash_analysis(monkeypatch):
    async def fail(*args, **kwargs):
        raise RuntimeError("database detail must stay private")

    monkeypatch.setattr("app.agent.business_analysis.tools.search_knowledge", fail)
    result = await search_business_knowledge.ainvoke({"query": "促销规则"})

    assert result["status"] == "degraded"
    assert result["sources"] == []
    assert "database detail" not in result["summary"]
```

- [ ] **Step 2: 实现知识检索工具**

调用现有检索函数，输出 `source_file`、`document_title`、`section_title`、`similarity`、`preview`，对 `preview` 和来源数量做限制。异常转成固定的 `degraded` 结果，不回显异常文本。

- [ ] **Step 3: 实现指标定义工具**

先通过现有知识检索查询指标名称；命中时返回指标定义和来源，未命中时返回 `not_found`，禁止用模型常识补写指标口径。

- [ ] **Step 4: 运行工具测试并提交**

运行：`pytest backend/tests/test_business_analysis_tools.py -q`

提交：`git add backend/app/agent/business_analysis/tools.py backend/tests/test_business_analysis_tools.py`；`git commit -m "feat: add knowledge and metric tools"`。

---

### Task 5: 建立报告、运行和 Artifact 持久化

**Files:**
- Create: `backend/app/services/analysis_report.py`
- Create: `backend/alembic/versions/20260924_create_business_analysis_tables.py`
- Create: `backend/tests/test_analysis_report.py`
- Reference: `backend/app/models/base.py`
- Reference: `backend/app/repositories/database.py`

**Interfaces:**
- Produces: `create_run(thread_id, user_id) -> run_id`、`append_artifact(run_id, kind, payload) -> artifact_id`、`save_report(run_id, report) -> report_id`、`load_thread_runs(thread_id) -> list[RunSummary]`、`save_analysis_report_tool(run_id, report) -> ToolResult`。

- [ ] **Step 1: 写数据库服务测试**

```python
@pytest.mark.anyio
async def test_large_tool_result_is_saved_as_artifact(db_session):
    artifact_id = await append_artifact(
        db_session,
        run_id="run-1",
        kind="query_result",
        payload={"rows": [{"value": 1}]},
    )
    assert artifact_id.startswith("art_")
```

- [ ] **Step 2: 添加迁移表**

建立四类数据：`business_analysis_runs`、`business_analysis_reports`、`business_analysis_artifacts`、`business_analysis_memories`。所有表都包含创建时间、更新时间和关联标识；`thread_id`、`run_id`、`artifact_id` 建唯一索引。

- [ ] **Step 3: 实现服务函数**

服务层负责事务和 JSON 序列化，禁止把完整 Prompt、密钥或原始 SQL 写入报告和 Artifact。报告只保存结构化字段：`summary`、`evidence`、`causes`、`recommendations`、`risks`、`sources`、`chart_configs`。

在 `tools.py` 中增加 `save_analysis_report` 工具包装器；包装器只接受当前运行的 `run_id` 和结构化报告，调用 `save_analysis_report_tool`，返回 `report_id`，不接受任意文件路径或任意表名。

- [ ] **Step 4: 运行迁移和服务测试**

运行：`python -m alembic upgrade head`；`pytest backend/tests/test_analysis_report.py -q`。

预期：迁移成功，报告和 Artifact 可以写入、读取并按 `thread_id` 查询。

- [ ] **Step 5: 提交**

提交：`git add backend/app/services/analysis_report.py backend/alembic/versions backend/tests/test_analysis_report.py`；`git commit -m "feat: persist analysis runs reports and artifacts"`。

---

### Task 6: 创建 Deep Agent、Prompt 和工具白名单

**Files:**
- Create: `backend/app/agent/business_analysis/prompts.py`
- Create: `backend/app/agent/business_analysis/agent.py`
- Create: `backend/tests/test_business_analysis_agent.py`
- Modify: `backend/app/core/config.py`（若 Task 1 的配置字段需要补充）

**Interfaces:**
- Produces: `get_business_analysis_agent() -> Runnable`、`BUSINESS_ANALYSIS_SYSTEM_PROMPT: str`、`BUSINESS_ANALYSIS_TOOLS: tuple`。

- [ ] **Step 1: 写 Agent 配置测试**

```python
def test_agent_exposes_only_business_tools(monkeypatch):
    captured = {}

    def fake_create_deep_agent(**kwargs):
        captured.update(kwargs)
        return object()

    monkeypatch.setattr("app.agent.business_analysis.agent.create_deep_agent", fake_create_deep_agent)
    get_business_analysis_agent(force_rebuild=True)

    names = {tool.name for tool in captured["tools"]}
    assert names == {
        "analyze_business_data",
        "search_business_knowledge",
        "get_metric_definition",
        "save_analysis_report",
    }
```

- [ ] **Step 2: 写 Prompt 内容测试**

```python
def test_prompt_requires_evidence_and_rejects_unsupported_claims():
    assert "不得编造" in BUSINESS_ANALYSIS_SYSTEM_PROMPT
    assert "数据证据" in BUSINESS_ANALYSIS_SYSTEM_PROMPT
    assert "SQL" in BUSINESS_ANALYSIS_SYSTEM_PROMPT
```

- [ ] **Step 3: 实现分层 Prompt**

Prompt 必须包含角色、工具选择规则、分析顺序、证据要求、信息不足时的表达、报告结构和安全边界；不得要求模型输出隐藏思维链。

- [ ] **Step 4: 实现 Agent 工厂**

使用 `create_deep_agent(model=get_llm(), tools=BUSINESS_ANALYSIS_TOOLS, system_prompt=BUSINESS_ANALYSIS_SYSTEM_PROMPT, ...)`。Checkpointer、Store 和运行限制通过依赖注入传入；对外只返回已编译 Runnable。工具列表使用固定 tuple，禁止从用户请求动态扩展。

- [ ] **Step 5: 运行 Agent 测试并提交**

运行：`pytest backend/tests/test_business_analysis_agent.py -q`

提交：`git add backend/app/agent/business_analysis/agent.py backend/app/agent/business_analysis/prompts.py backend/tests/test_business_analysis_agent.py`；`git commit -m "feat: create business analysis deep agent"`。

---

### Task 7: 实现上下文治理和事件安全映射

**Files:**
- Create: `backend/app/agent/business_analysis/context.py`
- Create: `backend/app/agent/business_analysis/events.py`
- Create: `backend/tests/test_business_analysis_context.py`
- Create: `backend/tests/test_business_analysis_events.py`

**Interfaces:**
- Produces: `summarize_history(messages, limit) -> list[dict]`、`compact_tool_result(result, char_limit) -> ToolResult`、`to_public_event(raw_event) -> AnalysisEvent | None`。

- [ ] **Step 1: 写上下文裁剪测试**

```python
def test_compact_tool_result_keeps_summary_and_artifact_id():
    compacted = compact_tool_result(
        {"status": "ok", "summary": "下降最大品类是家电", "data": {"rows": list(range(1000))}, "artifact_id": "art_1"},
        char_limit=200,
    )
    assert compacted["summary"] == "下降最大品类是家电"
    assert compacted["artifact_id"] == "art_1"
    assert len(str(compacted["data"])) <= 200
```

- [ ] **Step 2: 写事件脱敏测试**

```python
def test_event_mapper_drops_sql_and_exception_details():
    event = to_public_event({"type": "tool_completed", "tool": "analyze_business_data", "sql": "SELECT *", "error": "password=secret"})
    payload = event.to_sse_payload()
    assert "SELECT" not in payload
    assert "secret" not in payload
```

- [ ] **Step 3: 实现历史消息摘要**

保留最近消息原文；超过字符限制的旧消息转换为固定格式摘要，摘要只包含用户目标、已完成工具、结论摘要和 Artifact ID，不包含完整 SQL 或内部思维内容。

- [ ] **Step 4: 实现结果压缩和公开事件映射**

超过大小限制的 `data` 写入 Artifact 后只保留 `artifact_id`、字段名、行数和统计摘要。内部事件只映射到固定工具名、状态、摘要和时间戳。

- [ ] **Step 5: 运行测试并提交**

运行：`pytest backend/tests/test_business_analysis_context.py backend/tests/test_business_analysis_events.py -q`。

提交：`git add backend/app/agent/business_analysis/context.py backend/app/agent/business_analysis/events.py backend/tests/test_business_analysis_context.py backend/tests/test_business_analysis_events.py`；`git commit -m "feat: add context compaction and safe agent events"`。

---

### Task 8: 实现运行服务、Checkpoint 和并发保护

**Files:**
- Create: `backend/app/services/business_analysis_runner.py`
- Create: `backend/app/agent/business_analysis/memory.py`
- Create: `backend/app/agent/business_analysis/persistence.py`
- Create: `backend/tests/test_business_analysis_service.py`
- Reference: `backend/app/services/analysis_report.py`

**Interfaces:**
- Produces: `async def run_business_analysis(request: BusinessAnalysisRequest) -> AsyncIterator[AnalysisEvent]`、`load_user_preferences(user_id) -> UserPreferences`、`save_user_preference(user_id, key, value) -> None`。
- `persistence.py` produces: `build_postgres_checkpoint()` and `build_postgres_store()`; both return the verified async persistence implementations for the locked dependency versions.

- [ ] **Step 1: 写运行服务测试**

```python
@pytest.mark.anyio
async def test_runner_emits_start_tool_and_complete_events(fake_agent):
    events = [event async for event in run_business_analysis(_request(), agent=fake_agent)]
    assert [event.type for event in events] == ["run_started", "tool_started", "tool_completed", "run_completed"]
```

- [ ] **Step 2: 写并发测试**

```python
@pytest.mark.anyio
async def test_same_thread_cannot_start_two_runs(fake_agent):
    first = start_without_consuming(_request(thread_id="same"), agent=fake_agent)
    with pytest.raises(BusinessAnalysisBusyError):
        await collect(run_business_analysis(_request(thread_id="same"), agent=fake_agent))
    await first.cancel()
```

- [ ] **Step 3: 实现运行服务**

服务负责创建 `run_id`、加载偏好、调用 Agent 的 `astream`、限制步数和工具次数、把内部事件交给 `to_public_event`，并在结束时保存报告。使用 `asyncio.Lock` 做进程内并发保护；持久化运行表中的状态用于跨进程诊断。

- [ ] **Step 4: 接入 Checkpoint 和 Store**

根据 Task 1 的兼容性探针使用已验证的 PostgreSQL Checkpoint/Store 实现；线程配置至少包含 `thread_id` 和 `user_id`。启动时执行一次 setup/migration，关闭时释放连接池。

- [ ] **Step 5: 运行服务测试并提交**

运行：`pytest backend/tests/test_business_analysis_service.py -q`。

提交：`git add backend/app/services/business_analysis_runner.py backend/app/agent/business_analysis/memory.py backend/tests/test_business_analysis_service.py`；`git commit -m "feat: run resumable business analysis sessions"`。

---

### Task 9: 增加 FastAPI SSE 接口

**Files:**
- Create: `backend/app/api/business_analysis_routes.py`
- Modify: `backend/app/main.py` 或当前 API 路由挂载文件
- Create: `backend/tests/test_business_analysis_api.py`

**Interfaces:**
- Produces: `POST /api/v1/agent/business-analysis/runs`，请求为 `BusinessAnalysisRequest`，响应 `StreamingResponse(media_type="text/event-stream")`。

- [ ] **Step 1: 写 API 测试**

```python
def test_business_analysis_endpoint_streams_sse(client, monkeypatch):
    monkeypatch.setattr("app.api.business_analysis_routes.run_business_analysis", fake_events)
    response = client.post(
        "/api/v1/agent/business-analysis/runs",
        json={"thread_id": "thread-1", "message": "分析销售额"},
    )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert "event: run_started" in response.text
```

- [ ] **Step 2: 写非法请求测试**

覆盖空消息、超长消息、缺失线程标识、非法 UUID 字符串和同线程并发，分别断言 422、422、422、422、409。

- [ ] **Step 3: 实现 SSE 路由**

路由只做 Pydantic 校验、调用运行服务和格式化 `event:`/`data:`；不生成 SQL、不执行数据库查询、不拼接 Prompt。客户端断开时取消异步生成器并更新运行状态。

- [ ] **Step 4: 挂载路由并运行测试**

运行：`pytest backend/tests/test_business_analysis_api.py -q`；再运行：`pytest backend/tests/test_data_query_api.py backend/tests/test_rag_answer.py -q`，确认原有接口回归通过。

- [ ] **Step 5: 提交**

提交：`git add backend/app/api/business_analysis_routes.py backend/app/main.py backend/tests/test_business_analysis_api.py`；`git commit -m "feat: expose business analysis SSE api"`。

---

### Task 10: 实现前端 SSE 客户端和数据模型

**Files:**
- Create: `frontend/src/lib/api/business-analysis.ts`
- Create: `frontend/src/lib/api/business-analysis.test.ts`（沿用项目已配置的前端测试方式；若项目尚未配置测试运行器，先使用纯函数测试脚本并在本任务记录命令）

**Interfaces:**
- Produces: `BusinessAnalysisEvent` 联合类型、`runBusinessAnalysis(input, signal, onEvent): Promise<void>`、`createAnonymousUserId(): string`。

- [ ] **Step 1: 写事件解析测试**

```typescript
it("parses multiple SSE events and preserves report deltas", () => {
  const events = parseSseChunk(
    'event: status\ndata: {"label":"正在查询"}\n\n' +
    'event: report_delta\ndata: {"content":"## 结论"}\n\n',
  );
  expect(events).toEqual([
    { type: "status", label: "正在查询" },
    { type: "report_delta", content: "## 结论" },
  ]);
});
```

- [ ] **Step 2: 写断线和 AbortController 测试**

断言用户取消后 Promise 以 AbortError 结束，组件层可以区分“已取消”和“请求失败”。

- [ ] **Step 3: 实现 SSE 解析器**

使用 `fetch`、`ReadableStreamDefaultReader` 和 `TextDecoder`，按空行分割 SSE 帧，解析 `event` 和 JSON `data`；处理半包、多个事件同包和最后无空行的帧。

- [ ] **Step 4: 实现匿名标识**

从 `localStorage` 读取 `ai_data_platform_user_id`；不存在时使用 `crypto.randomUUID()` 创建并保存。读取失败时只在当前页面内使用 UUID，不把异常文本展示给用户。

- [ ] **Step 5: 运行前端检查并提交**

运行：`npm run lint`；按项目现有测试配置运行 SSE 解析测试。

提交：`git add frontend/src/lib/api/business-analysis.ts frontend/src/lib/api/business-analysis.test.ts`；`git commit -m "feat: add business analysis SSE client"`。

---

### Task 11: 构建经营分析工作台页面

**Files:**
- Create: `frontend/src/app/applications/business-analysis/page.tsx`
- Create: `frontend/src/app/applications/business-analysis/business-analysis.module.css`
- Create: `frontend/src/components/business-analysis/BusinessAnalysisWorkspace.tsx`
- Create: `frontend/src/components/business-analysis/AnalysisThreadList.tsx`
- Create: `frontend/src/components/business-analysis/AnalysisMessageList.tsx`
- Create: `frontend/src/components/business-analysis/AnalysisEventTimeline.tsx`
- Create: `frontend/src/components/business-analysis/AnalysisReportPanel.tsx`
- Modify: `frontend/src/features/platform/platform-config.ts`

**Interfaces:**
- Consumes: `runBusinessAnalysis()` 和 `BusinessAnalysisEvent`。
- Produces: 可访问 `/applications/business-analysis` 的多轮经营分析工作台。

- [ ] **Step 1: 写页面状态测试或交互验收清单**

页面必须覆盖：空状态、运行中、收到工具事件、报告增量、完成、取消、失败、历史线程切换；测试或手工验收必须逐项记录。

- [ ] **Step 2: 实现状态容器**

`BusinessAnalysisWorkspace` 管理 `threadId`、消息、事件、报告、`AbortController` 和请求阶段；卸载时取消请求；同一页面同时只允许一个运行。

- [ ] **Step 3: 实现执行时间线**

`AnalysisEventTimeline` 只渲染后端事件，不自行猜测 Agent 步骤；展示工具名称、状态、摘要和耗时，不展示原始参数。

- [ ] **Step 4: 实现报告面板**

按固定顺序渲染核心结论、数据证据、原因分析、行动建议、风险、表格、图表和知识来源；图表优先复用现有 `ResultChart`，不要新增第二套图表协议。

- [ ] **Step 5: 加入导航配置**

在 `PAGE_HREFS`、AI/智能应用模块配置和首页入口中登记页面，并明确标注“多轮经营分析、工具调用、可恢复会话”。

- [ ] **Step 6: 运行前端检查并提交**

运行：`npm run lint`；运行：`npm run build`。

提交：`git add frontend/src/app/applications/business-analysis frontend/src/components/business-analysis frontend/src/features/platform/platform-config.ts`；`git commit -m "feat: add business analysis workspace"`。

---

### Task 12: 实现长期偏好记忆和线程历史

**Files:**
- Modify: `backend/app/agent/business_analysis/memory.py`
- Modify: `backend/app/services/analysis_report.py`
- Modify: `backend/app/api/business_analysis_routes.py`
- Modify: `frontend/src/components/business-analysis/AnalysisThreadList.tsx`
- Create: `backend/tests/test_business_analysis_memory.py`

**Interfaces:**
- Produces: `GET /api/v1/agent/business-analysis/threads`、`GET /api/v1/agent/business-analysis/threads/{thread_id}`、`UserPreferences` 读写接口。

- [ ] **Step 1: 写偏好记忆测试**

```python
@pytest.mark.anyio
async def test_preference_is_applied_to_new_thread(memory_store):
    await save_user_preference(memory_store, "user-1", "currency_unit", "万元")
    preferences = await load_user_preferences(memory_store, "user-1")
    assert preferences["currency_unit"] == "万元"
```

- [ ] **Step 2: 实现安全偏好白名单**

只允许 `currency_unit`、`preferred_region`、`preferred_chart`、`report_style` 四个键；值长度、枚举和 JSON 类型固定校验。禁止把任意用户消息直接作为长期记忆写入。

- [ ] **Step 3: 实现线程历史查询接口**

只返回 `thread_id`、标题摘要、最后更新时间、运行状态和报告 ID；不返回完整工具参数、SQL 或内部 Prompt。

- [ ] **Step 4: 接入前端会话列表**

页面加载线程列表，切换线程时拉取公开消息和报告；无历史时显示空状态；当前运行线程禁止被删除或覆盖。

- [ ] **Step 5: 运行测试并提交**

运行：`pytest backend/tests/test_business_analysis_memory.py backend/tests/test_business_analysis_api.py -q`；`npm run lint`。

提交：`git add backend/app/agent/business_analysis/memory.py backend/app/services/analysis_report.py backend/app/api/business_analysis_routes.py frontend/src/components/business-analysis/AnalysisThreadList.tsx backend/tests/test_business_analysis_memory.py`；`git commit -m "feat: persist analysis threads and preferences"`。

---

### Task 13: 增加集成测试、评测样例和运行文档

**Files:**
- Create: `backend/tests/test_business_analysis_integration.py`
- Create: `backend/tests/fixtures/business_analysis_cases.json`
- Modify: `README.md`
- Modify: `frontend/README.md`（若当前文档包含页面清单）

**Interfaces:**
- Produces: 可重复运行的经营分析评测集和本地启动说明。

- [ ] **Step 1: 写三类集成场景**

至少覆盖：

```text
趋势下钻：第一次查区域趋势，第二次查品类贡献，最后生成报告。
知识增强：数据查询成功，知识库命中促销规则并返回来源。
降级场景：知识库不可用，但仍返回数据结论并标记知识来源缺失。
```

- [ ] **Step 2: 写安全回归场景**

断言 Agent 无法调用未注册工具、无法返回 SQL、单次运行超过最大步数会结束、工具异常不会泄露密钥文本。

- [ ] **Step 3: 实现 Fake Model/Fake Tools 集成测试**

测试默认不依赖真实模型密钥；使用固定工具调用轨迹验证 Agent Loop、事件顺序、报告持久化和线程恢复。真实模型只放在手工 smoke 测试，不进入 CI 必跑路径。

- [ ] **Step 4: 更新 README**

补充依赖安装、数据库迁移、SSE 接口、页面地址、匿名 UUID 限制、工具安全边界和示例问题。明确说明 `deepagents` 是 SDK，`dcode` 不属于本项目运行依赖。

- [ ] **Step 5: 运行完整验证**

运行：`pytest backend/tests -q`；`npm run lint`；`npm run build`；启动 Docker Compose 后手工访问 `/applications/business-analysis`，完成一次多工具经营分析。

- [ ] **Step 6: 提交**

提交：`git add backend/tests/test_business_analysis_integration.py backend/tests/fixtures/business_analysis_cases.json README.md frontend/README.md`；`git commit -m "test: add business analysis evaluation and docs"`。

---

## 完成定义

当以下条件全部满足时，功能才算完成：

1. 用户可以在新页面提交一个复杂经营问题。
2. Agent 至少根据中间结果进行两次工具调用。
3. 数据工具复用现有安全问数图，未新增数据库旁路。
4. 页面通过 SSE 展示运行状态、工具调用和报告。
5. 同一线程可以追问，刷新后可以恢复。
6. 用户偏好可以在新线程中生效。
7. 大工具结果不会无界增长模型上下文。
8. 现有智能问数、知识问答和安全查询测试全部通过。
9. 新增集成测试验证成功、降级、超时、并发和安全边界。
10. README 能让面试官理解 Deep Agents 在系统中的位置和实际业务价值。

## 计划自检

- 规格中的目标、工具边界、SSE、记忆、上下文、安全和验收标准均有对应任务。
- 计划不要求复制官方源码或集成 `dcode`。
- 任务按依赖顺序排列：契约 → 工具 → 持久化 → Agent → 服务 → API → 前端 → 记忆 → 集成。
- 每个任务都有测试入口和提交点，现有问数接口的回归测试在 Task 9 和 Task 13 执行。
- 未使用 `TODO`、`TBD` 或“稍后补充”等未定义步骤。
