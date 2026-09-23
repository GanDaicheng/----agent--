"""知识文档上传 / 列表接口（/api/v1/rag/documents）的 HTTP 层测试。

**不连数据库、不调 embedding、不调模型。** 两个服务函数都由 monkeypatch 换成替身：
- `routes.ingest_knowledge_document_from_content` —— 入库
- `routes.list_documents` —— 列表

**但 `extract_document_text` 是真跑的**，不替换：docx / pdf 的输入由
tests/document_fixtures.py 现场生成真实文件字节。这样测的是「路由 + 文件处理器」
这一整段真实链路，只有「切片之后」被截掉。替代它反而会掩盖处理器与路由接线处的错误。

真实的「上传 → 向量 → 入库 → 能检索到」由端到端手工验收覆盖，
不适合放进每次都要跑的套件。

这个接口有一类别的接口没有的风险：**它收的是文件**。所以除了状态码，
还专门盯住两件事——超大文件不能读进内存、错误响应不能把文件正文带出去。
"""

import asyncio
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

from app.api import routes
from app.core.exceptions import ConfigurationError
from app.main import app
from app.services.document_normalization import (
    EmptyDocumentError,
    UndecodableDocumentError,
)
from app.services.document_processors import (
    SUPPORTED_UPLOAD_TYPES,
    DocumentParseError,
    UnsupportedUploadTypeError,
)
from app.services.knowledge_catalog import KnowledgeDocumentSummary
from app.services.knowledge_ingestion import KnowledgeIngestionResult

from .document_fixtures import BODY, HEADING1, TITLE, build_docx, build_pdf

ENDPOINT = "/api/v1/rag/documents"

MOMENT = datetime(2026, 9, 23, 12, 0, tzinfo=timezone.utc)

# 留在正文里的标记：确认它不会顺着任何响应漏出去
CONTENT_MARKER = "zz-secret-body-marker-zz"


# --------------------------------------------------------------------------
# 替身
# --------------------------------------------------------------------------


def make_ingestion_result(
    *,
    source_file: str = "orders.md",
    action: str = "insert",
    document_id: int | None = 1,
    chunk_count: int = 3,
    embedded_chunks: int = 3,
) -> KnowledgeIngestionResult:
    return KnowledgeIngestionResult(
        source_file=source_file,
        action=action,  # type: ignore[arg-type]
        document_id=document_id,
        content_hash="0" * 64,
        chunk_count=chunk_count,
        embedded_chunks=embedded_chunks,
        dry_run=False,
    )


def make_summary(
    *,
    source_file: str = "orders.md",
    document_title: str = "订单口径",
    chunk_count: int = 3,
    updated_at: datetime | None = None,
) -> KnowledgeDocumentSummary:
    return KnowledgeDocumentSummary(
        source_file=source_file,
        document_title=document_title,
        chunk_count=chunk_count,
        created_at=MOMENT,
        updated_at=updated_at or MOMENT,
    )


def patch_ingest(monkeypatch, *, result=None, error=None):
    """把路由引用到的入库函数换成替身，返回记录调用参数的列表。"""
    calls: list[dict] = []

    async def fake_ingest(**kwargs):
        calls.append(kwargs)
        if error is not None:
            raise error
        return result if result is not None else make_ingestion_result()

    monkeypatch.setattr(routes, "ingest_knowledge_document_from_content", fake_ingest)
    return calls


def patch_list(monkeypatch, *, documents=None, error=None):
    calls: list[None] = []

    async def fake_list(*, connection=None):
        calls.append(None)
        if error is not None:
            raise error
        return list(documents or [])

    monkeypatch.setattr(routes, "list_documents", fake_list)
    return calls


def upload(
    *,
    filename: str | None = "orders.md",
    content: bytes = b"# \xe8\xae\xa2\xe5\x8d\x95\xe5\x8f\xa3\xe5\xbe\x84",
    title: str | None = None,
):
    """构造一次 multipart 上传请求。

    filename 传 None 时不带 filename 字段——真实客户端可能这么干。
    """
    files = (
        {"file": (filename, content, "text/markdown")} if filename is not None else {}
    )
    data = {} if title is None else {"title": title}
    with TestClient(app) as client:
        return client.post(ENDPOINT, files=files, data=data)


