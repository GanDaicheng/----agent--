"""知识库模型与迁移的静态测试。

**本文件不连接数据库。** 断言的都是「模型定义」和「迁移文件内容」——
这两样在 Python 里就能检查干净，不需要一个真库在旁边。
需要真实数据库才能验证的部分（列类型真的是 vector(1024)、外键真的级联删除）
由 alembic 迁移时的 DDL 渲染和一次性实测覆盖，不放进常规测试套件——
保持「pytest 不需要 PostgreSQL」这条项目约定。

这里守三类风险：
1. 模型定义漂移：列类型、可空性、约束名被无意改掉；
2. 迁移文件写坏：忘了幂等的 CREATE EXTENSION、回滚时误删扩展、加了不该加的向量索引；
3. 维度三处不同步：模型 / 迁移 / .env。
"""

import ast
import pathlib

import pytest
from sqlalchemy import BigInteger, UniqueConstraint

from app.core.config import get_settings
from app.models import Base
from app.models.knowledge import (
    CONTENT_HASH_LENGTH,
    KNOWLEDGE_EMBEDDING_DIMENSIONS,
    KnowledgeChunk,
    KnowledgeDocument,
    Vector,
)

BACKEND_DIR = pathlib.Path(__file__).resolve().parents[1]
ALEMBIC_INI = BACKEND_DIR / "alembic.ini"
VERSIONS_DIR = BACKEND_DIR / "alembic" / "versions"

NEW_REVISION = "69e6c2579c1b"
PREVIOUS_REVISION = "e205344666e8"
NEW_MIGRATION_FILE = VERSIONS_DIR / f"{NEW_REVISION}_create_knowledge_base_schema.py"

# 迁移之前的 5 张零售表 + alembic 自己的版本表，字段一个都不该变
RETAIL_TABLE_COLUMNS = {
    "customers": {"customer_id", "customer_name", "member_level", "registered_at", "created_at"},
    "products": {"product_id", "product_name", "category_name", "unit_price", "created_at"},
    "regions": {"region_id", "region_name", "region_level", "created_at"},
    "date_dim": {
        "date_id", "full_date", "year", "quarter", "month",
        "month_name", "day_of_month", "week_of_year", "is_weekend",
    },
    "orders": {
        "order_id", "order_no", "customer_id", "product_id", "region_id", "date_id",
        "quantity", "unit_price", "gross_amount", "discount_amount", "net_amount",
    },
}


def migration_source(path: pathlib.Path) -> str:
    """迁移文件原文。只用于「文件存在/能读」这类不敏感的断言。"""
    return path.read_text(encoding="utf-8")


def migration_module_assignments(path: pathlib.Path) -> dict[str, str]:
    """迁移文件顶层的赋值语句，例如 revision / down_revision / 维度常量。

    为什么不直接对原文做正则？因为注释会一起被命中。
    这个坑当场踩到了：迁移注释里写了「本迁移不创建 HNSW / IVFFlat 索引」，
    于是「不该出现 hnsw」那条测试反而因为注释写得清楚而失败。
    要看代码就看 AST，别拿字符串猜。
    """
    tree = ast.parse(migration_source(path))
    assignments: dict[str, str] = {}
    for node in tree.body:
        # revision / down_revision 是带类型注解的赋值（AnnAssign），
        # 而 EMBEDDING_DIMENSIONS 是普通赋值（Assign）——两种都要收。
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            if node.value is not None:
                assignments[node.target.id] = ast.unparse(node.value)
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    assignments[target.id] = ast.unparse(node.value)
    return assignments


def function_calls(path: pathlib.Path, function_name: str) -> list[str]:
    """某个函数体内所有调用的源码文本（注释天然不会出现在这里）。"""
    tree = ast.parse(migration_source(path))
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == function_name:
            return [
                ast.unparse(child) for child in ast.walk(node) if isinstance(child, ast.Call)
            ]
    raise AssertionError(f"迁移里没有找到 {function_name}()")


def upgrade_calls() -> list[str]:
    return function_calls(NEW_MIGRATION_FILE, "upgrade")


def downgrade_calls() -> list[str]:
    return function_calls(NEW_MIGRATION_FILE, "downgrade")


