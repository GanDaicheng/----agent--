import {
  INTERVIEW_HIGHLIGHTS,
  OVERVIEW_VALUE_PROPS,
} from "@/features/platform/overview-config";

import styles from "./InterviewHighlights.module.css";

/**
 * 面试视角：这个项目解决了什么问题，以及值得展开讲的几处实现。
 *
 * 分成两段是因为它们回答的是两个不同的问题——
 * 上面三句是「对业务有什么用」，下面七条是「技术上的难点在哪」。
 * 混成一段会让两者都变模糊。
 */
export function InterviewHighlights() {
  return (
    <div className={styles.wrapper}>
      <h3 className={styles.subTitle}>这个项目重点解决了什么问题</h3>

      <ul className={styles.valueList}>
        {OVERVIEW_VALUE_PROPS.map((item) => (
          <li key={item.id} className={styles.valueCard}>
            <p className={styles.valueTitle}>{item.title}</p>
            <p className={styles.valueDetail}>{item.detail}</p>
          </li>
        ))}
      </ul>

      <h3 className={styles.subTitle}>项目亮点</h3>

      <ul className={styles.highlightList}>
        {INTERVIEW_HIGHLIGHTS.map((item) => (
          <li key={item.id} className={styles.highlightCard}>
            <p className={styles.highlightTitle}>{item.title}</p>
            <p className={styles.highlightDetail}>{item.detail}</p>
          </li>
        ))}
      </ul>
    </div>
  );
}
