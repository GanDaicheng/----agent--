import styles from "./page.module.css";

const MODULES = [
  {
    name: "智能问数",
    desc: "用自然语言提问，自动检索指标口径、生成安全 SQL，并给出结论与图表。",
  },
  {
    name: "指标中心",
    desc: "统一管理指标定义、计算口径与可用维度，让「销售额」这类说法处处含义一致。",
  },
  {
    name: "数据目录",
    desc: "汇总可查询的表、字段与血缘关系，让 Agent 清楚有哪些数据、应该怎么用。",
  },
];

export default function Home() {
  return (
    <main className={styles.main}>
      <header className={styles.header}>
        <h1 className={styles.title}>数据中台 Agent</h1>
        <p className={styles.subtitle}>
          面向业务人员的智能问数与数据分析工作台
        </p>
      </header>

      <p className={styles.notice}>
        当前仅完成前端工程初始化，问数、指标与目录能力均在规划中。
      </p>

      <section className={styles.grid}>
        {MODULES.map((module) => (
          <article key={module.name} className={styles.card}>
            <span className={styles.badge}>规划中</span>
            <h2 className={styles.cardTitle}>{module.name}</h2>
            <p className={styles.cardDesc}>{module.desc}</p>
          </article>
        ))}
      </section>

      <footer className={styles.footer}>
        后端 FastAPI + LangGraph · 数据库 PostgreSQL 16 · 前端 Next.js +
        TypeScript
      </footer>
    </main>
  );
}