# --------------------------------------------------------------------------
# 上传：成功路径
# --------------------------------------------------------------------------


def test_successful_upload_returns_the_ingestion_result(monkeypatch):
    patch_ingest(
        monkeypatch,
        result=make_ingestion_result(chunk_count=5, embedded_chunks=5),
    )

    response = upload()

    assert response.status_code == 200
    body = response.json()
    assert body["source_file"] == "orders.md"
    assert body["action"] == "insert"
    assert body["chunk_count"] == 5
    assert body["embedded_chunks"] == 5


def test_upload_forwards_the_stripped_file_name(monkeypatch):
    """客户端可能把路径塞进 filename；source_file 是业务主键，只留最后一段。"""
    calls = patch_ingest(monkeypatch)

    upload(filename="docs/retail/orders.md")

    assert calls[0]["source_file"] == "orders.md"


def test_upload_forwards_the_decoded_content(monkeypatch):
    calls = patch_ingest(monkeypatch)

    upload(content="# 订单口径\r\n\r\n正文。".encode())

    # 解码那一步只做「字节 → 文本」，换行统一是归一化的事，发生在服务内部
    assert calls[0]["content"] == "# 订单口径\r\n\r\n正文。"


def test_upload_forwards_the_file_type_from_the_suffix(monkeypatch):
    calls = patch_ingest(monkeypatch)

    upload(filename="notes.txt", content="正文。".encode())

    assert calls[0]["file_type"] == "txt"


def test_upload_passes_an_absent_title_as_none(monkeypatch):
    """没填标题时要传 None，而不是空串。

    空串会覆盖掉下游「按文档一级标题兜底」的分支，让标题变成一片空白。
    """
    calls = patch_ingest(monkeypatch)

    upload()

    assert calls[0]["title"] is None


def test_upload_strips_and_forwards_the_title(monkeypatch):
    calls = patch_ingest(monkeypatch)

    upload(title="  零售指标口径  ")

    assert calls[0]["title"] == "零售指标口径"


def test_blank_title_is_treated_as_absent(monkeypatch):
    calls = patch_ingest(monkeypatch)

    upload(title="   ")

    assert calls[0]["title"] is None


@pytest.mark.parametrize("action", ["insert", "update", "skip"])
def test_every_action_is_reported_as_200(action, monkeypatch):
    """skip 也是成功——内容没变、什么都没写，那是幂等生效，不是失败。"""
    patch_ingest(
        monkeypatch,
        result=make_ingestion_result(action=action, embedded_chunks=0),
    )

    response = upload()

    assert response.status_code == 200
    assert response.json()["action"] == action
    assert response.json()["embedded_chunks"] == 0


def test_response_does_not_expose_internal_ingestion_fields(monkeypatch):
    """content_hash 是查重用的内部指纹，document_id 是数据库主键，都不外发。"""
    patch_ingest(monkeypatch)

    body = upload().json()

    assert set(body) == {"source_file", "action", "chunk_count", "embedded_chunks"}


# --------------------------------------------------------------------------
# 上传：用户给的文件有问题，一律 422
# --------------------------------------------------------------------------


@pytest.mark.parametrize("filename", ["a.csv", "a.xlsx", "a.pptx", "a.doc", "a"])
def test_unsupported_extension_returns_422(filename, monkeypatch):
    """csv / xlsx 是**数据文件**，走的是「导入成数仓表」那条链路，不是这里。

    它们不该被当成知识文档——表格数据切片后会变成一堆碎表格行，既检索不准，
    又和智能问数那条链路职责重叠。所以这里明确拒绝。
    """
    calls = patch_ingest(monkeypatch)

    response = upload(filename=filename)

    assert response.status_code == 422
    # 文案要说清支持什么，用户才知道该换什么格式
    for supported in SUPPORTED_UPLOAD_TYPES:
        assert supported in response.json()["detail"]
    # 类型都不支持，不该走到入库那一步
    assert calls == []


def test_missing_filename_returns_422(monkeypatch):
    calls = patch_ingest(monkeypatch)

    response = upload(filename=None)

    assert response.status_code == 422
    assert calls == []


