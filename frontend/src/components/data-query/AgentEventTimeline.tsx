import styles from "./data-query.module.css";

type Props = {
  /** 后端已做过安全映射的公开事件，前端只负责按顺序展示。 */
  events: string[];
};

/**
 * 执行过程时间线。
 *
 * 只渲染后端给的那几条公开事件。前端**不推断、不补全、不改写**执行步骤——
 * 一旦前端自己拼步骤，展示的就不再是系统真实做过的事，
 * 而是前端以为系统做过的事，排查问题时会把方向带偏。
 *
 * 事件文本已经过后端过滤，不含 SQL、表名字段名、重试次数或异常原文。
 */
export function AgentEventTimeline({ events }: Props) {
  if (events.length === 0) {
    return <p className={styles.hint}>本次没有可展示的执行步骤。</p>;
  }

  return (
    <ol className={styles.timeline}>
      {events.map((event, index) => (
        // 同一步骤可能出现两次（例如修复后再次校验），所以键里带上位置
        <li key={`${index}-${event}`} className={styles.timelineItem}>
          {event}
        </li>
      ))}
    </ol>
  );
}
