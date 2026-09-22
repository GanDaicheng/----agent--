"""智能问数 Agent 的常量登记表。

节点名和上限值集中放在这里，而不是写在 nodes.py 或 graph.py 里，原因有两个：

1. 避免循环导入。graph.py 要导入 nodes.py 里的节点函数，如果节点名又定义在
   graph.py，nodes.py 就得反过来导入 graph.py，形成环。
2. 这是「还没实现什么」的总清单。下一步逐个补节点时，对着 PLANNED_NODE_ORDER
   往下做就行，不会漏也不会重。
"""

# ---------------- 已实现的节点名 ----------------
NODE_INTAKE = "intake"
NODE_UNDERSTAND_QUESTION = "understand_question"  # 调用模型识别意图
NODE_DISCOVER_ASSETS = "discover_assets"  # 调用 search_metrics / search_datasets
NODE_GENERATE_SQL = "generate_sql"  # 调用模型生成 SQL 草稿
NODE_VALIDATE_SQL = "validate_sql"  # 用 sqlglot AST 做安全校验
NODE_REPAIR_SQL = "repair_sql"  # 调用模型按 issues 修复一次草稿
NODE_EXECUTE_QUERY = "execute_query"  # 校验通过后产出模拟查询结果
NODE_EXPLAIN_RESULT = "explain_result"  # 调用模型把结果解读成中文结论
NODE_SUGGEST_VISUALIZATION = "suggest_visualization"  # 纯规则产出图表建议
NODE_FINISH = "finish"

# ---------------- 待实现的节点名 ----------------
# 空元组 = 当初计划的节点已经全部接完。这个常量保留着，是因为
# graph.py 的注释和测试都还在引用它；哪天要加新节点，往这里加就行。
PLANNED_NODE_ORDER: tuple[str, ...] = ()

# ---------------- 上限常量 ----------------
# SQL 修复最多只允许一次：修不好就带着校验结果收尾，避免无休止重试既慢又费钱。
# repair_sql 节点会在**调用模型之前**先把这个额度用掉，所以异常路径
# 也不会绕过上限。
MAX_SQL_RETRY = 1

# 单次问答的图执行步数上限，真正生效的地方在 graph.py：
# build_graph() 用 with_config({"recursion_limit": MAX_GRAPH_STEPS}) 把它
# 绑到编译产物上，调用方不传 config 也照样受这个上限保护。
#
# 它和 MAX_SQL_RETRY 管的是两件不同的事：
# - MAX_SQL_RETRY 管「业务上允许修几次」，是产品决策；
# - MAX_GRAPH_STEPS 管「这一个图最多走几步」，是防死循环的兜底。
# 正常路径走完一圈（含一次修复）是 8 步，留出余量给 12。
MAX_GRAPH_STEPS = 12

# 生成的 SQL 草稿允许的最大 LIMIT。
# 这个值同时被两边引用：sql_generation 写进 Prompt 告诉模型上限，
# sql_validation 用它拒绝超限的 SQL。只定义一处，两边就不可能对不上。
MAX_SQL_LIMIT = 200