def test_non_utf8_content_returns_422(monkeypatch):
    """GBK 编码的中文是最常见的「打开正常、传上来乱码」，要当场挡住。"""
    calls = patch_ingest(monkeypatch)

    response = upload(content="订单口径".encode("gbk"))

    assert response.status_code == 422
    assert "UTF-8" in response.json()["detail"]
    assert calls == []


def test_empty_content_is_reported_by_the_service_as_422(monkeypatch):
    """「内容切完是空的」由入库服务判定，路由只把异常翻译成 422。"""
    patch_ingest(monkeypatch, error=EmptyDocumentError("orders.md 空空如也"))

    response = upload(content=b"   \n\n  ")

    assert response.status_code == 422
    assert response.json()["detail"] == routes.RAG_UPLOAD_EMPTY_DETAIL


def test_empty_bytes_are_reported_by_the_service_not_by_decoding(monkeypatch):
    """空文件有时是合法上传（用户传错了），交给服务层判定为空。"""
    patch_ingest(monkeypatch, error=EmptyDocumentError("空"))

    response = upload(content=b"")

    assert response.status_code == 422


def test_unsupported_type_error_from_the_service_is_also_422(monkeypatch):
    """类型不支持的判定有两处（路由按后缀挑处理器、处理器注册表再兜一层），
    两处都要翻译成同一条 422 文案。"""
    patch_ingest(monkeypatch, error=UnsupportedUploadTypeError("不支持"))

    response = upload()

    assert response.status_code == 422
    assert response.json()["detail"] == routes.RAG_UPLOAD_UNSUPPORTED_TYPE_DETAIL


def test_document_parse_error_returns_422(monkeypatch):
    """解析失败是「用户给的文件有问题」，属于 422，不是服务故障。

    这一条尤其重要：损坏的 docx / 加密的 pdf 会走到这里，
    如果映射成 500，用户会以为后端挂了，而真正该做的是换一份文件。
    """
    patch_ingest(monkeypatch, error=DocumentParseError("坏了"))

    response = upload()

    assert response.status_code == 422
    assert response.json()["detail"] == routes.RAG_UPLOAD_PARSE_FAILED_DETAIL


def test_undecodable_error_from_the_service_is_also_422(monkeypatch):
    patch_ingest(monkeypatch, error=UndecodableDocumentError("解不开"))

    response = upload()

    assert response.status_code == 422
    assert response.json()["detail"] == routes.RAG_UPLOAD_UNDECODABLE_DETAIL


def test_over_long_file_name_returns_422(monkeypatch):
    """超长文件名必须在路由拦住。

    否则它会一路走到 INSERT 才失败，还以「知识库暂时不可用」的面目出现——
    那是把「你的文件名太长」错报成「后端挂了」。
    """
    calls = patch_ingest(monkeypatch)

    response = upload(filename="a" * 300 + ".md")

    assert response.status_code == 422
    assert calls == []


def test_over_long_title_returns_422(monkeypatch):
    calls = patch_ingest(monkeypatch)

    response = upload(title="标" * 300)

    assert response.status_code == 422
    assert calls == []


# --------------------------------------------------------------------------
# 上传：docx / pdf（文件处理器）
#
# 这一组**不替换文件处理器**，上传的是现场生成的真实 docx / pdf 字节，
# 所以测的是「路由 → 处理器 → 交给入库服务」这一整段接线。
# --------------------------------------------------------------------------


def docx_upload(monkeypatch):
    """上传一份真实 docx，返回 (响应, 入库服务收到的参数)。"""
    calls = patch_ingest(monkeypatch)
    raw = build_docx(
        [
            (TITLE, "零售指标口径说明"),
            (BODY, "本文档定义核心指标口径。"),
            (HEADING1, "销售额"),
            (BODY, "销售额 = SUM(orders.net_amount)"),
        ]
    )

    response = upload(filename="spec.docx", content=raw)
    return response, calls


def test_docx_upload_succeeds(monkeypatch):
    response, calls = docx_upload(monkeypatch)

    assert response.status_code == 200
    # 响应里的 source_file 来自入库服务，请求里的文件名由路由转交给它
    assert calls[0]["source_file"] == "spec.docx"


