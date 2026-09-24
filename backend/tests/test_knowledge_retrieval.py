"""统一检索编排（rewrite → hybrid → rerank）的测试。

**本文件不调模型、不算向量、不连数据库、不发任何网络请求。**
三个外部环节全部注入替身，所以「谁先谁后」「各收到了什么参数」
都能逐条断言——这正是编排层唯一值得测的东西：它自己不产生任何结果，
只负责把三件事按正确顺序、用正确的参数串起来。

配置用 `Settings(_env_file=None)` 构造，**完全不读本地 .env**。
"""

import asyncio
import dataclasses
import pathlib

import pytest

from app.core.config import Settings
from app.core.exceptions import ConfigurationError
from app.services import knowledge_retrieval
from app.services.knowledge_retrieval import (
    KnowledgeRetrievalError,
    RetrievalResult,
    retrieve_knowledge,
)
from app.services.knowledge_search import (
    ChunkContent,
    KnowledgeSearchError,
    KnowledgeSearchResult,
)
from app.services.query_rewrite import QueryRewriteResult
from app.services.retrieval_fusion import RetrievalCandidate

MODULE_PATH = pathlib.Path(knowledge_retrieval.__file__)

QUESTION = "用户原问题"
REWRITTEN = "改写问题一"
KEYWORDS = ("术语甲", "概念乙")


# --------------------------------------------------------------------------
# 构造工具
# --------------------------------------------------------------------------


def make_env_values(**overrides) -> dict:
    values = {
        "rag_rerank_enabled": True,
        "rag_retrieval_candidate_limit": 20,
        "rag_final_top_k": 5,
        "rerank_provider": "dashscope",
        "rerank_model": "qwen3-rerank",
        "rerank_api_key": "sk-fake-for-tests",
        "rerank_base_url": "https://example.invalid/compatible-api/v1",
        "rerank_timeout_seconds": 10.0,
    }
    values.update(overrides)
    return values


def patch_settings(monkeypatch, **overrides) -> Settings:
    settings = Settings(_env_file=None, **make_env_values(**overrides))
    monkeypatch.setattr(knowledge_retrieval, "get_settings", lambda: settings)
    return settings


def make_plan(**overrides) -> QueryRewriteResult:
    values = {
        "original_query": QUESTION,
        "rewritten_queries": (REWRITTEN,),
        "keywords": KEYWORDS,
    }
    values.update(overrides)
    return QueryRewriteResult(**values)


def make_chunk(chunk_id: int) -> ChunkContent:
    return ChunkContent(
        chunk_id=chunk_id,
        document_id=100 + chunk_id,
        source_file="文档.md",
        document_title="文档标题",
        section_title="小节标题",
        chunk_index=chunk_id,
        content=f"第 {chunk_id} 段正文",
        embedding_model="text-embedding-v4",
    )


def make_candidate(chunk_id: int, *, rerank_score: float | None = None) -> RetrievalCandidate:
    return RetrievalCandidate(
        chunk=make_chunk(chunk_id),
        vector_rank=chunk_id,
        keyword_rank=None,
        rrf_score=1 / (60 + chunk_id),
        matched_queries=(QUESTION,),
        distance=0.1 * chunk_id,
        similarity=1 - 0.1 * chunk_id,
        rerank_score=rerank_score,
    )


def make_candidates(count: int) -> list[RetrievalCandidate]:
    return [make_candidate(chunk_id) for chunk_id in range(1, count + 1)]


class FakeRewriter:
    """记录被问到的问题，返回预设的改写计划或抛异常。"""

    def __init__(self, plan=None, *, error=None) -> None:
        self.plan = plan if plan is not None else make_plan()
        self.error = error
        self.calls: list[str] = []

    async def __call__(self, question):
        self.calls.append(question)
        if self.error is not None:
            raise self.error
        return self.plan


class FakeHybrid:
    """记录收到的计划与 candidate_limit，返回预设候选。"""

    def __init__(self, candidates=None, *, error=None) -> None:
        self.candidates = list(candidates) if candidates is not None else make_candidates(3)
        self.error = error
        self.calls: list[tuple[object, int]] = []

    async def __call__(self, query_plan, *, candidate_limit, **kwargs):
        self.calls.append((query_plan, candidate_limit))
        if self.error is not None:
            raise self.error
        return list(self.candidates)


