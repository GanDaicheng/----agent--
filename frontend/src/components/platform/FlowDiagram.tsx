import styles from "./FlowDiagram.module.css";

export type FlowNodeSpec = {
  label: string;
  /** 节点下方的小字说明，可选。 */
  hint?: string;
};

/**
 * 一个步骤。nodes 只有一个时是普通节点，多个时是一排并列节点（分支）。
 */
export type FlowStepSpec = {
  nodes: FlowNodeSpec[];
  /** 并列节点上方的一句说明，例如「两条检索路径」。 */
  caption?: string;
};

type Props = {
  title: string;
  steps: FlowStepSpec[];
  /**
   * 深色面板。用于架构页的主流程，作为整页的视觉重点。
   * 站点整体仍是浅色，只有这一块是深的。
   */
  tone?: "light" | "dark";
};

/**
 * 竖向流程图：节点自上而下，之间用竖线和箭头连接。
 *
 * 为什么不用横向的 WorkflowChain？那是给首页「一眼扫过」用的紧凑药丸；
 * 这里每一步带一句说明、还可能分支，需要更大的画布。两者服务不同场景，
 * 不是为了统一而硬凑成一个组件。
 *
 * 纯 HTML + CSS，没有 SVG 坐标、没有动画、没有依赖。
 * 语义上就是一个有序列表——读屏软件会按顺序念出每一步。
 */
export function FlowDiagram({ title, steps, tone = "light" }: Props) {
  return (
    <section className={styles.flow} data-tone={tone}>
      <h3 className={styles.title}>{title}</h3>

      <ol className={styles.steps}>
        {steps.map((step, index) => {
          const parallel = step.nodes.length > 1;
          // 键用位置 + 首节点名：同一张图里步骤不会重名，但分支可能同名
          const key = `${index}-${step.nodes[0]?.label ?? ""}`;

          return (
            <li key={key} className={styles.step}>
              {step.caption ? (
                <p className={styles.stepCaption}>{step.caption}</p>
              ) : null}

              <div className={styles.nodeRow} data-parallel={parallel}>
                {step.nodes.map((node) => (
                  <div key={node.label} className={styles.node}>
                    <span className={styles.nodeLabel}>{node.label}</span>
                    {node.hint ? (
                      <span className={styles.nodeHint}>{node.hint}</span>
                    ) : null}
                  </div>
                ))}
              </div>

              {index < steps.length - 1 ? (
                <span className={styles.arrow} aria-hidden="true" />
              ) : null}
            </li>
          );
        })}
      </ol>
    </section>
  );
}
