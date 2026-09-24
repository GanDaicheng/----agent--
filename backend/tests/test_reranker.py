"""Reranker 的单元测试：候选文本构造、Provider 适配器、编排函数。

**本文件不发任何真实网络请求。** 三处注入缝：
- Provider 层注入 `httpx.MockTransport`——请求真的会被 httpx 组装出来，
  只是不出网，所以 URL、方法、Header、请求体都能逐字段断言；
- 编排层注入假 `Reranker`；
- 配置层 monkeypatch `reranker.get_settings`，并且用 `Settings(_env_file=None)`
  构造，**完全不读本地 .env**——那里现在放着真实的百炼地址和 Key。

Provider 与编排放在同一个文件而不是拆开：拆开之后要共享一堆构造工具，
反而更难看清「一条候选是怎么从 RRF 走到精排结果的」。
"""

import asyncio
import dataclasses
import json
import pathlib

import httpx
import pytest

from app.core.config import RERANK_PATH, RerankSettings, Settings
from app.core.exceptions import ConfigurationError
from app.services import reranker
from app.services.knowledge_search import ChunkContent, KnowledgeSearchError
from app.services.reranker import (
    RERANK_INSTRUCT,
    DashScopeReranker,
    RerankItem,
    RerankerError,
    RerankerProviderError,
    build_rerank_document,
    build_rerank_payload,
    build_rerank_url,
    parse_rerank_response,
    rerank_candidates,
)
from app.services.retrieval_fusion import RetrievalCandidate

MODULE_PATH = pathlib.Path(reranker.__file__)

FAKE_KEY = "sk-fake-rerank-key-for-tests-0123456789"
FAKE_BASE_URL = "https://fake-workspace-id.cn-beijing.maas.aliyuncs.com/compatible-api/v1"
FAKE_MODEL = "qwen3-rerank"

QUERY = "用户原问题"
DOCUMENT_TEXT = "某段候选正文"


# --------------------------------------------------------------------------
# 构造工具
# --------------------------------------------------------------------------


def make_rerank_settings(**overrides) -> RerankSettings:
    settings = Settings(_env_file=None, **make_env_values(**overrides))
    return settings.require_rerank_settings()


def make_env_values(**overrides) -> dict:
    values = {
        "rerank_provider": "dashscope",
        "rerank_model": FAKE_MODEL,
        "rerank_api_key": FAKE_KEY,
        "rerank_base_url": FAKE_BASE_URL,
        "rerank_timeout_seconds": 10.0,
        "rag_rerank_enabled": True,
        "rag_retrieval_candidate_limit": 20,
        "rag_final_top_k": 5,
    }
    values.update(overrides)
    return values


def patch_settings(monkeypatch, **overrides) -> RerankSettings:
    """把编排函数读到的配置换掉，保证测试完全不碰本地 .env。"""
    settings = Settings(_env_file=None, **make_env_values(**overrides))
    monkeypatch.setattr(reranker, "get_settings", lambda: settings)
    return settings.require_rerank_settings()


def make_chunk(chunk_id: int, **overrides) -> ChunkContent:
    values = {
        "chunk_id": chunk_id,
        "document_id": 100 + chunk_id,
        "source_file": "文档.md",
        "document_title": "文档标题",
        "section_title": "小节标题",
        "chunk_index": chunk_id,
        "content": "正文内容",
        "embedding_model": "text-embedding-v4",
    }
    values.update(overrides)
    return ChunkContent(**values)


def make_candidate(chunk_id: int, **overrides) -> RetrievalCandidate:
    values = {
        "chunk": make_chunk(chunk_id),
        "vector_rank": 1,
        "keyword_rank": None,
        "rrf_score": 0.03,
        "matched_queries": ("原问题",),
        "distance": 0.2,
        "similarity": 0.8,
    }
    values.update(overrides)
    return RetrievalCandidate(**values)


def make_candidates(count: int) -> list[RetrievalCandidate]:
    return [make_candidate(chunk_id) for chunk_id in range(1, count + 1)]


class FakeTransport:
    """httpx.MockTransport 的处理器：记录请求，按脚本返回响应或抛异常。"""

    def __init__(self, *, json_body=None, status_code=200, text=None, error=None) -> None:
        self.json_body = json_body
        self.status_code = status_code
        self.text = text
        self.error = error
        self.requests: list[httpx.Request] = []

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self._handle)

    def _handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.error is not None:
            raise self.error
        if self.text is not None:
            return httpx.Response(self.status_code, text=self.text)
        return httpx.Response(self.status_code, json=self.json_body)

    @property
    def request(self) -> httpx.Request:
        return self.requests[-1]

    def sent_body(self) -> dict:
        return json.loads(self.request.content.decode("utf-8"))


