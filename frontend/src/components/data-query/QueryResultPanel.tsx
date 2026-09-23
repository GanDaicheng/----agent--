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
  // 后端老版本没有这个字段，缺席时按空数组处理（那一块就不渲染）
  const knowledgeSources = result.knowledge_sources ?? [];

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

      {/* 参考知识来源。紧跟在结论之后：它是「为什么这么解释」的依据。
          没有查知识库（或后端没返回这个字段）时整块不渲染，不留空框。 */}
      {knowledgeSources.length > 0 ? (
        <section className={styles.card} aria-labelledby="knowledge-heading">
          <h2 id="knowledge-heading" className={styles.cardTitle}>
            参考知识来源
          </h2>
          {/* 这条边界必须写在用户看得到的地方：数字来自查询结果，
              文档只解释口径与原因。不写清楚，用户会以为数字出自这些文档。 */}
          <p className={styles.cardCaption}>
            本次回答参考的业务文档小节。数据结论来自查询结果，这些资料只用于解释口径与可能的原因。
          </p>
          <ul className={styles.knowledgeList}>
            {knowledgeSources.map((source, index) => (
              <li
                key={`${source.source_file}-${source.section_title}-${index}`}
                className={styles.knowledgeItem}
              >
                <div className={styles.knowledgeHead}>
                  <span className={styles.knowledgeRank}>#{index + 1}</span>
                  <span className={styles.knowledgeSection}>{source.section_title}</span>
                  <span className={styles.knowledgeDoc}>{source.document_title}</span>
                  <span className={styles.knowledgeSimilarity}>
                    相似度 {source.similarity.toFixed(4)}
                  </span>
                </div>
                {source.preview ? (
                  <p className={styles.knowledgePreview} title="命中的文档原文（已截断）">
                    {source.preview}
                  </p>
                ) : null}
                <span className={styles.knowledgeFile}>{source.source_file}</span>
              </li>
            ))}
          </ul>
        </section>
      ) : null}

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