# --------------------------------------------------------------------------
# 模型已登记进 metadata（env.py 只导入 app.models，漏登记 autogenerate 就看不见）
# --------------------------------------------------------------------------


@pytest.mark.parametrize("table_name", ["knowledge_documents", "knowledge_chunks"])
def test_new_tables_are_registered_in_metadata(table_name):
    assert table_name in Base.metadata.tables


def test_models_are_exported_from_the_models_package():
    import app.models as models

    assert models.KnowledgeDocument is KnowledgeDocument
    assert models.KnowledgeChunk is KnowledgeChunk
    assert models.KNOWLEDGE_EMBEDDING_DIMENSIONS == KNOWLEDGE_EMBEDDING_DIMENSIONS


# --------------------------------------------------------------------------
# knowledge_documents
# --------------------------------------------------------------------------


def test_documents_table_columns():
    table = Base.metadata.tables["knowledge_documents"]

    assert set(table.c.keys()) == {
        "id", "source_file", "document_title", "content_hash",
        "chunk_count", "created_at", "updated_at",
    }


def test_documents_primary_key_is_bigint_autoincrement():
    column = Base.metadata.tables["knowledge_documents"].c.id

    assert isinstance(column.type, BigInteger)
    assert column.primary_key
    assert column.autoincrement is True


def test_source_file_is_unique_and_not_nullable():
    column = Base.metadata.tables["knowledge_documents"].c.source_file

    assert column.nullable is False
    assert column.unique is True


def test_content_hash_columns_are_long_enough_for_sha256():
    """sha256 十六进制是 64 字符。列写短了会在入库时被静默截断或直接报错。"""
    assert CONTENT_HASH_LENGTH == 64

    documents = Base.metadata.tables["knowledge_documents"].c.content_hash
    chunks = Base.metadata.tables["knowledge_chunks"].c.content_hash

    assert documents.type.length == CONTENT_HASH_LENGTH
    assert chunks.type.length == CONTENT_HASH_LENGTH


@pytest.mark.parametrize("column_name", ["created_at", "updated_at"])
def test_timestamps_have_server_defaults(column_name):
    column = Base.metadata.tables["knowledge_documents"].c[column_name]

    assert column.nullable is False
    assert column.server_default is not None


# --------------------------------------------------------------------------
# knowledge_chunks
# --------------------------------------------------------------------------


def test_chunks_table_columns():
    table = Base.metadata.tables["knowledge_chunks"]

    assert set(table.c.keys()) == {
        "id", "document_id", "section_title", "chunk_index",
        "content", "content_for_embedding", "content_hash",
        "estimated_token_count", "char_count",
        "embedding", "embedding_model", "created_at", "updated_at",
    }


def test_embedding_column_renders_as_vector_with_the_configured_dimension():
    """列类型必须渲染成 vector(1024)，而不是 TEXT 或没有长度的 vector。"""
    column = Base.metadata.tables["knowledge_chunks"].c.embedding

    assert isinstance(column.type, Vector)
    assert column.type.dimensions == KNOWLEDGE_EMBEDDING_DIMENSIONS
    assert str(column.type) == f"vector({KNOWLEDGE_EMBEDDING_DIMENSIONS})"


def test_embedding_column_is_nullable():
    """可空是有意的：支持「先落文本、后补向量」，接口超时不至于丢整批数据。"""
    assert Base.metadata.tables["knowledge_chunks"].c.embedding.nullable is True


def test_embedding_model_column_is_nullable():
    column = Base.metadata.tables["knowledge_chunks"].c.embedding_model

    assert column.nullable is True


def test_document_id_foreign_key_cascades_on_delete():
    table = Base.metadata.tables["knowledge_chunks"]
    foreign_keys = list(table.c.document_id.foreign_keys)

    assert len(foreign_keys) == 1
    target = foreign_keys[0]
    assert target.target_fullname == "knowledge_documents.id"
    assert target.ondelete == "CASCADE"


