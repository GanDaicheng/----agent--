import type { ReactNode } from "react";

import styles from "./EmptyState.module.css";

type Props = {
  title: string;
  /** 补充说明：告诉用户「现在能做什么」，而不是只说「没有数据」。 */
  children?: ReactNode;
  /** 可选的下一步动作，例如「前往知识问答」。 */
  action?: ReactNode;
};

/**
 * 空态。
 *
 * 空态不是错误态：它表示「这里确实什么都没有」，而且通常有下一步可走。
 * 所以它刻意长得比 Notice 安静——虚线框、灰字，不抢注意力。
 */
export function EmptyState({ title, children, action }: Props) {
  return (
    <div className={styles.empty}>
      <p className={styles.title}>{title}</p>
      {children ? <div className={styles.text}>{children}</div> : null}
      {action ? <div className={styles.action}>{action}</div> : null}
    </div>
  );
}
