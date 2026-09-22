"""智能问数 Agent 的 Graph 组装。

当前流程：

    START → intake → understand_question → discover_assets
                                                    │
                                        route_after_assets（条件边）
                                        ┌───────────┴───────────┐
                                  generate_sql               finish
                                        ↓
                                  validate_sql ←──────────┐
                                        │                 │
                              route_after_validation      │
                              （条件边）                   │
                    ┌───────────────────┼──────────┐      │
              校验通过              未通过且      未通过且  │
                    │              还有额度      额度用完  │
                    ↓                   │            │    │
              execute_query      repair_sql ─────────┼────┘
                    │                   │            │
                    ↓                   │            │
             explain_result             │            │
                    │                   │            │
                    ↓                   │            │
         suggest_visualization          │            │
                    │                   │            │
                    └───────────────────┴────────────┘
                                        ↓
                                      finish
                                        ↓
                                       END

**「SQL 校验通过」是进入 execute_query 的唯一入口**：整张图里只有
validate_sql 的条件边指向它，而那条边只在 passed == True 时才走。
换句话说，「先校验、再执行」不是靠节点自觉遵守的约定，而是**图的结构本身**——
想执行，就必须先过校验那一关，绕不过去。

**结果的加工是一条链，没有旁路**：execute_query → explain_result →
suggest_visualization → finish。用户最终看到的不是「返回了 N 行」这种
执行日志，而是「一段分析结论 + 一份前端可渲染的图表配置」。

最后三个节点里有三个用到了模型（understand_question / generate_sql /
repair_sql），两个纯本地（execute_query 是模拟数据，suggest_visualization
是规则引擎），一个纯本地且不注入也不能换（validate_sql）。
**不是每个 Agent 节点都需要 LLM** —— 见 visualization.py 的说明。

图里**唯一一条回边**是 repair_sql → validate_sql。它不会变成死循环，
因为 route_after_validation 要求 `retry_count < MAX_SQL_RETRY` 才会放行，
而 repair_sql 每次执行都会把 retry_count 加一 —— 最多绕一圈就必然从
finish 出去。除了这条，其余所有边都朝同一个方向（从 START 到 END）。

即便如此，仍然绑了 recursion_limit 兜底：循环的「可终止」是靠上面这套
推理保证的，而推理可能出错（比如以后有人改了计数逻辑）。recursion_limit
不依赖任何业务逻辑，是纯粹的步数硬上限 —— 万一推理失效，它保证进程
不会卡死，而是抛一个明确的 GraphRecursionError。

后续接真实节点时，按 constants.PLANNED_NODE_ORDER 的顺序补 add_node / add_edge。

本模块的 build_graph() 接受六个可选的替身参数：classifier、sql_generator、
sql_repairer、mock_executor、result_explainer、chart_suggester。不传时用
真实的——也就是说测试和生产走的是同一段接线代码，唯一的差别就是注入的
那几个参数。

本模块不直接导入 app.core.llm（那件事由 intent.py / sql_generation.py 负责），
也不导入数据库相关模块，不读 .env。
"""

from collections.abc import Callable
from functools import lru_cache, partial

from langgraph.graph import END, START, StateGraph

from app.agent.data_query.constants import (
    MAX_GRAPH_STEPS,
    MAX_SQL_RETRY,
    NODE_DISCOVER_ASSETS,
    NODE_EXECUTE_QUERY,
    NODE_EXPLAIN_RESULT,
    NODE_FINISH,
    NODE_GENERATE_SQL,
    NODE_INTAKE,
    NODE_REPAIR_SQL,
    NODE_SUGGEST_VISUALIZATION,
    NODE_UNDERSTAND_QUESTION,
    NODE_VALIDATE_SQL,
)
from app.agent.data_query.intent import IntentClassification, classify_intent
from app.agent.data_query.mock_query import execute_mock_query
from app.agent.data_query.nodes import (
    discover_assets,
    execute_query,
    explain_result,
    finish,
    generate_sql,
    intake,
    repair_sql,
    suggest_visualization,
    understand_question,
    validate_sql,
)
from app.agent.data_query.result_explanation import (
    ResultExplanation,
    explain_query_result,
)
from app.agent.data_query.sql_generation import (
    SqlDraft,
    generate_sql_draft,
    repair_sql_draft,
)
from app.agent.data_query.state import ChartSuggestion, DataQueryState, QueryResult
from app.agent.data_query.visualization import suggest_chart