def make_provider(transport: FakeTransport, *, settings=None) -> DashScopeReranker:
    return DashScopeReranker(
        settings or make_rerank_settings(), transport=transport.transport()
    )


async def run_provider(transport: FakeTransport, **kwargs):
    provider = kwargs.pop("provider", None) or make_provider(transport)
    documents = kwargs.pop("documents", [DOCUMENT_TEXT])
    top_n = kwargs.pop("top_n", 1)
    return await provider.rerank(QUERY, documents, top_n=top_n)


class FakeReranker:
    """记录调用参数，按脚本返回结果或抛异常。"""

    def __init__(self, items=None, *, error=None) -> None:
        self.items = items
        self.error = error
        self.calls: list[tuple[str, list[str], int]] = []

    @property
    def documents(self) -> list[str]:
        return self.calls[-1][1] if self.calls else []

    async def rerank(self, query, documents, *, top_n):
        self.calls.append((query, list(documents), top_n))
        if self.error is not None:
            raise self.error
        return self.items if self.items is not None else []


def run_rerank(candidates, *, reranker_=None, **kwargs):
    return asyncio.run(
        rerank_candidates(QUERY, candidates, reranker=reranker_, **kwargs)
    )


# --------------------------------------------------------------------------
# 候选文本构造
# --------------------------------------------------------------------------


def test_document_contains_the_title_section_and_body():
    text = build_rerank_document(make_candidate(1))

    assert "文档标题" in text
    assert "小节标题" in text
    assert "正文内容" in text


def test_document_keeps_the_body_intact():
    """正文一个字都不能改：reranker 判的就是这段文字本身。"""
    body = "第一段。\n\n第二段：`orders.net_amount` 与 COUNT(DISTINCT order_no)。"
    text = build_rerank_document(make_candidate(1, chunk=make_chunk(1, content=body)))

    assert body in text
    assert text.endswith(body)


def test_document_does_not_contain_internal_identifiers():
    """★ 内部主键、排名、分数都不该进候选文本。

    reranker 判的是「这段文字答不答这个问题」；给它排名信息只会干扰判断，
    给主键则完全无用，还多一份泄露面。
    """
    candidate = make_candidate(7, keyword_score=88.0, matched_terms=("keywords_exact",))
    text = build_rerank_document(candidate)

    assert "7" not in text  # chunk_id / chunk_index
    assert "107" not in text  # document_id
    assert candidate.chunk.source_file not in text
    assert "rrf" not in text.lower()
    assert "0.03" not in text
    assert "88.0" not in text
    assert "keywords_exact" not in text


def test_document_does_not_change_the_candidate():
    candidate = make_candidate(1)

    build_rerank_document(candidate)

    assert candidate.rerank_score is None
    assert candidate.chunk.content == "正文内容"


def test_documents_follow_the_candidate_order():
    candidates = make_candidates(3)

    documents = [build_rerank_document(candidate) for candidate in candidates]

    assert len(documents) == 3
    assert all(isinstance(document, str) for document in documents)


# --------------------------------------------------------------------------
# URL 与请求体（纯函数）
# --------------------------------------------------------------------------


def test_url_is_the_base_plus_the_rerank_path():
    assert build_rerank_url(FAKE_BASE_URL) == FAKE_BASE_URL + RERANK_PATH


def test_url_survives_a_trailing_slash_on_the_base():
    assert build_rerank_url(FAKE_BASE_URL + "/") == FAKE_BASE_URL + RERANK_PATH


def test_url_is_never_doubled():
    """配置层已经拦住了带 /reranks 的地址，这里再确认拼接只会加一次。"""
    url = build_rerank_url(FAKE_BASE_URL)

    assert url.count(RERANK_PATH) == 1


def test_payload_carries_the_documented_fields():
    payload = build_rerank_payload(
        model=FAKE_MODEL, query=QUERY, documents=["甲", "乙"], top_n=2
    )

    assert payload == {
        "model": FAKE_MODEL,
        "query": QUERY,
        "documents": ["甲", "乙"],
        "top_n": 2,
        "instruct": RERANK_INSTRUCT,
    }


def test_payload_does_not_ask_for_the_documents_back():
    """★ 不设置 return_documents。

    qwen3-rerank 不支持这个参数（只有 gte-rerank-v2 和 qwen3-vl-rerank 支持），
    而且我们要的是排名，回传一遍正文纯属浪费带宽。
    """
    payload = build_rerank_payload(
        model=FAKE_MODEL, query=QUERY, documents=["甲"], top_n=1
    )

    assert "return_documents" not in payload


def test_the_instruct_is_the_documented_english_default():
    """官方给的默认任务指令是英文的问答检索指令。"""
    assert RERANK_INSTRUCT == (
        "Given a web search query, retrieve relevant passages that answer the query."
    )


