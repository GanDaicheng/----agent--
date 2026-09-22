import styles from "./data-query.module.css";

type Props = {
  onCancel: () => void;
};

/**
 * 加载状态。
 *
 * 三个步骤只是说明「这期间系统在做什么」，**不标记任何一步已完成**：
 * 前端拿不到 Agent 的真实进度，标了就一定是编的。
 * 同理不画百分比进度条——进度不可预知，画出来只会误导。
 */
export function QueryLoadingState({ onCancel }: Props) {
  return (
    <section
      className={`${styles.card} ${styles.loadingCard}`}
      aria-labelledby="loading-heading"
      role="status"
      aria-live="polite"
    >
      <p className={styles.loadingHead} id="loading-heading">
        <span className={styles.spinner} aria-hidden="true" />
        正在处理，请稍候…
      </p>

      <ol className={styles.loadingSteps}>
        <li>正在提交问题</li>
        <li>正在由 Agent 分析数据</li>
        <li>正在等待分析结果</li>
      </ol>

      <p className={styles.loadingNote}>
        真实查询需要调用模型并读取数据库，通常需要数秒到十几秒。
        这里不显示百分比——进度无法准确预知。
      </p>

      <div className={styles.actions}>
        <button
          type="button"
          className={`${styles.button} ${styles.secondary}`}
          onClick={onCancel}
        >
          取消本次请求
        </button>
      </div>
    </section>
  );
}
