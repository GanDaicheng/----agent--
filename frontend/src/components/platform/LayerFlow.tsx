import Link from "next/link";

import { PLATFORM_SECTIONS } from "@/features/platform/platform-config";
import { SOURCE_NODE } from "@/mocks/platform-overview";

import { StatusBadge } from "./StatusBadge";
import styles from "./LayerFlow.module.css";

/**
 * 分层能力链路：业务系统 → 业务中台 → 数据中台 → AI 中台 → 智能应用。
 *
 * 这是全站唯一的强视觉元素，只出现在总览页。
 * 层级名称、职责与状态全部取自 platform-config，改配置即可同步。
 */
export function LayerFlow() {
  const lastIndex = PLATFORM_SECTIONS.length - 1;

  return (
    <ol className={styles.flow}>
      <li className={styles.step}>
        <div className={styles.card} data-tone="source">
          <div className={styles.head}>
            <h3 className={styles.name}>{SOURCE_NODE.name}</h3>
            <span className={styles.sourceTag}>数据来源</span>
          </div>
          <p className={styles.duty}>{SOURCE_NODE.duty}</p>
        </div>
        <span className={styles.arrow} aria-hidden="true" />
      </li>

      {PLATFORM_SECTIONS.map((section, index) => (
        <li key={section.id} className={styles.step}>
          <Link
            href={section.entry}
            className={styles.card}
            data-tone={section.id}
          >
            <div className={styles.head}>
              <h3 className={styles.name}>{section.name}</h3>
              <StatusBadge status={section.status} size="sm" />
            </div>
            <p className={styles.duty}>{section.duty}</p>
            <span className={styles.entry}>{section.entryLabel} →</span>
          </Link>
          {index < lastIndex ? (
            <span className={styles.arrow} aria-hidden="true" />
          ) : null}
        </li>
      ))}
    </ol>
  );
}
