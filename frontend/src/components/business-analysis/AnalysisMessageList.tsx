import type { RefObject } from "react";

import type { ChatMessage } from "@/app/applications/business-analysis/business-analysis-view-model";
import styles from "@/app/applications/business-analysis/business-analysis.module.css";

import { AnalysisMarkdown } from "./AnalysisMarkdown";

type Props = {
  messages: ChatMessage[];
  /**
   * 列表末尾的锚点。滚动由工作区负责：只有它知道这次变化是「刚发出问题」
   * 还是「又流进来一个 token」，两者该用不同的滚动方式。
   */
  bottomRef: RefObject<HTMLDivElement | null>;
};

/**
 * 运行中的动态状态。
 *
 * 只在流式阶段挂 `aria-live`：这几句会连续替换，读屏该念的是「最新那句」；
 * 错误和停止是终态文案，渲染出来即可，再播报一次反而吵。
 */
function StatusLine({ message }: { message: ChatMessage }) {
  if (!message.statusText) return null;
  const streaming = message.status === "streaming";
  return (
    <p
      className={styles.statusLine}
      data-status={message.status}
      aria-live={streaming ? "polite" : undefined}
    >
      {streaming ? <span className={styles.statusDot} aria-hidden="true" /> : null}
      {message.statusText}
    </p>
  );
}

export function AnalysisMessageList({ messages, bottomRef }: Props) {
  return (
    <div className={styles.messageList}>
      {messages.map((message) =>
        message.role === "user" ? (
          <div className={styles.userMessage} key={message.id}>
            <p className={styles.userBubble}>{message.content}</p>
          </div>
        ) : (
          <article
            className={styles.assistantMessage}
            key={message.id}
            data-status={message.status}
          >
            <p className={styles.assistantRole}>Agent</p>
            <StatusLine message={message} />
            {message.content ? <AnalysisMarkdown content={message.content} /> : null}
          </article>
        ),
      )}
      <div ref={bottomRef} />
    </div>
  );
}
