"""ORM 模型包。

Alembic 的 env.py 只导入本包，因此新增模型后必须在这里登记一次，
否则 autogenerate 会「看不见」这张表，迁移文件里就会缺表。
"""

from app.models.base import Base
from app.models.retail import MEMBER_LEVELS, Customer, DateDim, Order, Product, Region

__all__ = [
    "Base",
    "MEMBER_LEVELS",
    "Customer",
    "DateDim",
    "Order",
    "Product",
    "Region",
]