def test_docx_is_handed_to_the_ingestion_service_as_markdown(monkeypatch):
    """**这是本次扩展的核心约定**：docx 被还原成 Markdown 之后才交给入库服务。

    file_type 必须是 "md"（切片类型），不是 "docx"（上传类型）——
    入库服务因此完全不需要知道 docx 的存在，切片与入库逻辑一行都不用改。
    """
    _, calls = docx_upload(monkeypatch)

    assert calls[0]["file_type"] == "md"
    assert calls[0]["content"].startswith("# 零售指标口径说明")
    assert "## 销售额" in calls[0]["content"]


def test_pdf_upload_is_handed_to_the_ingestion_service_as_markdown(monkeypatch):
    calls = patch_ingest(monkeypatch)
    raw = build_pdf(
        [
            (22.0, 40.0, "Retail Metrics Specification"),
            (11.0, 14.0, "First body line of the paragraph."),
            (11.0, 30.0, "Second body line of the paragraph."),
        ]
    )

    response = upload(filename="spec.pdf", content=raw)

    assert response.status_code == 200
    assert calls[0]["file_type"] == "md"
    assert calls[0]["content"].startswith("# Retail Metrics Specification")


def test_docx_title_field_overrides_the_extracted_title(monkeypatch):
    """表单里填了标题就以它为准——处理器只负责提取，不负责决定这份文档叫什么。"""
    calls = patch_ingest(monkeypatch)
    raw = build_docx([(TITLE, "文档里写的标题"), (BODY, "正文。")])

    upload(filename="spec.docx", content=raw, title="我在表单里填的标题")

    assert calls[0]["title"] == "我在表单里填的标题"


def test_corrupt_docx_returns_422(monkeypatch):
    """损坏的 docx：真实走一遍处理器，确认它把底层异常收成 422。"""
    calls = patch_ingest(monkeypatch)

    response = upload(filename="broken.docx", content=b"not a zip at all")

    assert response.status_code == 422
    assert response.json()["detail"] == routes.RAG_UPLOAD_PARSE_FAILED_DETAIL
    # 解析都没过，不该走到入库
    assert calls == []


def test_corrupt_pdf_returns_422(monkeypatch):
    calls = patch_ingest(monkeypatch)

    response = upload(filename="broken.pdf", content=b"%PDF-1.4\ngarbage")

    assert response.status_code == 422
    assert response.json()["detail"] == routes.RAG_UPLOAD_PARSE_FAILED_DETAIL
    assert calls == []


def test_scanned_pdf_returns_422_with_the_no_text_layer_message(monkeypatch):
    """没有文字层的 PDF（扫描件）→ 422，且文案要指出这是扫描件。

    不能用通用的「内容为空」：拿着扫描件的用户会以为文件没写完，
    反复重试同一份文件。必须告诉他「里面有内容，但内容是图片，需要 OCR」。
    """
    calls = patch_ingest(monkeypatch)

    response = upload(filename="scan.pdf", content=build_pdf([]))

    assert response.status_code == 422
    assert response.json()["detail"] == routes.RAG_UPLOAD_NO_TEXT_LAYER_DETAIL
    # 解析出「没有文字」是在处理器里判定的，不该走到入库
    assert calls == []


def test_docx_with_no_text_yields_empty_content(monkeypatch):
    """空的 docx 提取出空文本，**原样交给入库服务**，由它判「内容为空」。

    为什么空内容的判定不在处理器里：处理器只负责「把字节变成文本」，
    「这段文本值不值得入库」是入库服务的职责——它在真实链路里会对空文本
    抛 EmptyDocumentError（已由 test_knowledge_ingestion 覆盖）。这里只确认
    「处理器没有偷偷替它做决定」，比如没有往空文档里塞占位文字。
    """
    calls = patch_ingest(monkeypatch)

    response = upload(filename="empty.docx", content=build_docx([]))

    assert response.status_code == 200  # 入库被替换成替身，所以这里是 200
    assert calls[0]["content"] == ""


# --------------------------------------------------------------------------
# 上传：体积上限
# --------------------------------------------------------------------------


