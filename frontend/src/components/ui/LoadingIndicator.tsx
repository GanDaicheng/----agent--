import { Button } from "./Button";
import styles from "./LoadingIndicator.module.css";

type Props = {
  /** 一句话说明正在发生什么。用「正在…」的不确定表述，不给完成度。 */
  message: string;
  /** 补充说明，例如「这个过程通常需要数秒」。 */
  note?: string;
  /** 有取消能力时才传。取消只代表前端不再等待，不代表服务端停止处理。 */
  onCancel?: () => void;
};

/**
 * 加载指示。
 *
 * **不确定进度就是不确定**：这里没有百分比、没有步骤打勾、没有「已切片 / 已向量化」这类
 * 节点推进。当前后端没有提供任何进度接口，画出来的进度一定是编的。
 * 用户需要的是「它还在动」和「我可以不等了」，这两件事一个转圈和一颗取消按钮就够了。
 */
export function LoadingIndicator({ message, note, onCancel }: Props) {
  return (
    <div className={styles.loading} role="status" aria-live="polite">
      <span className={styles.spinner} aria-hidden="true" />
      <div className={styles.body}>
        <p className={styles.message}>{message}</p>
        {note ? <p className={styles.note}>{note}</p> : null}
      </div>
      {onCancel ? (
        <Button variant="secondary" onClick={onCancel} className={styles.cancel}>
          取消
        </Button>
      ) : null}
    </div>
  );
}