def test_chunk_unique_constraint_is_the_document_scoped_pair():
    """唯一性必须是 (document_id, chunk_index) 组合。

    如果误写成全局 content_hash 唯一，不同文档里一模一样的说明片段会让后者入库失败。
    """
    table = Base.metadata.tables["knowledge_chunks"]
    uniques = [c for c in table.constraints if isinstance(c, UniqueConstraint)]

    assert len(uniques) == 1
    assert {column.name for column in uniques[0].columns} == {"document_id", "chunk_index"}
    assert uniques[0].name == "uq_knowledge_chunks_document_id_chunk_index"


def test_content_hash_is_indexed_but_not_unique():
    """content_hash 只建普通索引，不做全局唯一（去重策略留给后续）。"""
    table = Base.metadata.tables["knowledge_chunks"]
    indexes = {index.name: index for index in table.indexes}

    assert "ix_knowledge_chunks_content_hash" in indexes
    assert indexes["ix_knowledge_chunks_content_hash"].unique is False


def test_no_vector_index_is_created():
    """当前只有 44 个切片，精确扫描更合适；建 HNSW/IVFFlat 需要单独一个迁移。"""
    table = Base.metadata.tables["knowledge_chunks"]
    index_names = " ".join(index.name for index in table.indexes).lower()

    assert "hnsw" not in index_names
    assert "ivfflat" not in index_names


@pytest.mark.parametrize(
    "constraint_name",
    [
        "ck_knowledge_chunks_char_count_not_negative",
        "ck_knowledge_chunks_chunk_index_not_negative",
        "ck_knowledge_chunks_estimated_token_count_not_negative",
        "ck_knowledge_documents_chunk_count_not_negative",
    ],
)
def test_non_negative_check_constraints_exist(constraint_name):
    all_names = {
        constraint.name
        for table in ("knowledge_documents", "knowledge_chunks")
        for constraint in Base.metadata.tables[table].constraints
    }
    assert constraint_name in all_names


# --------------------------------------------------------------------------
# Vector 类型的序列化处理器（纯函数，不连库）
# --------------------------------------------------------------------------


def test_vector_get_col_spec_reports_the_dimension():
    assert Vector(1024).get_col_spec() == "vector(1024)"
    assert Vector(768).get_col_spec() == "vector(768)"


def test_vector_bind_processor_serializes_python_floats():
    process = Vector(3).bind_processor(None)

    assert process([0.1, 0.2, 0.3]) == "[0.1,0.2,0.3]"
    assert process([1, 2, 3]) == "[1.0,2.0,3.0]"


def test_vector_bind_processor_passes_through_none_and_strings():
    process = Vector(3).bind_processor(None)

    assert process(None) is None
    # 已经是 pgvector 文本格式时原样放行，便于直接执行 SQL 的场景
    assert process("[0.1,0.2,0.3]") == "[0.1,0.2,0.3]"


def test_vector_result_processor_parses_back_to_floats():
    process = Vector(3).result_processor(None, None)

    assert process("[0.1,0.2,0.3]") == [0.1, 0.2, 0.3]
    assert process(None) is None
    assert process("[]") == []


def test_vector_round_trip_preserves_values():
    """写进去再读出来必须完全一致——这是入库和检索都依赖的性质。"""
    bind = Vector(4).bind_processor(None)
    result = Vector(4).result_processor(None, None)

    original = [0.125, -1.5, 3.0, 0.0]

    assert result(bind(original)) == original


def test_vector_type_is_cacheable():
    """cache_ok=False 会让 SQLAlchemy 每次编译语句都重新生成 SQL，白费性能。"""
    assert Vector(1024).cache_ok is True


# --------------------------------------------------------------------------
# 维度三处必须同步：模型 / 迁移 / .env
# --------------------------------------------------------------------------


def test_model_dimension_matches_configured_embedding_dimension():
    """模型里的 vector(N) 必须与 .env 的 EMBEDDING_DIMENSION 一致。

    这两处一旦不一致，插入时会报「expected N dimensions」，
    而报错发生在入库那一刻、离改配置的那一刻很远。在这里提前拦住。
    改维度需要三步同时做：改 .env、改模型常量、新写一个迁移改列类型
    （PG 不允许直接改 vector 的长度）。"""
    configured = get_settings().embedding_dimension

    assert KNOWLEDGE_EMBEDDING_DIMENSIONS == configured, (
        f"模型是 vector({KNOWLEDGE_EMBEDDING_DIMENSIONS})，"
        f"但 .env 的 EMBEDDING_DIMENSION 是 {configured}。"
        "改维度要同步：.env、app/models/knowledge.py、以及一个改列类型的新迁移。"
    )


