import styles from "@/app/applications/business-analysis/business-analysis.module.css";

export function AnalysisReportPanel({ report }: { report: string }) {
  return <section className={styles.reportPanel}><div className={styles.reportHeader}><span>经营分析报告</span><span className={styles.reportBadge}>数据证据驱动</span></div><pre className={styles.reportText}>{report}</pre></section>;
}