# --------------------------------------------------------------------------
# 响应解析（纯函数）
# --------------------------------------------------------------------------


def make_response(index_and_scores) -> dict:
    return {
        "object": "list",
        "results": [
            {"index": index, "relevance_score": score} for index, score in index_and_scores
        ],
        "model": FAKE_MODEL,
    }


def test_results_are_parsed_from_the_top_level():
    """★ qwen3-rerank 的 results 在**顶层**，不像 gte-rerank-v2 那样在 output 下面。"""
    items = parse_rerank_response(
        make_response([(0, 0.9), (1, 0.4)]), document_count=2, top_n=2
    )

    assert [item.index for item in items] == [0, 1]
    assert items[0].relevance_score == pytest.approx(0.9)


def test_nested_results_under_output_are_rejected():
    """把 gte-rerank-v2 的格式套上来时，必须报错而不是静默返回空。"""
    nested = {"output": {"results": [{"index": 0, "relevance_score": 0.9}]}}

    with pytest.raises(RerankerProviderError):
        parse_rerank_response(nested, document_count=1, top_n=1)


def test_provider_order_is_not_trusted():
    """★ 供应商返回的顺序不可信，按分数自己排。"""
    items = parse_rerank_response(
        make_response([(2, 0.1), (0, 0.9), (1, 0.5)]), document_count=3, top_n=3
    )

    assert [item.index for item in items] == [0, 1, 2]
    assert [item.relevance_score for item in items] == pytest.approx([0.9, 0.5, 0.1])


def test_equal_scores_fall_back_to_the_original_index_order():
    """同分时按原始下标升序——保证同样的响应永远得到同样的顺序。"""
    items = parse_rerank_response(
        make_response([(2, 0.5), (0, 0.5), (1, 0.5)]), document_count=3, top_n=3
    )

    assert [item.index for item in items] == [0, 1, 2]


def test_results_are_truncated_to_top_n():
    items = parse_rerank_response(
        make_response([(0, 0.9), (1, 0.8), (2, 0.7)]), document_count=3, top_n=2
    )

    assert len(items) == 2


@pytest.mark.parametrize(
    "payload",
    [
        {},  # 没有 results
        {"results": None},  # results 是 null
        {"results": "不是列表"},  # ★ 字符串可迭代，必须按类型拒绝
        {"results": {"index": 0}},  # 字典也不是列表
        {"results": []},  # 空结果集
        {"results": [{"index": 0}]},  # 缺 relevance_score
        {"results": [{"relevance_score": 0.9}]},  # 缺 index
        {"results": ["不是对象"]},
        {"results": [None]},
    ],
)
def test_malformed_payloads_are_rejected(payload):
    with pytest.raises(RerankerProviderError):
        parse_rerank_response(payload, document_count=2, top_n=2)


@pytest.mark.parametrize("bad_index", [-1, 2, 99])
def test_out_of_range_index_is_rejected(bad_index):
    with pytest.raises(RerankerProviderError):
        parse_rerank_response(
            make_response([(bad_index, 0.9)]), document_count=2, top_n=1
        )


def test_duplicate_index_is_rejected():
    """同一个候选被返回两次，会让「按 index 映射回候选」出现重复。"""
    with pytest.raises(RerankerProviderError):
        parse_rerank_response(
            make_response([(0, 0.9), (0, 0.5)]), document_count=2, top_n=2
        )


@pytest.mark.parametrize("bad_index", [True, False, 1.0, "0", None])
def test_non_integer_index_is_rejected(bad_index):
    """bool 是 int 的子类，True 会被当成 1 混过去，必须先排掉。"""
    with pytest.raises(RerankerProviderError):
        parse_rerank_response(
            make_response([(bad_index, 0.9)]), document_count=2, top_n=1
        )


@pytest.mark.parametrize("bad_score", ["0.9", None, [0.9], {"v": 1}, True])
def test_non_numeric_score_is_rejected(bad_score):
    with pytest.raises(RerankerProviderError):
        parse_rerank_response(
            make_response([(0, bad_score)]), document_count=1, top_n=1
        )


@pytest.mark.parametrize("bad_score", [float("nan"), float("inf"), float("-inf")])
def test_non_finite_score_is_rejected(bad_score):
    """★ NaN / Infinity 必须先拦掉。

    python 的 json 解析默认接受 NaN 和 Infinity 字面量，
    于是这些值能一路活到这里；一旦参与排序，整个顺序就不可预测了。
    """
    with pytest.raises(RerankerProviderError):
        parse_rerank_response(
            make_response([(0, bad_score)]), document_count=1, top_n=1
        )


