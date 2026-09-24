import type { BusinessAnalysisEvent } from "@/lib/api/business-analysis";

import styles from "@/app/applications/business-analysis/business-analysis.module.css";

export function AnalysisEventTimeline({ events }: { events: BusinessAnalysisEvent[] }) {
  if (events.length === 0) return <p className={styles.muted}>提交问题后，这里会实时显示 Agent 的工具调用。</p>;
  return <ol className={styles.eventList}>{events.map((event, index) => <li key={`${event.type}-${index}`}><span className={styles.eventDot} data-type={event.type} /><div><strong>{event.type === "tool_started" || event.type === "tool_completed" ? event.tool : event.type === "status" ? event.label : event.type === "report_delta" ? "正在生成报告" : event.type === "run_completed" ? "分析完成" : event.type === "run_started" ? "任务已启动" : "任务异常"}</strong>{event.type === "tool_completed" && event.summary ? <small>{event.summary}</small> : null}</div></li>)}</ol>;
}
