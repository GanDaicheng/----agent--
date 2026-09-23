import styles from "./WorkflowChain.module.css";

type Props = {
  title: string;
  steps: string[];
  /**
   * 标题的语义层级。
   *
   * 同一条链路在模块页里是页面的主要分节（h2），在首页里是某个分节下的内容（h3）。
   * 写死一种就会在另一处造成标题层级跳跃，所以交给调用方决定。
   */
  headingLevel?: "h2" | "h3";
};

/** 逐步展示一条已跑通的流程，用编号 + 箭头表达先后顺序。 */
export function WorkflowChain({ title, steps, headingLevel = "h2" }: Props) {
  const Heading = headingLevel;

  return (
    <section className={styles.wrapper}>
      <Heading className={styles.title}>{title}</Heading>

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