@pytest.mark.parametrize("bad_score", [-0.1, 1.1, 100])
def test_out_of_range_score_is_rejected(bad_score):
    """官方说 relevance_score 是 0.0~1.0 的 double。"""
    with pytest.raises(RerankerProviderError):
        parse_rerank_response(
            make_response([(0, bad_score)]), document_count=1, top_n=1
        )


@pytest.mark.parametrize("boundary", [0.0, 1.0])
def test_boundary_scores_are_accepted(boundary):
    items = parse_rerank_response(
        make_response([(0, boundary)]), document_count=1, top_n=1
    )

    assert items[0].relevance_score == pytest.approx(boundary)


def test_an_integer_score_is_accepted():
    items = parse_rerank_response(make_response([(0, 1)]), document_count=1, top_n=1)

    assert items[0].relevance_score == pytest.approx(1.0)


# --------------------------------------------------------------------------
# Provider 适配器：请求形状
# --------------------------------------------------------------------------


def test_the_request_is_a_post_to_the_rerank_endpoint():
    transport = FakeTransport(json_body=make_response([(0, 0.9)]))

    asyncio.run(run_provider(transport))

    assert transport.request.method == "POST"
    assert str(transport.request.url) == FAKE_BASE_URL + RERANK_PATH


def test_the_request_carries_a_bearer_token():
    transport = FakeTransport(json_body=make_response([(0, 0.9)]))

    asyncio.run(run_provider(transport))

    # 断言结果存成布尔再断言：失败信息里不会带出 Header 内容
    authorization_is_correct = (
        transport.request.headers.get("Authorization") == f"Bearer {FAKE_KEY}"
    )
    assert authorization_is_correct, "Authorization 头不正确（内容不打印）"


def test_the_request_declares_json():
    transport = FakeTransport(json_body=make_response([(0, 0.9)]))

    asyncio.run(run_provider(transport))

    assert transport.request.headers["Content-Type"].startswith("application/json")


def test_the_request_body_matches_the_documented_shape():
    transport = FakeTransport(json_body=make_response([(0, 0.9)]))

    asyncio.run(run_provider(transport, documents=["甲", "乙"], top_n=1))

    body = transport.sent_body()
    assert body["model"] == FAKE_MODEL
    assert body["query"] == QUERY
    assert body["documents"] == ["甲", "乙"]
    assert body["top_n"] == 1
    assert body["instruct"] == RERANK_INSTRUCT
    assert "return_documents" not in body


def test_the_timeout_comes_from_the_settings():
    """超时是真的配置进 httpx 的，不是写在文档里的承诺。"""
    transport = FakeTransport(json_body=make_response([(0, 0.9)]))
    provider = DashScopeReranker(
        make_rerank_settings(rerank_timeout_seconds=3.5), transport=transport.transport()
    )

    asyncio.run(provider.rerank(QUERY, ["甲"], top_n=1))

    # httpx 把 timeout 存在 extensions 里，MockTransport 也会带上
    timeout = transport.request.extensions.get("timeout")
    assert timeout is not None
    assert float(timeout["read"]) == pytest.approx(3.5)


def test_documents_are_sent_in_order():
    transport = FakeTransport(json_body=make_response([(0, 0.9)]))

    asyncio.run(run_provider(transport, documents=["第一段", "第二段", "第三段"], top_n=1))

    assert transport.sent_body()["documents"] == ["第一段", "第二段", "第三段"]


# --------------------------------------------------------------------------
# Provider 适配器：失败转换
# --------------------------------------------------------------------------


@pytest.mark.parametrize("status_code", [401, 403, 429, 500, 502, 503])
def test_error_status_codes_become_provider_errors(status_code):
    transport = FakeTransport(json_body={"error": "boom"}, status_code=status_code)

    with pytest.raises(RerankerProviderError) as error:
        asyncio.run(run_provider(transport))

    assert str(status_code) in str(error.value)


@pytest.mark.parametrize(
    "error",
    [
        httpx.ReadTimeout("超时"),
        httpx.ConnectTimeout("连接超时"),
        httpx.ConnectError("连不上"),
        httpx.ReadError("读失败"),
    ],
)
def test_transport_errors_become_provider_errors(error):
    transport = FakeTransport(error=error)

    with pytest.raises(RerankerProviderError) as caught:
        asyncio.run(run_provider(transport))

    assert type(error).__name__ in str(caught.value)


def test_a_non_json_response_becomes_a_provider_error():
    transport = FakeTransport(text="<html>这不是 JSON</html>")

    with pytest.raises(RerankerProviderError):
        asyncio.run(run_provider(transport))


def test_a_malformed_body_becomes_a_provider_error():
    transport = FakeTransport(json_body={"results": [{"index": 5, "relevance_score": 0.9}]})

    with pytest.raises(RerankerProviderError):
        asyncio.run(run_provider(transport, documents=["甲"], top_n=1))