class FakeRerank:
    """记录 query / 候选 / top_n；成功时给前 top_n 条写上 rerank_score。

    默认行为刻意与真实的 rerank_candidates 对齐：成功才写分数，
    降级时原样返回——这样「rerank_applied 怎么算」才测得准。
    """

    def __init__(self, *, applied: bool = True, error=None) -> None:
        self.applied = applied
        self.error = error
        self.calls: list[tuple[str, list, int]] = []

    @property
    def query(self) -> str:
        return self.calls[-1][0]

    @property
    def candidates(self) -> list:
        return self.calls[-1][1]

    @property
    def top_n(self) -> int:
        return self.calls[-1][2]

    async def __call__(self, query, candidates, *, top_n, **kwargs):
        self.calls.append((query, list(candidates), top_n))
        if self.error is not None:
            raise self.error
        if not self.applied:
            return list(candidates[:top_n])
        return [
            dataclasses.replace(candidate, rerank_score=1.0 - index * 0.1)
            for index, candidate in enumerate(candidates[:top_n])
        ]


def run_retrieval(monkeypatch, *, rewriter=None, hybrid=None, rerank=None, **kwargs):
    rewriter = rewriter if rewriter is not None else FakeRewriter()
    hybrid = hybrid if hybrid is not None else FakeHybrid()
    rerank = rerank if rerank is not None else FakeRerank()
    result = asyncio.run(
        retrieve_knowledge(
            kwargs.pop("question", QUESTION),
            rewriter=rewriter,
            hybrid_retriever=hybrid,
            candidate_reranker=rerank,
            **kwargs,
        )
    )
    return result, rewriter, hybrid, rerank


# --------------------------------------------------------------------------
# 调用顺序与参数
# --------------------------------------------------------------------------


def test_the_three_stages_run_in_order(monkeypatch):
    """★ 顺序是 rewrite → hybrid → rerank，不能调换。

    用一条共享的调用日志来断言，而不是分别看三个替身——
    分开看只能证明「都调了」，证明不了「顺序对」。
    """
    patch_settings(monkeypatch)
    log: list[str] = []

    class Recording:
        def __init__(self, name, result) -> None:
            self.name = name
            self.result = result

        async def __call__(self, *args, **kwargs):
            log.append(self.name)
            return self.result

    plan = make_plan()
    asyncio.run(
        retrieve_knowledge(
            QUESTION,
            rewriter=Recording("rewrite", plan),
            hybrid_retriever=Recording("hybrid", make_candidates(2)),
            candidate_reranker=Recording("rerank", make_candidates(2)),
        )
    )

    assert log == ["rewrite", "hybrid", "rerank"]


def test_the_rewriter_gets_the_normalized_question(monkeypatch):
    patch_settings(monkeypatch)
    _, rewriter, _, _ = run_retrieval(monkeypatch, question="  用户原问题  ")

    assert rewriter.calls == [QUESTION]


def test_the_hybrid_retriever_gets_the_whole_query_plan(monkeypatch):
    """★ 改写结果要**整体**传给召回层：原问题、改写问题、关键词都在里面。"""
    patch_settings(monkeypatch)
    plan = make_plan()
    _, _, hybrid, _ = run_retrieval(monkeypatch, rewriter=FakeRewriter(plan))

    received, _ = hybrid.calls[0]
    assert received is plan
    assert received.original_query == QUESTION
    assert received.rewritten_queries == (REWRITTEN,)
    assert received.keywords == KEYWORDS


def test_the_hybrid_retriever_gets_the_configured_candidate_limit(monkeypatch):
    patch_settings(monkeypatch, rag_retrieval_candidate_limit=12)
    _, _, hybrid, _ = run_retrieval(monkeypatch)

    assert hybrid.calls[0][1] == 12


def test_the_reranker_gets_the_original_query_not_a_rewrite(monkeypatch):
    """★ 精排只认用户原问题。

    改写是模型换的说法，可能把限定词抹平；拿它去精排，
    选出来的候选就偏离了用户真正问的东西。
    """
    patch_settings(monkeypatch)
    _, _, _, rerank = run_retrieval(monkeypatch)

    assert rerank.query == QUESTION
    assert rerank.query != REWRITTEN


