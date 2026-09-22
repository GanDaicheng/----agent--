"""智能问数 Agent（data_query）——独立于通用聊天 Agent 的一套流程。

与 app/agent/graph.py 里的聊天 Agent 完全隔离，互不影响：

- 聊天 Agent：通用对话，可以调工具，需要模型 API Key。
- 本包：面向「自然语言问数」的固定流程，本次只搭骨架。

设计约束（后续补节点时也要守住）：
- 只有 intent.py 和 sql_generation.py 允许接入模型，且必须走
  app/core/llm.py 这个统一入口；
- 只有 sql_validation.py 允许导入 sqlglot；
- 其余模块不导入模型、数据库，也不直接读环境变量。

本次产出：
- State 定义（state.py）
- 模拟资产目录（catalog.py）：4 个指标 + 5 个数据集，纯常量，不代表已建表
- 两个检索工具（tools.py）：search_metrics / search_datasets
- 意图识别（intent.py）：Prompt + Pydantic 模型 + 分类器
- SQL 草稿生成（sql_generation.py）：受 Prompt + Schema 双重约束，
  同一模块也提供按校验问题修复一次的 repair_sql_draft
- SQL 安全校验（sql_validation.py）：sqlglot AST 逐条检查
- 模拟查询执行（mock_query.py）：按意图返回固定结果，不解析也不执行 SQL
- 结果解释（result_explanation.py）：把结构化结果解读成克制的中文结论；
  查询结果按不可信数据对待，用显式边界与系统规则隔开
- 图表建议（visualization.py）：**纯规则**产出前端可直接渲染的图表配置，
  不调用 LLM——字段对不上时降级为 table，绝不猜字段名
- 流程：intake → understand_question → discover_assets →（条件边）
        → generate_sql → validate_sql →（条件边）
        → 通过则 execute_query → explain_result → suggest_visualization → finish
        ／ 未通过且还有额度则 repair_sql → 回到 validate_sql

受控循环：图里唯一一条回边是 repair_sql → validate_sql，由
constants.MAX_SQL_RETRY 限制最多走一次；另用 constants.MAX_GRAPH_STEPS
绑定 recursion_limit 作为与业务无关的步数兜底。

至此 constants.PLANNED_NODE_ORDER 已清空——当初规划的节点全部接完。
真实数据库查询、RAG 仍是后续阶段的事。
"""

from app.agent.data_query.constants import MAX_GRAPH_STEPS, MAX_SQL_RETRY
from app.agent.data_query.graph import build_graph, get_data_query_graph
from app.agent.data_query.state import DataQueryState

__all__ = [
    "DataQueryState",
    "MAX_GRAPH_STEPS",
    "MAX_SQL_RETRY",
    "build_graph",
    "get_data_query_graph",
]
