"""ORM 基类与建表命名约定。

Alembic 的 autogenerate 会把约束/索引的名字写进迁移文件。如果不预先约定命名规则，
PostgreSQL 自动生成的名字和 SQLAlchemy 默认名字会不一致，导致后续迁移反复出现
「drop 一个不存在的索引、再建一个同名索引」的噪声。这里统一命名，让迁移可重复。
"""

from sqlalchemy import MetaData
from sqlalchemy.orm import DeclarativeBase

NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    """所有零售分析表的公共基类。"""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)