# --------------------------------------------------------------------------
# 迁移文件
# --------------------------------------------------------------------------


def test_new_migration_file_exists_and_chains_onto_the_previous_revision():
    assignments = migration_module_assignments(NEW_MIGRATION_FILE)

    assert assignments["revision"] == f"'{NEW_REVISION}'"
    assert assignments["down_revision"] == f"'{PREVIOUS_REVISION}'"


def test_existing_migration_is_untouched():
    """已有迁移必须保持冻结——它记录的是当时发生了什么，改了就无法重放。"""
    path = VERSIONS_DIR / f"{PREVIOUS_REVISION}_create_retail_analytics_schema.py"
    assignments = migration_module_assignments(path)

    assert assignments["revision"] == f"'{PREVIOUS_REVISION}'"
    assert assignments["down_revision"] == "None"


def test_migration_is_the_single_alembic_head():
    """迁移链只能有一个头；出现分叉时 upgrade head 会报错，谁也不知道该走哪条。"""
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    config = Config(str(ALEMBIC_INI))
    heads = ScriptDirectory.from_config(config).get_heads()

    assert list(heads) == [NEW_REVISION]


def test_migration_creates_the_vector_extension_idempotently():
    """迁移自己保证扩展存在，否则干净机器上 upgrade head 会失败。"""
    assert any(
        "CREATE EXTENSION IF NOT EXISTS vector" in call for call in upgrade_calls()
    )


def test_migration_downgrade_does_not_drop_the_extension():
    """回滚知识库不该顺带废掉别人的向量列——扩展是库级别共享对象。"""
    assert not any("DROP EXTENSION" in call.upper() for call in downgrade_calls())


def test_migration_creates_both_tables_and_an_embedding_column():
    calls = upgrade_calls()

    assert any("'knowledge_documents'" in call for call in calls)
    assert any("'knowledge_chunks'" in call for call in calls)
    # 列类型由 VectorType 渲染，维度取自模块常量
    assert any("VectorType(EMBEDDING_DIMENSIONS)" in call for call in calls)
    assert migration_module_assignments(NEW_MIGRATION_FILE)["EMBEDDING_DIMENSIONS"] == "1024"


def test_migration_does_not_create_a_vector_index():
    """建表语句里不该出现向量索引；要加索引得单独写一个迁移。"""
    joined = " ".join(upgrade_calls()).lower()

    assert "hnsw" not in joined
    assert "ivfflat" not in joined


def test_migration_does_not_touch_the_retail_tables():
    """本迁移只新增两张表，不得出现删除或修改零售表的语句。"""
    joined = " ".join(upgrade_calls())

    for table in RETAIL_TABLE_COLUMNS:
        assert f"drop_table('{table}')" not in joined
        assert f"'{table}'" not in joined, f"upgrade 里提到了零售表 {table}"


def test_migration_does_not_touch_the_retail_tables():
    """本迁移只新增两张表，不得出现删除或修改零售表的语句。"""
    source = migration_source(NEW_MIGRATION_FILE)
    upgrade_body = source.split("def downgrade()")[0]

    for table in RETAIL_TABLE_COLUMNS:
        assert f"drop_table('{table}')" not in upgrade_body
        assert f'"{table}"' not in upgrade_body, f"upgrade 里提到了零售表 {table}"


# --------------------------------------------------------------------------
# 零售模型未被改动
# --------------------------------------------------------------------------


@pytest.mark.parametrize(("table_name", "expected"), RETAIL_TABLE_COLUMNS.items())
def test_retail_table_columns_are_unchanged(table_name, expected):
    """这 5 张表的字段一个都不该动。加了或删了列都必须是有意识的行为，
    这个测试就是那道「有意识」的关卡。"""
    assert set(Base.metadata.tables[table_name].c.keys()) == expected


def test_retail_member_levels_are_still_the_four_known_values():
    from app.models import MEMBER_LEVELS

    assert MEMBER_LEVELS == ("普通会员", "银卡会员", "金卡会员", "黑金会员")