def test_the_reranker_never_sees_the_rewritten_queries(monkeypatch):
    """改写问题连「出现过」都不该出现——它不是精排的输入。"""
    patch_settings(monkeypatch)
    _, _, _, rerank = run_retrieval(monkeypatch)

    query, candidates, _ = rerank.calls[0]
    assert REWRITTEN not in query
    assert all(REWRITTEN not in candidate.chunk.content for candidate in candidates)


def test_the_reranker_gets_the_candidates_from_the_hybrid_stage(monkeypatch):
    patch_settings(monkeypatch)
    candidates = make_candidates(4)
    _, _, _, rerank = run_retrieval(monkeypatch, hybrid=FakeHybrid(candidates))

    assert [c.chunk.chunk_id for c in rerank.candidates] == [1, 2, 3, 4]


def test_final_top_k_is_forwarded_to_the_reranker(monkeypatch):
    patch_settings(monkeypatch)
    _, _, _, rerank = run_retrieval(monkeypatch, final_top_k=3)

    assert rerank.top_n == 3


def test_the_configured_final_top_k_is_the_default(monkeypatch):
    patch_settings(monkeypatch, rag_final_top_k=2)
    _, _, _, rerank = run_retrieval(monkeypatch)

    assert rerank.top_n == 2


def test_the_requested_top_k_is_not_used_as_the_recall_width(monkeypatch):
    """★ top_k 只决定最终留几条，不该把每一路召回也压到那么窄。

    粗召回要宽（20 条），精排后才截成 top_k（3 条）——
    反过来的话，答案很可能在召回阶段就已经被丢掉了。
    """
    patch_settings(monkeypatch, rag_retrieval_candidate_limit=20)
    _, _, hybrid, rerank = run_retrieval(monkeypatch, final_top_k=3)

    assert hybrid.calls[0][1] == 20
    assert rerank.top_n == 3


# --------------------------------------------------------------------------
# 返回值
# --------------------------------------------------------------------------


def test_the_result_is_a_retrieval_result(monkeypatch):
    patch_settings(monkeypatch)
    result, _, _, _ = run_retrieval(monkeypatch)

    assert isinstance(result, RetrievalResult)
    assert isinstance(result.results, tuple)
    assert result.original_query == QUESTION


def test_search_queries_keep_the_plan_order(monkeypatch):
    """原问题在前、改写在后——顺序是语义的一部分，不能重排。"""
    patch_settings(monkeypatch)
    plan = make_plan(rewritten_queries=("改写一", "改写二"))
    result, _, _, _ = run_retrieval(monkeypatch, rewriter=FakeRewriter(plan))

    assert result.search_queries == (QUESTION, "改写一", "改写二")


def test_search_queries_shrink_when_there_is_no_rewrite(monkeypatch):
    patch_settings(monkeypatch)
    plan = make_plan(rewritten_queries=())
    result, _, _, _ = run_retrieval(monkeypatch, rewriter=FakeRewriter(plan))

    assert result.search_queries == (QUESTION,)


def test_candidates_considered_is_the_pre_rerank_count(monkeypatch):
    """它是「精排前有多少候选」——精排之后剩几条是 results 的长度。"""
    patch_settings(monkeypatch)
    result, _, _, _ = run_retrieval(
        monkeypatch, hybrid=FakeHybrid(make_candidates(7)), final_top_k=3
    )

    assert result.candidates_considered == 7
    assert len(result.results) == 3


def test_results_follow_the_rerank_order(monkeypatch):
    patch_settings(monkeypatch)
    result, _, _, _ = run_retrieval(monkeypatch)

    assert [candidate.rerank_score for candidate in result.results] == pytest.approx([1.0, 0.9, 0.8])


def test_the_original_candidates_are_not_mutated(monkeypatch):
    patch_settings(monkeypatch)
    candidates = make_candidates(3)

    run_retrieval(monkeypatch, hybrid=FakeHybrid(candidates))

    assert all(candidate.rerank_score is None for candidate in candidates)