def test_provider_errors_never_leak_the_key_the_query_or_the_body():
    """★ 错误信息里只能有错误类别和状态码。

    异常正文、Key、用户问题、候选正文、完整 URL 一个都不能进——
    它们会顺着日志和接口响应一路扩散出去。
    """
    transport = FakeTransport(
        json_body={"error": f"invalid api_key={FAKE_KEY}"}, status_code=401
    )

    with pytest.raises(RerankerProviderError) as error:
        asyncio.run(run_provider(transport, documents=[DOCUMENT_TEXT], top_n=1))

    message = str(error.value)
    assert FAKE_KEY not in message
    assert "sk-" not in message
    assert QUERY not in message
    assert DOCUMENT_TEXT not in message
    assert FAKE_BASE_URL not in message
    assert "fake-workspace-id" not in message
    assert "invalid api_key" not in message


def test_provider_errors_are_app_errors():
    """受控异常要能被上层的 AppError 兜住，而不是变成裸的第三方异常。"""
    from app.core.exceptions import AppError

    assert issubclass(RerankerProviderError, AppError)
    assert issubclass(RerankerError, AppError)
    assert issubclass(RerankerProviderError, RerankerError)


def test_a_successful_response_is_parsed_into_items():
    transport = FakeTransport(json_body=make_response([(1, 0.8), (0, 0.9)]))

    items = asyncio.run(run_provider(transport, documents=["甲", "乙"], top_n=2))

    assert [item.index for item in items] == [0, 1]
    assert all(isinstance(item, RerankItem) for item in items)


# --------------------------------------------------------------------------
# 编排：输入校验与短路
# --------------------------------------------------------------------------


def test_empty_candidates_return_empty_without_reading_config_or_building_a_client(
    monkeypatch,
):
    """★ 没有候选就没有可精排的东西。

    这一步必须在读配置之前：既不该因为「没配 Key」而报错，
    也不该为了一个空列表去建 HTTP 客户端。
    """

    def explode():
        raise AssertionError("没有候选时不该读配置")

    monkeypatch.setattr(reranker, "get_settings", explode)
    monkeypatch.setattr(reranker, "DashScopeReranker", explode)

    assert asyncio.run(rerank_candidates(QUERY, [])) == []


@pytest.mark.parametrize("blank", ["", "   ", "\n\t "])
def test_blank_query_is_rejected(blank):
    with pytest.raises(RerankerError) as error:
        asyncio.run(rerank_candidates(blank, make_candidates(2)))

    assert "sk-" not in str(error.value)


def test_none_query_is_rejected():
    with pytest.raises(RerankerError):
        asyncio.run(rerank_candidates(None, make_candidates(2)))


def test_the_query_is_stripped_before_being_sent(monkeypatch):
    patch_settings(monkeypatch)
    reranker_ = FakeReranker([RerankItem(0, 0.9)])

    asyncio.run(rerank_candidates("  原问题  ", make_candidates(1), reranker=reranker_))

    assert reranker_.calls[0][0] == "原问题"


def test_a_blank_query_is_rejected_before_the_empty_candidate_shortcut():
    """参数错误要被看见，不能因为「反正没有候选」就悄悄放过。"""
    with pytest.raises(RerankerError):
        asyncio.run(rerank_candidates("   ", []))


@pytest.mark.parametrize("bad_top_n", [0, -1, 1.5, "5", True])
def test_invalid_top_n_is_rejected(monkeypatch, bad_top_n):
    patch_settings(monkeypatch)

    with pytest.raises(RerankerError):
        asyncio.run(
            rerank_candidates(
                QUERY, make_candidates(2), top_n=bad_top_n, reranker=FakeReranker()
            )
        )


def test_omitting_top_n_uses_the_configured_default(monkeypatch):
    """省略 top_n（或显式传 None）表示「用配置里的值」，不是参数错误。"""
    patch_settings(monkeypatch, rag_final_top_k=3)

    result = asyncio.run(
        rerank_candidates(
            QUERY, make_candidates(5), top_n=None, reranker=FakeReranker([RerankItem(0, 0.9)])
        )
    )

    assert len(result) == 3


# --------------------------------------------------------------------------
# 编排：禁用与成功路径
# --------------------------------------------------------------------------


def test_disabled_rerank_returns_the_rrf_order(monkeypatch):
    """★ 关掉精排时，返回的就是 RRF 顺序的前 N 条，一次网络都不发。"""
    patch_settings(monkeypatch, rag_rerank_enabled=False, rag_final_top_k=3)
    candidates = make_candidates(5)
    reranker_ = FakeReranker()  # 一个也不会被调用

    result = asyncio.run(rerank_candidates(QUERY, candidates, reranker=reranker_))

    assert [c.chunk.chunk_id for c in result] == [1, 2, 3]
    assert reranker_.calls == []


