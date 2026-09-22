import type { AgentDataQueryResponse } from "@/lib/api/agent-data-query";

import { AgentEventTimeline } from "./AgentEventTimeline";
import { ResultChart } from "./ResultChart";
import { ResultTable } from "./ResultTable";
import styles from "./data-query.module.css";

type Props = {
  result: AgentDataQueryResponse;
};

/**
 * 结果区。
 *
 * 两种形态泾渭分明：
 * - status === "error"：只展示受控的错误说明和执行过程，**不展示结果与图表**。
 *   出错时 State 里可能残留上一次的中间产物，展示出来就是误导。
 * - status === "ok"：结论、过程、图表、明细依次排开。没有查询结果也是正常结果
 *   （例如问题不属于问数范畴），照实说明即可，不当成故障。
 */
export function QueryResultPanel({ result }: Props) {
  if (result.status === "error") {
    return (
      <section className={styles.card} aria-labelledby="result-error-heading">
        <h2 id="result-error-heading" className={styles.cardTitle}>
          本次分析未完成
        </h2>
        <p className={styles.cardCaption}>
          Agent 返回了受控的失败说明，因此没有查询结果，也没有图表建议。
        </p>
        <p className={`${styles.answer} ${styles.answerError}`}>{result.answer}</p>

        <h3 className={styles.cardTitle} style={{ marginTop: 20 }}>
          分析过程
        </h3>
        <AgentEventTimeline events={result.events} />
      </section>
    );
  }

  const queryResult = result.query_result;
  const suggestion = result.chart_suggestion;
  // 度量字段与它的展示格式都来自图表建议；表格只对这一列套格式
  const valueField = suggestion?.y_field ?? null;
  const valueFormat = suggestion?.value_format ?? null;

  return (
    <div className={styles.page}>
      <section className={styles.card} aria-labelledby="answer-heading">
        <h2 id="answer-heading" className={styles.cardTitle}>
          Agent 分析结论
        </h2>
        <p className={styles.cardCaption}>
          以下结论由模型根据查询结果生成，只复述结果里已有的事实。
        </p>
        {/* 纯文本渲染：保留换行，但绝不按 HTML / Markdown 执行 */}
        <p className={styles.answer}>{result.answer}</p>
      </section>

      <section className={styles.card} aria-labelledby="events-heading">
        <h2 id="events-heading" className={styles.cardTitle}>
          分析过程
        </h2>
        <p className={styles.cardCaption}>
          由后端返回的公开步骤，前端不做推断或补充。
        </p>
        <AgentEventTimeline events={result.events} />
      </section>

      {queryResult ? (
        <>
          <section className={styles.card} aria-labelledby="chart-heading">
            <h2 id="chart-heading" className={styles.cardTitle}>
              图表建议
            </h2>
            <ResultChart result={queryResult} suggestion={suggestion} />
          </section>

          <section className={styles.card} aria-labelledby="table-heading">
            <h2 id="table-heading" className={styles.cardTitle}>
              查询结果
            </h2>
            <ResultTable
              result={queryResult}
              valueField={valueField}
              valueFormat={valueFormat}
            />
          </section>
        </>
      ) : (
        <p className={styles.notice} data-tone="empty">
          <span className={styles.noticeTag}>无结果</span>
          本次没有返回查询结果。这通常意味着问题不属于数据分析范畴，
          或者没有匹配到可用的数据资产——两种情况都不是系统故障。
        </p>
      )}
    </div>
  );
}
