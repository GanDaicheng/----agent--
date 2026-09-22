"""智能问数 Agent 的两个检索工具。

为什么单独一个 tools.py，而不是把搜索函数写进 catalog.py？
- catalog.py 是「知识层」：纯数据 + 纯函数，不依赖任何框架，谁都能导入。
- tools.py 是「能力层」：把知识层包成 LangChain 工具，带上给调用方看的说明书。
两层分开后，换框架（比如以后不用 LangChain）只需要重写这一层，
catalog.py 一行都不用动。

工具和普通函数的区别不只是装饰器。看下面的 docstring 就明白：
工具的 docstring 是写给「调用方」看的接口说明，而不是给维护者看的实现注释。
现在调用方是我们自己的节点；将来把 Agent 交给 LLM 自主选工具时，
这段文字就是模型唯一能看到的说明——写得含糊，模型就会选错工具。

注意：这两个工具只查 catalog.py 里登记过的资产，检索不到就返回空列表，
绝不会凭空编造指标名或表名。
"""

from langchain_core.tools import tool

from app.agent.data_query.catalog import (
    search_datasets_in_catalog,
    search_metrics_in_catalog,
)
from app.agent.data_query.state import MatchedAsset


@tool
def search_metrics(query: str) -> list[MatchedAsset]:
    """根据用户问题的中文关键词，检索已登记的指标（业务口径）。

    输入 query 是用户的原始问题，例如「华东地区近六个月销售额趋势怎么样」。
    返回命中的指标列表，每项包含 kind（固定为 metric）、name（指标内部名，
    如 sales_amount）、reason（中文说明为什么匹配）。
    没有命中时返回空列表 []，此时不应虚构任何指标。

    本工具只覆盖已登记的口径：销售额、订单数、客单价、复购率。
    """
    return search_metrics_in_catalog(query)


@tool
def search_datasets(query: str) -> list[MatchedAsset]:
    """根据用户问题的中文关键词，检索可能用到的数据集（数据表）。

    输入 query 是用户的原始问题，例如「华东地区近六个月销售额趋势怎么样」。
    返回命中的数据集列表，每项包含 kind（固定为 dataset）、name（数据集内部名，
    如 orders）、reason（中文说明为什么匹配）。
    没有命中时返回空列表 []，此时不应虚构任何数据集。

    本工具只覆盖已登记的数据集：orders（订单明细）、customers（客户）、
    products（商品）、regions（区域）、date_dim（日期维度）。
    这些是模拟元数据，不代表数据库里已经建好了对应的表。
    """
    return search_datasets_in_catalog(query)
