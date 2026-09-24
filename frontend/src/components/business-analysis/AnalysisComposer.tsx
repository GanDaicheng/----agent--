import { useEffect, type KeyboardEvent, type RefObject } from "react";

import styles from "@/app/applications/business-analysis/business-analysis.module.css";

type Props = {
  value: string;
  phase: "idle" | "running" | "done" | "cancelled" | "failed";
  /** 由工作区持有：点示例之后要把光标放进输入框，组件内部也需要它来量高度。 */
  inputRef: RefObject<HTMLTextAreaElement | null>;
  onChange: (value: string) => void;
  onSend: () => void;
  onStop: () => void;
};

/** 底部输入区：输入框 + 右侧主操作，运行中主操作变成「停止生成」。 */
export function AnalysisComposer({
  value,
  phase,
  inputRef,
  onChange,
  onSend,
  onStop,
}: Props) {
  const running = phase === "running";
  const canSend = value.trim().length > 0 && !running;

  // 高度跟着内容长，但封顶交给 CSS 的 max-height——上限只写一处，
  // 超过之后由 textarea 自己出滚动条，不会把整个页面顶下去。
  useEffect(() => {
    const node = inputRef.current;
    if (!node) return;
    const border = node.offsetHeight - node.clientHeight;
    node.style.height = "auto";
    node.style.height = `${node.scrollHeight + border}px`;
  }, [inputRef, value]);

  function handleKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key !== "Enter" || event.shiftKey) return;
    // 输入法组合期间的回车是在确认候选词。放行它，否则中文选词会误发。
    if (event.nativeEvent.isComposing) return;
    event.preventDefault();
    if (canSend) onSend();
  }

  return (
    <form
      className={styles.composer}
      onSubmit={(event) => {
        event.preventDefault();
        if (canSend) onSend();
      }}
    >
      <textarea
        ref={inputRef}
        className={styles.composerInput}
        value={value}
        rows={2}
        aria-label="分析问题"
        placeholder="描述一个需要多步分析的经营问题，Enter 发送，Shift+Enter 换行"
        disabled={running}
        onChange={(event) => onChange(event.target.value)}
        onKeyDown={handleKeyDown}
      />
      {running ? (
        <button
          type="button"
          className={styles.stopButton}
          onClick={onStop}
          aria-label="停止生成"
        >
          停止生成
        </button>
      ) : (
        <button
          type="submit"
          className={styles.sendButton}
          disabled={!canSend}
          aria-label="发送问题"
        >
          发送
        </button>
      )}
    </form>
  );
}
