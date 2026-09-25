import Link from "next/link";

import type { ApplicationEntry } from "@/features/platform/overview-config";

import styles from "./ApplicationCapabilityCard.module.css";

type Props = {
  entry: ApplicationEntry;
};

/**
 * 一个可交互业务入口的卡片。
 *
 * 整张卡可点（跳转真实页面），CTA 只是视觉提示而不是第二个链接——
 * 一张卡里放两个指向同一处的链接，读屏时会念两遍。
 *
 * 信息按「为什么需要它 → 吃什么 → 怎么处理 → 吐出什么」排列：
 * 面试官扫一眼就知道这个功能在链路里的位置，不用先读实现细节。
 */
export function ApplicationCapabilityCard({ entry }: Props) {
  return (
    <li className={styles.item}>
      <Link
        href={entry.href}
        className={styles.card}
        aria-label={`进入${entry.name}`}
      >
        <h3 className={styles.name}>{entry.name}</h3>
        <p className={styles.problem}>{entry.problem}</p>

        <dl className={styles.facts}>
          <div className={styles.fact}>
            <dt className={styles.factLabel}>输入</dt>
            <dd className={styles.factValue}>{entry.input}</dd>
          </div>
          <div className={styles.fact}>
            <dt className={styles.factLabel}>输出</dt>
            <dd className={styles.factValue}>{entry.output}</dd>
          </div>
        </dl>

        <div className={styles.process}>
          <p className={styles.processLabel} id={`${entry.id}-process`}>
            核心处理过程
          </p>
          <ol className={styles.steps} aria-labelledby={`${entry.id}-process`}>
            {entry.process.map((step) => (
              <li key={step}>{step}</li>
            ))}
          </ol>
        </div>

        <span className={styles.action}>
          进入 {entry.name}
          <span aria-hidden="true"> →</span>
        </span>
      </Link>
    </li>
  );
}