# --------------------------------------------------------------------------
# rerank_applied 的语义
# --------------------------------------------------------------------------


def test_rerank_applied_is_true_when_a_score_came_back(monkeypatch):
    patch_settings(monkeypatch)
    result, _, _, _ = run_retrieval(monkeypatch, rerank=FakeRerank(applied=True))

    assert result.rerank_applied is True


def test_rerank_applied_is_false_when_the_reranker_did_not_score(monkeypatch):
    """★ 退回 RRF 顺序（供应商失败 / 功能关闭）时必须是 False。

    只看 RAG_RERANK_ENABLED 是不够的：开关开着但这次调用失败了，
    精排其实一次都没生效。
    """
    patch_settings(monkeypatch)
    result, _, _, _ = run_retrieval(monkeypatch, rerank=FakeRerank(applied=False))

    assert result.rerank_applied is False


def test_rerank_applied_is_false_when_there_are_no_candidates(monkeypatch):
    patch_settings(monkeypatch)
    result, _, _, _ = run_retrieval(monkeypatch, hybrid=FakeHybrid([]))

    assert result.rerank_applied is False
    assert result.results == ()


def test_rerank_applied_does_not_look_at_the_switch(monkeypatch):
    """★ 开关打开但精排没生效时仍然是 False。

    这一条专门防「用配置值糊弄过去」的实现：
    配置说开着，不代表这次请求真的精排过。
    """
    patch_settings(monkeypatch, rag_rerank_enabled=True)
    result, _, _, _ = run_retrieval(monkeypatch, rerank=FakeRerank(applied=False))

    assert result.rerank_applied is False


# --------------------------------------------------------------------------
# 短路：候选为空
# --------------------------------------------------------------------------


def test_an_empty_candidate_list_skips_the_reranker(monkeypatch):
    """★ 没有候选就没有可精排的东西：一次调用都不该发。"""
    patch_settings(monkeypatch)
    rerank = FakeRerank()
    result, _, _, _ = run_retrieval(monkeypatch, hybrid=FakeHybrid([]), rerank=rerank)

    assert rerank.calls == []
    assert result.results == ()
    assert result.candidates_considered == 0


def test_an_empty_result_is_returned_normally(monkeypatch):
    """候选为空是正常结果，不是错误——知识库里可能真的没有相关内容。"""
    patch_settings(monkeypatch)

    result, _, _, _ = run_retrieval(monkeypatch, hybrid=FakeHybrid([]))

    assert result.original_query == QUESTION
    assert result.search_queries == (QUESTION, REWRITTEN)
    assert result.results == ()


def test_the_rewriter_still_runs_before_the_empty_short_circuit(monkeypatch):
    patch_settings(monkeypatch)
    rewriter = FakeRewriter()

    run_retrieval(monkeypatch, rewriter=rewriter, hybrid=FakeHybrid([]))

    assert rewriter.calls == [QUESTION]


# --------------------------------------------------------------------------
# 参数校验
# --------------------------------------------------------------------------


@pytest.mark.parametrize("bad", [0, -1, 1.5, "3", True])
def test_invalid_final_top_k_is_rejected(monkeypatch, bad):
    patch_settings(monkeypatch)
    rerank = FakeRerank()

    with pytest.raises(KnowledgeRetrievalError):
        run_retrieval(monkeypatch, final_top_k=bad, rerank=rerank)

    assert rerank.calls == []


def test_final_top_k_larger_than_the_candidate_limit_is_rejected(monkeypatch):
    """★ 最终留下的条数不可能超过候选总数，配成这样只可能是哪里写反了。"""
    patch_settings(monkeypatch, rag_retrieval_candidate_limit=5)

    with pytest.raises(KnowledgeRetrievalError) as error:
        run_retrieval(monkeypatch, final_top_k=6)

    assert "5" in str(error.value)


def test_final_top_k_equal_to_the_candidate_limit_is_allowed(monkeypatch):
    patch_settings(monkeypatch, rag_retrieval_candidate_limit=5)
    _, _, _, rerank = run_retrieval(monkeypatch, final_top_k=5)

    assert rerank.top_n == 5


