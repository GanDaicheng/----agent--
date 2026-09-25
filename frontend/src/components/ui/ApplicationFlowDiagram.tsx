import styles from "./ApplicationFlowDiagram.module.css";

type FlowVariant = "rag" | "data-query";

type Props = {
  variant: FlowVariant;
};

const flowCopy = {
  rag: {
    eyebrow: "RAG执行链路",
    title: "从问题到带来源回答",
    description: "先检索证据，再基于证据回答，避免把模型记忆当成业务口径。",
    steps: [
      ["01", "用户问题", "业务口径 / 规则"],
      ["02", "问题改写", "query expansion"],
      ["03", "混合召回", "向量 + 关键词"],
      ["04", "RRF + Rerank", "qwen3-rerank"],
      ["05", "带来源回答", "答案 + 证据"],
    ],
    footer: "Word/PDF → Markdown chunks → text-embedding-v4 → PostgreSQL + pgvector",
  },
  "data-query": {
    eyebrow: "Agent执行链路",
    title: "从自然语言到安全查询",
    description: "Agent 用 RAG 补充指标口径，再经过 AST 校验和只读查询形成闭环。",
    steps: [
      ["01", "自然语言问题", "趋势 / 排行 / 对比"],
      ["02", "意图与资产发现", "指标、表、字段"],
      ["03", "RAG补充口径", "指标定义 / 规则"],
      ["04", "SQL生成", "LangChain tool"],
      ["05", "AST校验 + 查询", "sqlglot + PostgreSQL"],
    ],
    footer: "校验失败 → 一次自动修复 → 结果解释 → 表格 + 图表建议",
  },
} as const;

export function ApplicationFlowDiagram({ variant }: Props) {
  const copy = flowCopy[variant];

  return (
    <section className={styles.card} aria-labelledby={`${variant}-flow-title`}>
      <div className={styles.heading}>
        <div>
          <p className={styles.eyebrow}>{copy.eyebrow}</p>
          <h2 id={`${variant}-flow-title`} className={styles.title}>{copy.title}</h2>
          <p className={styles.description}>{copy.description}</p>
        </div>
        <span className={styles.badge}>可追溯流程</span>
      </div>

      <div className={styles.flow} role="list" aria-label={copy.title}>
        {copy.steps.map(([number, label, detail], index) => (
          <div className={styles.step} role="listitem" key={number}>
            <div className={styles.stepTop}>
              <span className={styles.number}>{number}</span>
              {index < copy.steps.length - 1 ? <span className={styles.connector} aria-hidden="true" /> : null}
            </div>
            <strong>{label}</strong>
            <span>{detail}</span>
          </div>
        ))}
      </div>

      <p className={styles.footer}><span aria-hidden="true">↳</span> {copy.footer}</p>
    </section>
  );
}
