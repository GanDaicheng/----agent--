"use client";

import { useId, useState, type CSSProperties } from "react";

import type { WorkflowDefinition } from "@/features/architecture/architecture-data";

import styles from "./BusinessWorkflowCard.module.css";

type Props = {
  workflow: WorkflowDefinition;
};

/**
 * 一条业务链路的展开卡片。
 *
 * 为什么是客户端组件：展开/收起和「当前步骤」都是交互状态。
 * 数据通过 props 传入（纯对象，可序列化），不会把整份架构模型打进客户端包。
 *
 * 步骤做成按钮而不是纯文本：面试演示时经常需要指着某一步讲，
 * 能选中并留下高亮比只能悬停有用；按钮天然可聚焦，键盘也能操作。
 */
export function BusinessWorkflowCard({ workflow }: Props) {
  const [expanded, setExpanded] = useState(false);
  const [activeStep, setActiveStep] = useState<number | null>(null);

  const detailId = useId();
  const statusId = useId();

  const activeLabel =
    activeStep === null ? null : workflow.pipeline[activeStep];

  return (
    <article
      className={styles.card}
      style={{ "--flow-color": workflow.color } as CSSProperties}
    >
      <header className={styles.head}>
        <h3 className={styles.title}>{workflow.title}</h3>
        <p className={styles.summary}>{workflow.summary}</p>
      </header>

      <ol className={styles.chain}>
        {workflow.pipeline.map((step, index) => {
          const active = activeStep === index;

          return (
            <li key={step} className={styles.step}>
              <button
                type="button"
                className={styles.stepButton}
                data-active={active}
                aria-current={active ? "step" : undefined}
                aria-describedby={statusId}
                onClick={() => setActiveStep(active ? null : index)}
              >
                <span className={styles.stepIndex} aria-hidden="true">
                  {index + 1}
                </span>
                <span className={styles.stepLabel}>{step}</span>
              </button>
            </li>
          );
        })}
      </ol>

      {/* 选中哪一步只改变高亮，不改变页面结构；用 live region 让读屏也知道 */}
      <p className={styles.status} id={statusId} aria-live="polite">
        {activeLabel
          ? `当前步骤 ${activeStep! + 1} / ${workflow.pipeline.length}：${activeLabel}`
          : `共 ${workflow.pipeline.length} 步，可逐一点选查看`}
      </p>

      <button
        type="button"
        className={styles.toggle}
        aria-expanded={expanded}
        aria-controls={detailId}
        onClick={() => setExpanded((value) => !value)}
      >
        {expanded ? "收起阶段说明" : "展开阶段说明"}
        <span className={styles.toggleMark} aria-hidden="true">
          {expanded ? "−" : "+"}
        </span>
      </button>

      <div className={styles.detail} id={detailId} hidden={!expanded}>
        <ol className={styles.stages}>
          {workflow.steps.map((stage, index) => (
            <li key={stage.id} className={styles.stage}>
              <span className={styles.stageIndex} aria-hidden="true">
                {String(index + 1).padStart(2, "0")}
              </span>
              <div>
                <p className={styles.stageTitle}>{stage.title}</p>
                <p className={styles.stageDesc}>{stage.description}</p>
              </div>
            </li>
          ))}
        </ol>

        <p className={styles.outcome}>
          <span className={styles.outcomeLabel}>产出</span>
          {workflow.outcome}
        </p>
      </div>
    </article>
  );
}