@pytest.mark.parametrize("blank", ["", "   ", "\n\t "])
def test_a_blank_question_fails_before_any_external_call(monkeypatch, blank):
    patch_settings(monkeypatch)
    rewriter, hybrid, rerank = FakeRewriter(), FakeHybrid(), FakeRerank()

    with pytest.raises(KnowledgeRetrievalError):
        run_retrieval(monkeypatch, question=blank, rewriter=rewriter, hybrid=hybrid, rerank=rerank)

    assert rewriter.calls == []
    assert hybrid.calls == []
    assert rerank.calls == []


def test_none_question_is_rejected(monkeypatch):
    with pytest.raises(KnowledgeRetrievalError):
        run_retrieval(monkeypatch, question=None)


def test_the_question_error_does_not_echo_the_question(monkeypatch):
    with pytest.raises(KnowledgeRetrievalError) as error:
        run_retrieval(monkeypatch, question="   ")

    assert "sk-" not in str(error.value)


# --------------------------------------------------------------------------
# 降级与异常传递
# --------------------------------------------------------------------------


def test_the_rewriter_degrades_by_itself(monkeypatch):
    """★ 改写失败由它自己降级成「只用原问题」，编排层不重写一版。

    这里模拟它的降级结果：只含原问题的计划。
    """
    patch_settings(monkeypatch)
    degraded = make_plan(rewritten_queries=(), keywords=())
    result, _, hybrid, rerank = run_retrieval(
        monkeypatch, rewriter=FakeRewriter(degraded)
    )

    assert result.search_queries == (QUESTION,)
    assert hybrid.calls[0][0].search_queries == (QUESTION,)
    assert rerank.query == QUESTION
    assert len(result.results) == 3  # 召回与精排照常进行


def test_a_reranker_fallback_is_passed_through_unchanged(monkeypatch):
    """★ 精排失败已经由它自己降级成 RRF 顺序，编排层不能再去改结果。"""
    patch_settings(monkeypatch)
    candidates = make_candidates(4)
    result, _, _, _ = run_retrieval(
        monkeypatch, hybrid=FakeHybrid(candidates), rerank=FakeRerank(applied=False), final_top_k=2
    )

    assert [c.chunk.chunk_id for c in result.results] == [1, 2]
    assert all(c.rerank_score is None for c in result.results)


def test_a_hybrid_failure_propagates(monkeypatch):
    """★ 两路召回全失败时 hybrid_search 抛受控异常，编排层原样往上抛。

    这里不吞它——吞掉就意味着「检索失败」和「没有相关资料」
    长得一模一样，而前者该报错、后者是正常结果。
    """
    patch_settings(monkeypatch)

    with pytest.raises(KnowledgeSearchError):
        run_retrieval(monkeypatch, hybrid=FakeHybrid(error=KnowledgeSearchError("全部失败")))


def test_a_hybrid_failure_does_not_reach_the_reranker(monkeypatch):
    patch_settings(monkeypatch)
    rerank = FakeRerank()

    with pytest.raises(KnowledgeSearchError):
        run_retrieval(
            monkeypatch, hybrid=FakeHybrid(error=KnowledgeSearchError("全部失败")), rerank=rerank
        )

    assert rerank.calls == []


def test_configuration_errors_are_not_swallowed(monkeypatch):
    """★ 配置错误是部署问题，必须当场暴露。

    把它降级成「悄悄不用精排」，会让「Key 没填」和「服务挂了」长得一模一样。
    """
    settings = Settings(_env_file=None, **make_env_values(rerank_api_key=""))
    monkeypatch.setattr(knowledge_retrieval, "get_settings", lambda: settings)

    with pytest.raises(ConfigurationError):
        run_retrieval(monkeypatch)


def test_programming_errors_are_not_swallowed(monkeypatch):
    """★ TypeError / AssertionError 是程序 bug，不能包成「检索失败」。"""
    patch_settings(monkeypatch)

    with pytest.raises(TypeError):
        run_retrieval(monkeypatch, rewriter=FakeRewriter(error=TypeError("bug")))

    with pytest.raises(AssertionError):
        run_retrieval(monkeypatch, hybrid=FakeHybrid(error=AssertionError("bug")))

    with pytest.raises(TypeError):
        run_retrieval(monkeypatch, rerank=FakeRerank(error=TypeError("bug")))


