import styles from "./WorkflowChain.module.css";

type Props = {
  title: string;
  steps: string[];
};

/** 逐步展示一条已跑通的流程，用编号 + 箭头表达先后顺序。 */
export function WorkflowChain({ title, steps }: Props) {
  return (
    <section className={styles.wrapper}>
      <h2 className={styles.title}>{title}</h2>

      <ol className={styles.list}>
        {steps.map((step, index) => (
          <li key={step} className={styles.step}>
            <span className={styles.index} aria-hidden="true">
              {index + 1}
            </span>
            <span className={styles.name}>{step}</span>
            {index < steps.length - 1 ? (
              <span className={styles.arrow} aria-hidden="true" />
            ) : null}
          </li>
        ))}
      </ol>
    </section>
  );
}
