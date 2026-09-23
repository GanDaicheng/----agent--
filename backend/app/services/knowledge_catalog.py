"""知识文档目录：列出已入库的文档。

## 为什么单独一个模块

入库在 knowledge_ingestion.py（往里写），检索在 knowledge_search.py（读切片）。
「列出库里有哪些文档」既不是入库也不是切片检索，塞进哪一个都会让那个模块
多出一份不相干的职责。这里只做一件事：把 knowledge_documents 表读成一份清单。

## 为什么不返回主键

knowledge_documents.id 是数据库内部主键。当前还没有任何「按 id 操作某份文档」的
接口（删除、重命名都还没做），把它发出去只会多一个没人用的字段，却在对外契约里
永久占住一个位置。等真的有了按 id 删除，再补不迟——那时它的含义也是明确的。
这与 /api/v1/rag/answer 的来源列表刻意不带 chunk_id / document_id 是同一条约定。

## 排序为什么是两个字段

主排序是 updated_at 倒序：刚上传或刚更新过的文档排在最前，这是「数据采集」页面上
最想先看到的东西。

但**只按它排是不够的**：updated_at 虽然精度到微秒，一批文档同时写入（目录同步就是
这样）仍然可能拿到同一个时间戳。同值时 PostgreSQL 不保证返回顺序稳定，两次请求
可能给出不同的排列，页面看起来会「自己抖动」。所以补一个 source_file 作为兜底，
让顺序在任何情况下都是确定的。

本模块只读：不写任何数据、不调模型、不碰业务表。
"""

from collections.abc import Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncConnection

from app.models.knowledge import KnowledgeDocument
from app.repositories.database import get_connection


@dataclass(frozen=True)
class KnowledgeDocumentSummary:
    """列表里的一份文档。

    只有能给人看的字段：没有 content_hash（那是查重用的内部指纹，
    对用户没有意义），也没有 id（理由见模块说明）。
    """

    source_file: str
    document_title: str
    chunk_count: int
    created_at: datetime
    updated_at: datetime


@asynccontextmanager
async def _connection_scope(connection: AsyncConnection | None):
    """有外部连接就用外部的（测试注入用），没有再自己借一条。

    与 knowledge_search.py 的同名工具保持一致：两个只读服务用同一套连接注入方式，
    测试写起来才不用记两套规则。
    """
    if connection is not None:
        yield connection
        return
    async with get_connection() as borrowed:
        yield borrowed


def build_document_summary(row: Mapping[str, Any]) -> KnowledgeDocumentSummary:
    """把一行查询结果映射成清单项。"""
    return KnowledgeDocumentSummary(
        source_file=str(row["source_file"]),
        document_title=str(row["document_title"]),
        chunk_count=int(row["chunk_count"]),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


async def list_documents(
    *, connection: AsyncConnection | None = None
) -> list[KnowledgeDocumentSummary]:
    """列出知识库里已有的文档，最近的排在最前。

    connection 可注入，测试因此不必连数据库。
    """
    async with _connection_scope(connection) as active:
        table = KnowledgeDocument.__table__
        rows = (
            await active.execute(
                select(
                    table.c.source_file,
                    table.c.document_title,
                    table.c.chunk_count,
                    table.c.created_at,
                    table.c.updated_at,
                ).order_by(table.c.updated_at.desc(), table.c.source_file.asc())
            )
        ).mappings().all()

    return [build_document_summary(row) for row in rows]