def route_after_assets(state: DataQueryState) -> str:
    """条件边的路由函数：只看 State，返回下一个要走的节点名。

    这是个**纯函数**，不碰模型、不碰数据库、没有副作用。
    好处是它可以脱离 Graph 单独测试——传一个 dict 进去，断言返回的字符串，
    比搭一整个图再观察走到了哪个节点快得多，也准得多。

    四个判断条件，命中任意一条就直奔 finish：

    - 已有 error      上游失败了，没必要再花钱生成 SQL
    - intent 是 unknown 问题根本不是问数问题，生成 SQL 没有意义
    - 没有匹配资产     是问数问题，但目录里找不到可用的表和指标，
                      模型拿不到任何「可用资产」清单，硬生成必然编造表名
    - 其余情况         正常问数，交给 generate_sql

    注意最后一条是「默认放行」而不是「显式匹配某个 intent」：
    将来新增意图时，只要它没被显式排除，就会自动走生成流程，
    不会因为忘了改这里而被悄悄跳过。
    """
    if state.get("error"):
        return NODE_FINISH
    if state.get("intent") == "unknown":
        return NODE_FINISH
    if not state.get("matched_assets"):
        return NODE_FINISH
    return NODE_GENERATE_SQL


def route_after_validation(state: DataQueryState) -> str:
    """校验之后的分流：是去修复，还是收尾。

    和 route_after_assets 一样是纯函数，可以脱离 Graph 单测。

    判断顺序：
      1. 已有 error        → finish（上游真失败了，修复也没有意义）
      2. 没有校验结果      → finish（没东西可判断，不冒险往下走）
      3. 校验通过          → execute_query（**进入执行阶段的唯一入口**）
      4. 没过且还有额度    → repair_sql（唯一一条回边，回到 validate_sql）
      5. 没过且额度用完    → finish（终态）

    第 3 条是本次改动最要紧的一行：校验通过的出口从 finish 换成了 execute_query。
    这意味着**「校验通过」是执行阶段唯一的入场券**——没有任何别的边指向
    execute_query，想执行就必须先过 validate_sql 这一关。
    把这条规则放在路由里，而不是靠在 execute_query 节点里自查，
    是因为图的结构本身就能被测试断言（见 test_validation_node_branches_conditionally），
    而节点内部的自查只能靠单测覆盖。

    第 4、5 条合起来就是「最多修一次」的全部实现——它不靠节点自觉，
    而是靠路由在这里把住门。repair_sql 内部虽然也有一道同样的检查
    （见 nodes.py），但那是纵深防御，真正的闸门在这里。

    这个函数**不写 error**：校验失败是可修复的中间状态，写 error 会让
    repair_sql 自己的熔断守卫（if state.get("error"): return {}）把它挡在门外，
    唯一的修复机会就此丢掉。
    """
    if state.get("error"):
        return NODE_FINISH

    validation = state.get("sql_validation")
    if not validation:
        return NODE_FINISH

    if validation.get("passed"):
        return NODE_EXECUTE_QUERY

    if (state.get("retry_count") or 0) < MAX_SQL_RETRY:
        return NODE_REPAIR_SQL

    return NODE_FINISH


