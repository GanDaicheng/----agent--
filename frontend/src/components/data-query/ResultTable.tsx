import type { QueryResult, ValueFormat } from "@/lib/api/agent-data-query";

import { formatValue } from "./format";
import styles from "./data-query.module.css";

type Props = {
  result: QueryResult;
  /**
   * 度量字段（图表建议里的 y_field）。
   * 只有这一列按 value_format 格式化——把「金额格式」套到月份列上，
   * 会渲染出「¥1.00」这种荒唐的单元格。
   */
  valueField: string | null;
  valueFormat: ValueFormat | null;
};

/**
 * 查询结果明细表。
 *
 * 表格永远渲染后端给的行，不排序、不聚合、不改数——它就是「模型看到了什么」的底稿。
 * 单元格一律按纯文本渲染，因此结果里就算混进 <script> 也只会原样显示成字符。
 */
export function ResultTable({ result, valueField, valueFormat }: Props) {
  const { columns, rows, row_count, source } = result;

  return (
    <div>
      <div className={styles.tableMeta}>
        <span>返回 {row_count} 行</span>
        <span className={styles.sourceTag} data-source={source}>
          {source === "mock" ? "模拟数据" : "数据来源：PostgreSQL 样例数据"}
        </span>
      </div>

      {rows.length === 0 ? (
        <p className={styles.hint}>查询已执行，但没有匹配的数据。</p>
      ) : (
        <div className={styles.tableWrap}>
          <table className={styles.table}>
            <thead>
              <tr>
                {columns.map((column) => (
                  <th key={column} scope="col">
                    {column}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((row, rowIndex) => (
                // 结果行没有稳定主键，用位置作键；表格不排序，位置就是稳定的
                <tr key={rowIndex}>
                  {columns.map((column) => (
                    <td
                      key={column}
                      className={
                        column === valueField ? styles.numeric : undefined
                      }
                    >
                      {formatValue(
                        row[column],
                        column === valueField ? valueFormat : null,
                      )}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
