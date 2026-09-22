import { MOCK_NOTICE } from "@/mocks/platform-overview";

import styles from "./DataSourceNote.module.css";

type Props = {
  /** 覆盖默认文案，用于说明该处数据的具体来源。 */
  label?: string;
  /** 说明这些数据将来会由谁提供。 */
  hint?: string;
};

/**
 * Mock 数据边界标记。
 *
 * 凡是渲染 src/mocks/ 里静态数据的位置都必须带上它，
 * 让阅读者一眼看出这不是真实运行数据。
 */
export function DataSourceNote({ label = MOCK_NOTICE, hint }: Props) {
  return (
    <p className={styles.note}>
      <span className={styles.tag}>静态数据</span>
      <span>{label}</span>
      {hint ? <span className={styles.hint}>{hint}</span> : null}
    </p>
  );
}
