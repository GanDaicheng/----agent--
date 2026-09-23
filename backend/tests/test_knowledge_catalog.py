"""知识文档目录（列表）服务的测试。

**不连数据库。** 连接由 FakeCatalogConnection 注入，
`list_documents` 的 connection 参数就是为这个留的。

这里要守住的是一条容易被顺手改坏的约定：**列表里不出现内部字段**
（id、content_hash）。它们现在没用，但一旦发出去就进了对外契约，
以后想删就得考虑兼容；而且 id 是数据库主键，泄露它对调用方没有价值。
"""

import asyncio
import dataclasses
from datetime import datetime, timedelta, timezone

import pytest

from app.services.knowledge_catalog import (
    KnowledgeDocumentSummary,
    build_document_summary,
    list_documents,
)

# 断言「不外发内部字段」时用的名单
INTERNAL_FIELDS = ("id", "document_id", "content_hash", "embedding")


class _FakeMappings:
    def __init__(self, rows) -> None:
        self._rows = rows

    def all(self):
        return list(self._rows)


class _FakeResult:
    def __init__(self, rows) -> None:
        self._rows = rows

    def mappings(self):
        return _FakeMappings(self._rows)


class FakeCatalogConnection:
    """记录发出去的语句；execute 返回预设行。"""

    def __init__(self, rows=()) -> None:
        self.rows = list(rows)
        self.calls: list[str] = []

    async def execute(self, statement, parameters=None):
        self.calls.append(str(statement))
        return _FakeResult(self.rows)


def make_row(
    *,
    source_file: str = "retail_metrics.md",
    document_title: str = "零售核心指标口径说明",
    chunk_count: int = 9,
    created_at: datetime | None = None,
    updated_at: datetime | None = None,
) -> dict:
    moment = datetime(2026, 9, 23, 12, 0, tzinfo=timezone.utc)
    return {
        "source_file": source_file,
        "document_title": document_title,
        "chunk_count": chunk_count,
        "created_at": created_at or moment,
        "updated_at": updated_at or moment,
    }


async def run_list(rows=()):
    connection = FakeCatalogConnection(rows)
    documents = await list_documents(connection=connection)
    return documents, connection


# --------------------------------------------------------------------------
# 行映射
# --------------------------------------------------------------------------


def test_row_fields_are_mapped_through():
    row = make_row(
        source_file="member_rules.md",
        document_title="会员等级与复购口径",
        chunk_count=12,
    )

    summary = build_document_summary(row)

    assert isinstance(summary, KnowledgeDocumentSummary)
    assert summary.source_file == "member_rules.md"
    assert summary.document_title == "会员等级与复购口径"
    assert summary.chunk_count == 12


def test_timestamps_are_passed_through_unchanged():
    """时间戳原样带出，不在这一层做任何格式化。

    格式化是展示层的事（前端要按本地时区显示）；在这里转成字符串会让
    API 响应里出现一个「看着像时间但已经是死字符串」的字段。
    """
    created = datetime(2026, 1, 2, 3, 4, 5, tzinfo=timezone.utc)
    updated = created + timedelta(days=30)

    summary = build_document_summary(
        make_row(created_at=created, updated_at=updated)
    )

    assert summary.created_at == created
    assert summary.updated_at == updated
    assert isinstance(summary.created_at, datetime)


def test_chunk_count_is_coerced_to_int():
    """驱动若把 count 给成字符串，这里要转成 int。

    否则响应里会出现 `"chunk_count": "9"`，前端拿到字符串做数值运算
    会静默出错（JS 里 "9" + 1 == "91"）。
    """
    summary = build_document_summary(make_row(chunk_count="9"))

    assert summary.chunk_count == 9
    assert isinstance(summary.chunk_count, int)


def test_summary_exposes_no_internal_fields():
    """列表项只有那五个能给人看的字段。"""
    names = {field.name for field in dataclasses.fields(KnowledgeDocumentSummary)}

    assert names == {
        "source_file",
        "document_title",
        "chunk_count",
        "created_at",
        "updated_at",
    }
    for forbidden in INTERNAL_FIELDS:
        assert not hasattr(build_document_summary(make_row()), forbidden)


def test_summary_is_immutable():
    summary = build_document_summary(make_row())

    with pytest.raises(dataclasses.FrozenInstanceError):
        summary.chunk_count = 99  # type: ignore[misc]


# --------------------------------------------------------------------------
# 查询语句
# --------------------------------------------------------------------------


def test_query_does_not_select_internal_columns():
    """SELECT 里不能出现 id 和 content_hash。

    读出来再丢掉是另一种写法，但那意味着这两个字段会一路被搬进内存、
    写进测试替身，最后总有人「顺手」把它们加进响应模型。不读就没事。
    """
    _, connection = asyncio.run(run_list())

    assert len(connection.calls) == 1
    projection = connection.calls[0].split("FROM")[0]
    assert "knowledge_documents.id" not in projection
    assert "content_hash" not in projection


def test_query_selects_exactly_the_five_public_columns():
    _, connection = asyncio.run(run_list())

    projection = connection.calls[0].split("FROM")[0]
    for column in (
        "source_file",
        "document_title",
        "chunk_count",
        "created_at",
        "updated_at",
    ):
        assert column in projection, column


def test_query_orders_by_updated_at_descending():
    """最近更新的排最前，且顺序必须确定（见模块说明里的同值问题）。"""
    _, connection = asyncio.run(run_list())

    sql = connection.calls[0]
    assert "ORDER BY" in sql
    assert "updated_at DESC" in sql
    # 同值兜底：再按 source_file 排
    assert "source_file ASC" in sql


def test_query_reads_from_the_documents_table():
    _, connection = asyncio.run(run_list())

    assert "FROM knowledge_documents" in connection.calls[0]


def test_query_takes_no_parameters():
    """只读列表不需要任何参数——没有参数也就没有注入面。"""
    _, connection = asyncio.run(run_list())

    assert ":" not in connection.calls[0]


# --------------------------------------------------------------------------
# 结果集
# --------------------------------------------------------------------------


def test_empty_table_returns_an_empty_list():
    """空库是正常结果，不是错误——页面上显示「还没有文档」而不是报错。"""
    documents, _ = asyncio.run(run_list())

    assert documents == []


def test_all_rows_are_returned_in_the_order_the_database_gave_them():
    """服务层不重排：顺序由 SQL 的 ORDER BY 决定。

    在 Python 里再排一遍，就等于有两处排序规则，早晚会不一致。
    """
    rows = [
        make_row(source_file="b.md", updated_at=datetime(2026, 9, 23, tzinfo=timezone.utc)),
        make_row(source_file="a.md", updated_at=datetime(2026, 9, 22, tzinfo=timezone.utc)),
    ]

    documents, _ = asyncio.run(run_list(rows))

    assert [item.source_file for item in documents] == ["b.md", "a.md"]


def test_every_row_becomes_one_summary():
    rows = [
        make_row(source_file="a.md", chunk_count=3),
        make_row(source_file="b.md", chunk_count=7),
    ]

    documents, _ = asyncio.run(run_list(rows))

    assert len(documents) == 2
    assert [item.chunk_count for item in documents] == [3, 7]