def test_oversized_upload_returns_422_without_calling_the_service(monkeypatch):
    """超限要在读的时候就停下——不是读完整份之后再补一句「你超限了」。

    这条断言的重点是 calls == []：证明服务一次都没被调用，
    也就意味着超大的内容没有被送进切片与向量流程。
    """
    calls = patch_ingest(monkeypatch)
    oversized = b"a" * (routes.MAX_UPLOAD_BYTES + 1)

    response = upload(content=oversized)

    assert response.status_code == 422
    assert "MiB" in response.json()["detail"]
    assert calls == []


def test_upload_at_the_limit_is_accepted(monkeypatch):
    """边界值本身合法：恰好等于上限应当放行。"""
    calls = patch_ingest(monkeypatch)
    exact = b"a" * routes.MAX_UPLOAD_BYTES

    response = upload(content=exact)

    assert response.status_code == 200
    assert len(calls[0]["content"]) == routes.MAX_UPLOAD_BYTES


def test_read_within_limit_stops_early_instead_of_buffering_everything():
    """直接测那个读函数：超限时抛错，且返回的字节数不超过上限加一个块。

    它是「不把超大文件读进内存」这条承诺的实现处，
    单独测比隔着 HTTP 断言更说明问题。
    """

    class _FakeUpload:
        def __init__(self, payload: bytes) -> None:
            self._payload = payload
            self._offset = 0
            self.read_bytes = 0

        async def read(self, size: int) -> bytes:
            chunk = self._payload[self._offset : self._offset + size]
            self._offset += len(chunk)
            self.read_bytes += len(chunk)
            return chunk

    limit = 1024
    fake = _FakeUpload(b"a" * 100_000)

    with pytest.raises(routes.UploadTooLargeError):
        asyncio.run(routes.read_upload_within_limit(fake, limit=limit))

    # 最多读到「上限 + 一个块」就停手，而不是把 10 万字节全读完
    assert fake.read_bytes <= limit + routes.UPLOAD_CHUNK_BYTES


def test_read_within_limit_returns_the_exact_bytes():
    class _FakeUpload:
        def __init__(self, payload: bytes) -> None:
            self._payload = payload
            self._offset = 0

        async def read(self, size: int) -> bytes:
            chunk = self._payload[self._offset : self._offset + size]
            self._offset += len(chunk)
            return chunk

    payload = "正文。".encode()

    result = asyncio.run(routes.read_upload_within_limit(_FakeUpload(payload), limit=1024))

    assert result == payload


# --------------------------------------------------------------------------
# 上传：服务端故障
# --------------------------------------------------------------------------


def test_missing_embedding_config_returns_500_without_leaking_the_key(monkeypatch):
    marker = "sk-zz-secret-marker-zz"
    patch_ingest(
        monkeypatch, error=ConfigurationError(f"缺少 EMBEDDING_API_KEY（{marker}）")
    )

    response = upload()

    assert response.status_code == 500
    assert response.json()["detail"] == routes.RAG_UPLOAD_NOT_READY_DETAIL
    assert marker not in response.text


def test_database_error_returns_503(monkeypatch):
    patch_ingest(
        monkeypatch,
        error=OperationalError("INSERT", {}, Exception("connection refused")),
    )

    response = upload()

    assert response.status_code == 503
    assert response.json()["detail"] == routes.RAG_KNOWLEDGE_UNAVAILABLE_DETAIL


def test_unexpected_error_returns_500_with_a_fixed_message(monkeypatch):
    marker = "zz-internal-detail-zz"
    patch_ingest(monkeypatch, error=RuntimeError(f"内部细节 {marker}"))

    response = upload()

    assert response.status_code == 500
    assert response.json()["detail"] == routes.RAG_UPLOAD_FAILED_DETAIL
    assert marker not in response.text


def test_error_response_does_not_echo_the_file_content(monkeypatch):
    """文件正文属于用户数据：不进普通日志，更不能回显在错误响应里。"""
    patch_ingest(monkeypatch, error=RuntimeError("boom"))

    response = upload(content=f"# 标题\n\n{CONTENT_MARKER}".encode())

    assert response.status_code == 500
    assert CONTENT_MARKER not in response.text


def test_error_response_does_not_echo_the_title(monkeypatch):
    patch_ingest(monkeypatch, error=RuntimeError("boom"))

    response = upload(title=CONTENT_MARKER)

    assert CONTENT_MARKER not in response.text