def test_the_module_never_wraps_the_whole_flow_in_a_broad_except():
    """★ 不允许「一个 except Exception 包住整个编排」。

    那样会把配置错误、程序错误和外部故障全变成同一种结果，
    而这三者的处理方式正好相反。
    """
    import ast

    tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))

    for node in ast.walk(tree):
        if isinstance(node, ast.ExceptHandler):
            caught = node.type
            assert not (
                caught is None
                or (isinstance(caught, ast.Name) and caught.id == "Exception")
            ), "编排层不该捕获 Exception"


# --------------------------------------------------------------------------
# 注入与模块卫生
# --------------------------------------------------------------------------


def test_all_three_collaborators_can_be_injected(monkeypatch):
    patch_settings(monkeypatch)
    _, rewriter, hybrid, rerank = run_retrieval(monkeypatch)

    assert len(rewriter.calls) == 1
    assert len(hybrid.calls) == 1
    assert len(rerank.calls) == 1


def test_injecting_collaborators_means_no_production_calls(monkeypatch):
    """★ 注入了替身就不该再碰生产实现。

    把三个生产函数都换成一调用就炸的桩：真去用就会当场失败。
    """
    patch_settings(monkeypatch)

    def explode(*args, **kwargs):
        raise AssertionError("注入了替身就不该调用生产实现")

    monkeypatch.setattr(knowledge_retrieval, "rewrite_query", explode)
    monkeypatch.setattr(knowledge_retrieval, "hybrid_search", explode)
    monkeypatch.setattr(knowledge_retrieval, "rerank_candidates", explode)

    result, _, _, _ = run_retrieval(monkeypatch)

    assert len(result.results) == 3


def test_the_defaults_are_the_production_stages():
    """默认值必须指向生产实现——否则「上线忘了接线」不会有人发现。"""
    import inspect

    parameters = inspect.signature(retrieve_knowledge).parameters

    assert parameters["rewriter"].default is knowledge_retrieval.rewrite_query
    assert parameters["hybrid_retriever"].default is knowledge_retrieval.hybrid_search
    assert parameters["candidate_reranker"].default is knowledge_retrieval.rerank_candidates


def test_the_module_does_not_call_the_answer_model_or_embedding():
    """★ 编排层不拼 Prompt、不调回答模型、不算向量。"""
    import ast

    tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)

    forbidden = ("app.core.llm", "app.services.embedding", "langchain", "openai", "httpx")
    assert not [module for module in modules if module.startswith(forbidden)]


def test_the_module_does_not_import_the_database_layer():
    source = MODULE_PATH.read_text(encoding="utf-8")

    assert "repositories.database" not in source
    assert "sqlalchemy" not in source


def test_the_module_does_not_build_prompts():
    """Prompt 只有一份，在 rag_answer.py 里；编排层不复制第二份。"""
    source = MODULE_PATH.read_text(encoding="utf-8")

    assert "PROMPT" not in source
    assert "untrusted" not in source


@pytest.mark.parametrize(
    "term", ["客单价", "销售额", "会员", "复购率", "华东", "黑金会员", "年底旺季"]
)
def test_the_module_has_no_hardcoded_domain_vocabulary(term):
    assert term not in MODULE_PATH.read_text(encoding="utf-8")


def test_retrieval_result_is_frozen():
    result = RetrievalResult(
        original_query=QUESTION,
        search_queries=(QUESTION,),
        candidates_considered=0,
        rerank_applied=False,
        results=(),
    )

    with pytest.raises(dataclasses.FrozenInstanceError):
        result.rerank_applied = True


def test_the_legacy_vector_result_still_has_the_shared_shape():
    """回归：纯向量结果也满足编排层对「候选」的最小要求。"""
    vector_result = KnowledgeSearchResult(
        chunk_id=1,
        document_id=1,
        source_file="文档.md",
        document_title="标题",
        section_title="小节",
        chunk_index=0,
        content="正文",
        embedding_model=None,
        distance=0.2,
        similarity=0.8,
    )

    assert isinstance(vector_result.chunk, ChunkContent)
    assert vector_result.distance == pytest.approx(0.2)
