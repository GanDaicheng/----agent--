"""真实数据库冒烟验证：让 Agent 走完整流程去查真实的 PostgreSQL。

用法（在 backend/ 目录下执行）：

    python tests/smoke_agent_real_query.py

**故意不叫 test_*.py**，所以 pytest 不会收集它：默认测试套件不依赖数据库，
在任何机器上都能跑。这个脚本是「唯一一处」会真正连库的验证，
需要本地 PostgreSQL 已启动且样例数据已写入。

它验证的是整条真实链路：

    自然语言问题
    → （假分类器，不调 LLM）
    → （假 SQL 生成器，不调 LLM）
    → Agent 的 validate_sql
    → 数据中台 execute_safe_query（AST 校验 + 只读事务）
    → 真实 PostgreSQL
    → （假解释器，不调 LLM）
    → 真实图表建议（纯规则）

也就是说：**除了取数这一段是真的，模型调用全部被替身接管**，
所以本脚本不会调用任何真实 LLM。

同时它会在前后各统计一次 orders 的行数与净销售额，
证明整个过程没有对样例数据做出任何修改。
"""

import asyncio
import sys
from decimal import Decimal
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from sqlalchemy import text  # noqa: E402

from app.agent.data_query.graph import build_graph  # noqa: E402
from app.repositories.database import dispose_engine, get_engine  # noqa: E402
from tests.test_data_query_graph import (  # noqa: E402
    FakeChartSuggester,
    FakeClassifier,
    FakeResultExplainer,
    FakeSqlGenerator,
    FakeSqlRepairer,
)

QUESTION_TREND = "华东地区近六个月销售额趋势怎么样"
QUESTION_RANKING = "销售额最高的商品是哪些"

# 两条已知合规的 SQL。它们同时也是 /api/v1/data/query 里验证过的那两条，
# 因此结果可以直接和接口的返回对齐。
TREND_SQL = (
    "SELECT date_dim.month, SUM(orders.net_amount) AS sales_amount "
    "FROM orders "
    "JOIN date_dim ON orders.date_id = date_dim.date_id "
    "GROUP BY date_dim.month "
    "ORDER BY date_dim.month "
    "LIMIT 12"
)

RANKING_SQL = (
    "SELECT products.product_name, SUM(orders.net_amount) AS sales_amount "
    "FROM orders "
    "JOIN products ON orders.product_id = products.product_id "
    "GROUP BY products.product_name "
    # 注意这里写的是完整的聚合表达式，而不是 ORDER BY sales_amount。
    # Agent 自己的 validate_sql 要求每个字段都带表名，ORDER BY 里的输出别名
    # 会被它判成「未限定表名」而拒绝（数据服务那一层是允许别名的）。
    # 这是 Agent 校验器的一个既有误报，本任务按边界要求没有改它，
    # 详见汇报里的说明。
    "ORDER BY SUM(orders.net_amount) DESC "
    "LIMIT 10"
)

# 与 POST /api/v1/data/query 返回的已知结果对齐（数据没被改动过时必然一致）
EXPECTED_TREND_ROWS = 12
EXPECTED_TREND_FIRST = {"month": 1, "sales_amount": 140892.02}
EXPECTED_TREND_LAST = {"month": 12, "sales_amount": 375247.52}
EXPECTED_RANKING_ROWS = 10
EXPECTED_RANKING_TOP3 = [
    ("蓝牙降噪耳机", 397792.59),
    ("女士针织衫", 353353.7),
    ("不粘炒锅", 265241.85),
]

failures: list[str] = []


def check(condition: bool, description: str) -> None:
    print(f"  [{'通过' if condition else '不通过'}] {description}")
    if not condition:
        failures.append(description)


def build_real_graph(intent: str, sql: str):
    """生产接线 + 真实执行器；模型调用全部换成替身。"""
    return build_graph(
        classifier=FakeClassifier(intent=intent),
        sql_generator=FakeSqlGenerator(sql=sql),
        sql_repairer=FakeSqlRepairer(),
        result_explainer=FakeResultExplainer(answer="（替身结论，不会调用真实模型）"),
        chart_suggester=FakeChartSuggester(),
    )


async def orders_snapshot() -> tuple[int, Decimal]:
    engine = get_engine()
    async with engine.connect() as conn:
        count = await conn.scalar(text("SELECT count(*) FROM orders"))
        total = await conn.scalar(text("SELECT sum(net_amount) FROM orders"))
    return count, total


async def main() -> int:
    before_count, before_total = await orders_snapshot()
    print("=" * 62)
    print("Agent 真实数据查询冒烟验证")
    print("=" * 62)
    print(f"orders 基线：{before_count} 行，净销售额合计 {before_total}\n")

    # ---------------- 月度销售趋势 ----------------
    print("[1] 月度销售趋势")
    graph = build_real_graph("trend", TREND_SQL)
    trend = await graph.ainvoke({"question": QUESTION_TREND})
    trend_result = trend["query_result"]

    check(trend_result["source"] == "postgres", "来源标记为 postgres")
    check(
        trend_result["row_count"] == len(trend_result["rows"]) == EXPECTED_TREND_ROWS,
        f"返回 {trend_result['row_count']} 行（期望 {EXPECTED_TREND_ROWS}）",
    )
    check(trend_result["rows"][0] == EXPECTED_TREND_FIRST, f"首行与接口一致：{trend_result['rows'][0]}")
    check(trend_result["rows"][-1] == EXPECTED_TREND_LAST, f"末行与接口一致：{trend_result['rows'][-1]}")
    check("模拟" not in trend["answer"], "answer 里没有「模拟数据」说明")
    check(
        any("真实数据查询完成" in event for event in trend["events"]),
        "执行事件标明是真实数据查询",
    )
    print(f"       answer = {trend['answer']}")
    print(f"       chart  = {trend['chart_suggestion']['chart_type']}"
          f" x={trend['chart_suggestion']['x_field']} y={trend['chart_suggestion']['y_field']}\n")

    # ---------------- 商品销售排行 ----------------
    print("[2] 商品销售排行")
    graph = build_real_graph("ranking", RANKING_SQL)
    ranking = await graph.ainvoke({"question": QUESTION_RANKING})
    ranking_result = ranking["query_result"]

    check(ranking_result["source"] == "postgres", "来源标记为 postgres")
    check(
        ranking_result["row_count"] == len(ranking_result["rows"]) == EXPECTED_RANKING_ROWS,
        f"返回 {ranking_result['row_count']} 行（期望 {EXPECTED_RANKING_ROWS}）",
    )
    actual_top3 = [
        (row["product_name"], row["sales_amount"]) for row in ranking_result["rows"][:3]
    ]
    check(actual_top3 == EXPECTED_RANKING_TOP3, f"前三名与接口一致：{actual_top3}")
    check("模拟" not in ranking["answer"], "answer 里没有「模拟数据」说明")
    print(f"       chart  = {ranking['chart_suggestion']['chart_type']}"
          f" x={ranking['chart_suggestion']['x_field']}\n")

    # ---------------- 数据未被改动 ----------------
    after_count, after_total = await orders_snapshot()
    print("[3] 样例数据未被改动")
    check(after_count == before_count, f"orders 行数不变：{before_count} → {after_count}")
    check(after_total == before_total, f"净销售额不变：{before_total} → {after_total}")

    await dispose_engine()

    print("\n" + "=" * 62)
    if failures:
        print(f"冒烟验证失败：{len(failures)} 项未通过")
        for item in failures:
            print(f"  - {item}")
        return 1
    print("冒烟验证通过：Agent 已能读取真实 PostgreSQL 数据，且未改动任何数据。")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