# --------------------------------------------------------------------------
# 列表
# --------------------------------------------------------------------------


def test_list_returns_documents(monkeypatch):
    patch_list(
        monkeypatch,
        documents=[
            make_summary(source_file="orders.md", document_title="订单口径", chunk_count=3),
            make_summary(source_file="members.md", document_title="会员规则", chunk_count=7),
        ],
    )

    with TestClient(app) as client:
        response = client.get(ENDPOINT)

    assert response.status_code == 200
    documents = response.json()["documents"]
    assert [item["source_file"] for item in documents] == ["orders.md", "members.md"]
    assert documents[1]["chunk_count"] == 7


def test_empty_knowledge_base_returns_200_with_an_empty_list(monkeypatch):
    """空库是「还没有文档」这个诚实的业务结果，不是故障。

    这里要是回 404 或 500，页面就会显示成报错，而用户其实什么都没做错。
    """
    patch_list(monkeypatch, documents=[])

    with TestClient(app) as client:
        response = client.get(ENDPOINT)

    assert response.status_code == 200
    assert response.json()["documents"] == []


def test_list_serializes_timestamps_as_iso_strings(monkeypatch):
    updated = MOMENT + timedelta(days=1)
    patch_list(monkeypatch, documents=[make_summary(updated_at=updated)])

    with TestClient(app) as client:
        response = client.get(ENDPOINT)

    item = response.json()["documents"][0]
    # 前端 new Date(...) 要能解析它
    assert item["updated_at"].startswith("2026-09-24T12:00:00")
    assert datetime.fromisoformat(item["updated_at"]) == updated


def test_list_does_not_expose_internal_fields(monkeypatch):
    """列表项里不能出现 id / content_hash —— 它们是内部主键与查重指纹。"""
    patch_list(monkeypatch, documents=[make_summary()])

    with TestClient(app) as client:
        item = client.get(ENDPOINT).json()["documents"][0]

    assert set(item) == {
        "source_file",
        "document_title",
        "chunk_count",
        "created_at",
        "updated_at",
    }


def test_list_database_error_returns_503(monkeypatch):
    patch_list(
        monkeypatch,
        error=OperationalError("SELECT", {}, Exception("connection refused")),
    )

    with TestClient(app) as client:
        response = client.get(ENDPOINT)

    assert response.status_code == 503
    assert response.json()["detail"] == routes.RAG_KNOWLEDGE_UNAVAILABLE_DETAIL


def test_list_configuration_error_returns_500(monkeypatch):
    patch_list(monkeypatch, error=ConfigurationError("缺少 DATABASE_URL"))

    with TestClient(app) as client:
        response = client.get(ENDPOINT)

    assert response.status_code == 500
    assert response.json()["detail"] == routes.RAG_DOCUMENT_LIST_FAILED_DETAIL


def test_list_unexpected_error_returns_500_without_detail(monkeypatch):
    marker = "zz-internal-detail-zz"
    patch_list(monkeypatch, error=RuntimeError(f"内部细节 {marker}"))

    with TestClient(app) as client:
        response = client.get(ENDPOINT)

    assert response.status_code == 500
    assert marker not in response.text


# --------------------------------------------------------------------------
# 路由形状与回归
# --------------------------------------------------------------------------


def test_documents_endpoint_supports_post_and_get_only():
    methods = app.openapi()["paths"][ENDPOINT]

    assert set(methods) == {"post", "get"}


def test_upload_endpoint_declares_a_multipart_body():
    """请求体必须是 multipart/form-data —— 否则前端传文件会直接 422。"""
    request_body = app.openapi()["paths"][ENDPOINT]["post"]["requestBody"]

    assert "multipart/form-data" in request_body["content"]


def test_existing_endpoints_did_not_regress():
    paths = app.openapi()["paths"]

    for path in (
        "/",
        "/chat",
        "/health/db",
        "/api/v1/health",
        "/api/v1/data/query",
        "/api/v1/agent/data-query",
        "/api/v1/rag/answer",
        ENDPOINT,
    ):
        assert path in paths, f"路由丢失：{path}"