def test_disabled_rerank_does_not_create_a_production_client(monkeypatch):
    patch_settings(monkeypatch, rag_rerank_enabled=False)

    def explode(*args, **kwargs):
        raise AssertionError("关掉精排时不该建生产客户端")

    monkeypatch.setattr(reranker, "DashScopeReranker", explode)

    asyncio.run(rerank_candidates(QUERY, make_candidates(3)))


def test_disabled_rerank_still_validates_top_n(monkeypatch):
    """参数错误和功能开关是两件事：关着也要拦住写错的参数。"""
    patch_settings(monkeypatch, rag_rerank_enabled=False)

    with pytest.raises(RerankerError):
        asyncio.run(rerank_candidates(QUERY, make_candidates(3), top_n=0))


def test_successful_rerank_follows_the_provider_order(monkeypatch):
    patch_settings(monkeypatch)
    candidates = make_candidates(5)
    reranker_ = FakeReranker([RerankItem(4, 0.95), RerankItem(1, 0.7)])

    result = asyncio.run(rerank_candidates(QUERY, candidates, top_n=2, reranker=reranker_))

    assert [c.chunk.chunk_id for c in result] == [5, 2]
    assert reranker_.calls[0][2] == 2


def test_rerank_score_is_written_onto_the_candidates(monkeypatch):
    patch_settings(monkeypatch)
    candidates = make_candidates(3)
    reranker_ = FakeReranker([RerankItem(2, 0.95), RerankItem(0, 0.4)])

    result = asyncio.run(rerank_candidates(QUERY, candidates, top_n=2, reranker=reranker_))

    assert result[0].rerank_score == pytest.approx(0.95)
    assert result[0].chunk.chunk_id == 3
    assert result[1].rerank_score == pytest.approx(0.4)


def test_reranking_does_not_mutate_the_input_candidates(monkeypatch):
    """★ 原候选对象不能被改。

    它是 RRF 的产物，别处（日志、调试、后续阶段）可能还拿着它；
    就地改字段会让「这份候选到底排过序没有」变成一个说不清的问题。
    """
    patch_settings(monkeypatch)
    candidates = make_candidates(3)
    reranker_ = FakeReranker([RerankItem(0, 0.95)])

    asyncio.run(rerank_candidates(QUERY, candidates, top_n=2, reranker=reranker_))

    assert all(candidate.rerank_score is None for candidate in candidates)
    assert [candidate.chunk.chunk_id for candidate in candidates] == [1, 2, 3]


def test_the_other_candidate_fields_are_preserved(monkeypatch):
    """只换 rerank_score，RRF 阶段留下的排名与分数都要带着走。"""
    patch_settings(monkeypatch)
    candidate = make_candidate(1, vector_rank=3, keyword_rank=2, rrf_score=0.05)

    result = asyncio.run(
        rerank_candidates(QUERY, [candidate], top_n=1, reranker=FakeReranker([RerankItem(0, 0.9)]))
    )

    assert result[0].vector_rank == 3
    assert result[0].keyword_rank == 2
    assert result[0].rrf_score == pytest.approx(0.05)
    assert result[0].distance == pytest.approx(0.2)
    assert result[0].matched_queries == ("原问题",)


def test_the_documents_sent_to_the_reranker_are_the_built_texts(monkeypatch):
    patch_settings(monkeypatch)
    candidates = make_candidates(2)
    reranker_ = FakeReranker([RerankItem(0, 0.9)])

    asyncio.run(rerank_candidates(QUERY, candidates, top_n=1, reranker=reranker_))

    assert reranker_.documents == [build_rerank_document(c) for c in candidates]


# --------------------------------------------------------------------------
# 编排：补足与边界
# --------------------------------------------------------------------------


def test_missing_tail_is_filled_from_the_original_order(monkeypatch):
    """★ 供应商只返回了一部分时，剩下按**原 RRF 顺序**补足。

    补足的那些**没有** rerank_score——它们确实没被精排过，
    编一个分数出来就是在撒谎。
    """
    patch_settings(monkeypatch)
    candidates = make_candidates(5)
    reranker_ = FakeReranker([RerankItem(3, 0.95)])

    result = asyncio.run(rerank_candidates(QUERY, candidates, top_n=3, reranker=reranker_))

    assert [c.chunk.chunk_id for c in result] == [4, 1, 2]
    assert result[0].rerank_score == pytest.approx(0.95)
    assert result[1].rerank_score is None
    assert result[2].rerank_score is None


