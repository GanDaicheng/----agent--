import type { ReactNode } from "react";

import styles from "@/app/applications/business-analysis/business-analysis.module.css";

type Thread = { id: string; title: string; updatedAt: string };

type Props = {
  threads: Thread[];
  activeId: string;
  onNew: () => void;
  onSelect: (thread: Thread) => void;
  footer?: ReactNode;
};

export function AnalysisThreadList({ threads, activeId, onNew, onSelect, footer }: Props) {
  return (
    <aside className={styles.threadColumn}>
      <div className={styles.threadHeader}><span>分析会话</span><button type="button" onClick={onNew}>＋ 新建</button></div>
      {threads.length === 0 ? <p className={styles.muted}>完成一次分析后，会话会显示在这里。</p> : (
        <ul className={styles.threadList}>
          {threads.map((thread) => <li key={thread.id}><button type="button" className={thread.id === activeId ? styles.activeThread : styles.thread} onClick={() => onSelect(thread)}><span>{thread.title}</span><small>{thread.updatedAt}</small></button></li>)}
        </ul>
      )}
      {footer}
    </aside>
  );
}
