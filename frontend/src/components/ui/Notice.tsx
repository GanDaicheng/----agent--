import type { ReactNode } from "react";

import styles from "./Notice.module.css";

/**
 * 提示的语义。
 *
 * 五档刻意分开，是因为这个项目里最容易被混淆的两件事就是
 * 「系统坏了」和「系统诚实地告诉你它答不出来」：
 * - danger  服务故障、请求失败 —— 需要重试或排查；
 * - warning 用户能自己修的问题（文件格式不对、资料不足）—— 不是故障；
 * - info    中性说明；
 * - success 操作完成；
 * - neutral 用户主动取消、或「本次没有结果」这类既非成功也非失败的结果。
 */
export type NoticeTone = "info" | "success" | "warning" | "danger" | "neutral";

type Props = {
  tone: NoticeTone;
  /** 左侧的短标签。每个提示都必须有文字标签，不能只靠颜色表达语义。 */
  tag: string;
  /** role="alert" 用于需要立刻打断用户的失败；一般状态用 "status"。 */
  role?: "status" | "alert";
  /** 需要被读屏软件在出现时朗读的内容。 */
  children: ReactNode;
};

export function Notice({ tone, tag, role = "status", children }: Props) {
  return (
    <div className={styles.notice} data-tone={tone} role={role}>
      <span className={styles.tag}>{tag}</span>
      <div className={styles.body}>{children}</div>
    </div>
  );
}