def test_the_filled_tail_never_repeats_the_reranked_ones(monkeypatch):
    patch_settings(monkeypatch)
    candidates = make_candidates(4)
    reranker_ = FakeReranker([RerankItem(1, 0.95), RerankItem(0, 0.9)])

    result = asyncio.run(rerank_candidates(QUERY, candidates, top_n=4, reranker=reranker_))

    ids = [c.chunk.chunk_id for c in result]
    assert ids == [2, 1, 3, 4]
    assert len(ids) == len(set(ids))


def test_top_n_larger_than_the_candidate_count_uses_all_of_them(monkeypatch):
    patch_settings(monkeypatch)
    candidates = make_candidates(2)
    reranker_ = FakeReranker([RerankItem(1, 0.9)])

    result = asyncio.run(rerank_candidates(QUERY, candidates, top_n=10, reranker=reranker_))

    assert len(result) == 2
    assert reranker_.calls[0][2] == 10


def test_the_configured_final_top_k_is_the_default(monkeypatch):
    patch_settings(monkeypatch, rag_final_top_k=2)
    candidates = make_candidates(6)
    reranker_ = FakeReranker([RerankItem(0, 0.9)])

    result = asyncio.run(rerank_candidates(QUERY, candidates, reranker=reranker_))

    assert len(result) == 2
    assert reranker_.calls[0][2] == 2


def test_an_empty_provider_result_falls_back_to_the_rrf_order(monkeypatch):
    """供应商一条都没返回——按原顺序给前 N 条，而不是返回空。"""
    patch_settings(monkeypatch)
    candidates = make_candidates(4)
    reranker_ = FakeReranker([])

    result = asyncio.run(rerank_candidates(QUERY, candidates, top_n=2, reranker=reranker_))

    assert [c.chunk.chunk_id for c in result] == [1, 2]
    assert all(c.rerank_score is None for c in result)


# --------------------------------------------------------------------------
# 编排：失败降级
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "error",
    [
        RerankerProviderError("精排服务返回 401。"),
        RerankerProviderError("精排服务返回 429。"),
        RerankerProviderError("精排服务返回 500。"),
        RerankerProviderError("精排请求超时。"),
        RerankerProviderError("精排响应无法解析。"),
    ],
)
def test_provider_failures_fall_back_to_the_rrf_order(monkeypatch, error):
    patch_settings(monkeypatch)
    candidates = make_candidates(5)

    result = asyncio.run(
        rerank_candidates(QUERY, candidates, top_n=3, reranker=FakeReranker(error=error))
    )

    assert [c.chunk.chunk_id for c in result] == [1, 2, 3]


def test_a_fallback_never_fakes_a_rerank_score(monkeypatch):
    """★ 退回 RRF 时，rerank_score 保持 None。

    填 0 或 1 都会让下游以为「这条被精排过，而且分数很低」，
    而真相是「这条根本没送去精排」。
    """
    patch_settings(monkeypatch)
    candidates = make_candidates(3)

    result = asyncio.run(
        rerank_candidates(
            QUERY, candidates, top_n=3, reranker=FakeReranker(error=RerankerProviderError("挂了"))
        )
    )

    assert all(candidate.rerank_score is None for candidate in result)


def test_programming_errors_are_not_swallowed(monkeypatch):
    """★ 只捕获 RerankerProviderError。

    TypeError / AssertionError 这类是程序 Bug，吞掉它们等于把 Bug 藏起来——
    而隐藏 Bug 比一次失败更糟。
    """
    patch_settings(monkeypatch)

    with pytest.raises(TypeError):
        asyncio.run(
            rerank_candidates(QUERY, make_candidates(2), reranker=FakeReranker(error=TypeError("bug")))
        )

    with pytest.raises(AssertionError):
        asyncio.run(
            rerank_candidates(
                QUERY, make_candidates(2), reranker=FakeReranker(error=AssertionError("bug"))
            )
        )


def test_configuration_errors_are_not_swallowed(monkeypatch):
    """★ 配置错误是部署问题，必须当场暴露，不能降级成「悄悄不用精排」。"""
    monkeypatch.setattr(
        reranker,
        "get_settings",
        lambda: Settings(_env_file=None, **make_env_values(rerank_api_key="")),
    )

    with pytest.raises(ConfigurationError):
        asyncio.run(rerank_candidates(QUERY, make_candidates(3)))


def test_failure_logging_records_only_the_exception_class(monkeypatch, caplog):
    import logging

    patch_settings(monkeypatch)
    marker = "zz-question-marker-zz"
    secret = "sk-canary-rerank-leak-0123456789abcdef"

    with caplog.at_level(logging.WARNING):
        asyncio.run(
            rerank_candidates(
                f"关于 {marker} 的问题",
                make_candidates(2),
                top_n=1,
                reranker=FakeReranker(error=RerankerProviderError(f"401 api_key={secret}")),
            )
        )

    assert "RerankerProviderError" in caplog.text
    assert marker not in caplog.text
    assert secret not in caplog.text
    assert "sk-" not in caplog.text
    assert "正文内容" not in caplog.text