def build_graph(
    classifier: Callable[[str], IntentClassification] = classify_intent,
    sql_generator: Callable[[str, str, list], SqlDraft] = generate_sql_draft,
    sql_repairer: Callable[[str, str, list, str, list], SqlDraft] = repair_sql_draft,
    mock_executor: Callable[..., QueryResult] = execute_mock_query,
    result_explainer: Callable[..., ResultExplanation] = explain_query_result,
    chart_suggester: Callable[..., ChartSuggestion] = suggest_chart,
):
    """组装并编译 Graph。每次调用都返回独立的新实例，测试里可以随便建。

    六个参数缺省都是真实实现；测试传入替身即可完全不碰网络。

    注意最后那个 chart_suggester：它注入的是个**纯函数**，不是模型调用。
    保留这个注入点的理由是测试——要构造「建议器抛异常」这种场景，
    只能靠替换实现。
    """
    builder = StateGraph(DataQueryState)

    # 注册节点：名字（给图看，出现在报错和可视化里）+ 函数（真正执行的逻辑）
    builder.add_node(NODE_INTAKE, intake)
    # 用 partial 把依赖预先绑定进去，得到一个只吃 state 的节点函数。
    # 节点参数里因此不会出现 config 之类的名字，LangGraph 会按普通单参节点调用它。
    builder.add_node(
        NODE_UNDERSTAND_QUESTION,
        partial(understand_question, classifier=classifier),
    )
    builder.add_node(NODE_DISCOVER_ASSETS, discover_assets)
    builder.add_node(
        NODE_GENERATE_SQL,
        partial(generate_sql, sql_generator=sql_generator),
    )
    builder.add_node(NODE_VALIDATE_SQL, validate_sql)
    builder.add_node(
        NODE_REPAIR_SQL,
        partial(repair_sql, sql_repairer=sql_repairer),
    )
    builder.add_node(
        NODE_EXECUTE_QUERY,
        partial(execute_query, mock_executor=mock_executor),
    )
    builder.add_node(
        NODE_EXPLAIN_RESULT,
        partial(explain_result, result_explainer=result_explainer),
    )
    builder.add_node(
        NODE_SUGGEST_VISUALIZATION,
        partial(suggest_visualization, chart_suggester=chart_suggester),
    )
    builder.add_node(NODE_FINISH, finish)

    # 直线段：每步只有一个确定的下一站
    builder.add_edge(START, NODE_INTAKE)
    builder.add_edge(NODE_INTAKE, NODE_UNDERSTAND_QUESTION)
    builder.add_edge(NODE_UNDERSTAND_QUESTION, NODE_DISCOVER_ASSETS)
    builder.add_edge(NODE_GENERATE_SQL, NODE_VALIDATE_SQL)
    # 执行完必然去解读，解读完必然给图表建议，然后收尾。
    # 这三步都不分叉，所以全用普通边。
    #
    # 注意 execute_query **不再直接连 finish**：结果必须先经过解释节点，
    # 才能变成给用户看的结论。少接这一跳，用户看到的就还是「返回了 N 行」
    # 这种执行日志，而不是分析结论。
    #
    # 同理，explain_result 也不再直接连 finish：结论之外还要带上
    # 前端渲染所需的图表配置，两样齐了才算一次完整的问答。
    builder.add_edge(NODE_EXECUTE_QUERY, NODE_EXPLAIN_RESULT)
    builder.add_edge(NODE_EXPLAIN_RESULT, NODE_SUGGEST_VISUALIZATION)
    builder.add_edge(NODE_SUGGEST_VISUALIZATION, NODE_FINISH)
    builder.add_edge(NODE_FINISH, END)

    # 唯一的一条回边。注意它是普通的 add_edge，不带走什么条件：
    # 「该不该回来」由 repair_sql 上游的 route_after_validation 决定，
    # 一旦进了 repair_sql，就必然重新校验一次 —— 修完必须复检，
    # 没有「修完直接放行」这种捷径。
    builder.add_edge(NODE_REPAIR_SQL, NODE_VALIDATE_SQL)

    # 条件边：discover_assets 之后要分叉，靠 route_after_assets 现场决定。
    # 第三个参数是「路由函数可能返回哪些值 → 各对应哪个节点」的映射表，
    # 必须把路由函数所有可能返回的名字都列全——
    # 漏一个的话，运行时一旦返回那个值，LangGraph 会直接报错。
    builder.add_conditional_edges(
        NODE_DISCOVER_ASSETS,
        route_after_assets,
        {
            NODE_GENERATE_SQL: NODE_GENERATE_SQL,
            NODE_FINISH: NODE_FINISH,
        },
    )

    # 校验之后同样分叉：通过就去做模拟查询，没过且还有额度就回去修。
    # 这里必须用条件边而不是普通边——如果写成 add_edge(VALIDATE_SQL, FINISH)，
    # 修复这条路就彻底没了；写成 add_edge(VALIDATE_SQL, EXECUTE_QUERY)，
    # 又会变成「不管校验结果如何都去执行」，那才是真正危险的接线错误。
    builder.add_conditional_edges(
        NODE_VALIDATE_SQL,
        route_after_validation,
        {
            NODE_EXECUTE_QUERY: NODE_EXECUTE_QUERY,
            NODE_REPAIR_SQL: NODE_REPAIR_SQL,
            NODE_FINISH: NODE_FINISH,
        },
    )

    # compile() 把「节点 + 边」的声明校验并固化成可执行对象。
    # 没写过 compile() 的 builder 只是一份图纸，不能 invoke。
    compiled = builder.compile()

    # 把步数上限绑到编译产物上。with_config 返回的是一份带默认 config 的新对象，
    # 不修改原来的图；之后无论谁调用，哪怕不传 config，这个上限都生效。
    # 这样「忘记设上限」就不可能发生了——它是接线的一部分，不是调用方的义务。
    return compiled.with_config({"recursion_limit": MAX_GRAPH_STEPS})


@lru_cache(maxsize=1)
def get_data_query_graph():
    """进程内共用同一份编译结果。

    编译有固定开销，而编译产物本身是无状态的（状态在每次 invoke 时传入），
    所以运行时没必要每次请求都重新编译一遍。lru_cache 保证只编译一次。
    测试想拿到全新实例时直接调 build_graph()，不受缓存影响。

    注意这里**不能**传替身：这是生产入口，用的必须是真实的
    classifier、sql_generator、sql_repairer、mock_executor、
    result_explainer 和 chart_suggester。
    """
    return build_graph()