# --------------------------------------------------------------------------
# 编排：客户端创建
# --------------------------------------------------------------------------


def test_an_injected_reranker_means_no_production_client(monkeypatch):
    patch_settings(monkeypatch)

    def explode(*args, **kwargs):
        raise AssertionError("注入了 reranker 之后不该再建生产客户端")

    monkeypatch.setattr(reranker, "DashScopeReranker", explode)

    result = asyncio.run(
        rerank_candidates(
            QUERY, make_candidates(2), top_n=1, reranker=FakeReranker([RerankItem(0, 0.9)])
        )
    )

    assert len(result) == 1


def test_the_production_client_is_created_lazily_from_the_settings(monkeypatch):
    """没注入时才建，而且用的是配置层校验过的值。"""
    patch_settings(monkeypatch)
    captured: dict = {}

    class RecordingProvider:
        def __init__(self, settings):
            captured["settings"] = settings

        async def rerank(self, query, documents, *, top_n):
            return [RerankItem(0, 0.5)]

    monkeypatch.setattr(reranker, "DashScopeReranker", RecordingProvider)

    asyncio.run(rerank_candidates(QUERY, make_candidates(2), top_n=1))

    assert captured["settings"].model == FAKE_MODEL
    assert captured["settings"].base_url == FAKE_BASE_URL


def test_no_network_client_is_created_when_the_provider_fails_late(monkeypatch):
    """Provider 报 `RerankerProviderError` 时，编排层只降级、不再建第二个客户端。"""
    patch_settings(monkeypatch)
    built: list[int] = []

    class FailingProvider:
        def __init__(self, settings):
            built.append(1)

        async def rerank(self, query, documents, *, top_n):
            raise RerankerProviderError("精排服务返回 503。")

    monkeypatch.setattr(reranker, "DashScopeReranker", FailingProvider)

    result = asyncio.run(rerank_candidates(QUERY, make_candidates(2), top_n=1))

    assert built == [1]
    assert [c.chunk.chunk_id for c in result] == [1]


# --------------------------------------------------------------------------
# 模块卫生与通用性
# --------------------------------------------------------------------------


def test_the_module_does_not_import_models_or_embedding():
    """精排只跟 rerank 服务打交道，不该够得着 LLM 与 embedding。"""
    import ast

    tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)

    forbidden = ("app.core.llm", "app.services.embedding", "langchain", "openai")
    assert not [module for module in modules if module.startswith(forbidden)]


def test_the_module_does_not_import_the_database_layer():
    """精排是纯网络调用，不该连数据库。"""
    source = MODULE_PATH.read_text(encoding="utf-8")

    assert "repositories.database" not in source
    assert "sqlalchemy" not in source


@pytest.mark.parametrize(
    "term",
    ["客单价", "销售额", "会员", "复购率", "华东", "黑金会员", "年底旺季"],
)
def test_the_module_has_no_hardcoded_domain_vocabulary(term):
    assert term not in MODULE_PATH.read_text(encoding="utf-8")


def test_the_module_never_reads_the_environment_directly():
    """配置只从 core.config 来，不自己 os.environ.get，否则会绕过校验。"""
    source = MODULE_PATH.read_text(encoding="utf-8")

    assert "os.environ" not in source
    assert "getenv" not in source


# --------------------------------------------------------------------------
# 回归：RAG-13.4 的候选类型没被这一阶段改坏
# --------------------------------------------------------------------------


def test_retrieval_candidate_defaults_are_unchanged():
    candidate = make_candidate(1)

    assert candidate.rerank_score is None
    assert candidate.keyword_score is None
    assert candidate.matched_terms == ()
    assert candidate.vector_rank == 1
    assert candidate.keyword_rank is None


def test_retrieval_candidate_can_be_replaced_with_a_rerank_score():
    """写 rerank_score 走的是 dataclasses.replace，而不是就地改。"""
    candidate = make_candidate(1)

    updated = dataclasses.replace(candidate, rerank_score=0.75)

    assert updated.rerank_score == pytest.approx(0.75)
    assert candidate.rerank_score is None
    assert updated.chunk is candidate.chunk


def test_rerank_does_not_import_from_fusion_at_module_import_time_only():
    """融合模块与本模块的依赖方向必须是单向的：融合不知道精排的存在。"""
    import app.services.retrieval_fusion as fusion

    assert "reranker" not in pathlib.Path(fusion.__file__).read_text(encoding="utf-8")


def test_knowledge_search_error_is_still_the_retrieval_parameter_error():
    """召回链路的参数错误仍然用 KnowledgeSearchError，本阶段没有换掉它。"""
    assert issubclass(KnowledgeSearchError, Exception)
