import type { Metadata } from "next";
import Link from "next/link";

import { ApplicationCapabilityCard } from "@/components/platform/ApplicationCapabilityCard";
import { BusinessWorkflowCard } from "@/components/platform/BusinessWorkflowCard";
import { DataSourceNote } from "@/components/platform/DataSourceNote";
import { InterviewHighlights } from "@/components/platform/InterviewHighlights";
import { PlatformHero } from "@/components/platform/PlatformHero";
import { PlatformPipeline } from "@/components/platform/PlatformPipeline";
import { TechnologyStackMap } from "@/components/platform/TechnologyStackMap";
import { ARCHITECTURE_MODEL } from "@/features/architecture/architecture-data";
import {
  OVERVIEW_APPLICATIONS,
  OVERVIEW_TECH_LAYERS,
  PROJECT_BOUNDARY_INTRO,
  PROJECT_BOUNDARY_ITEMS,
  getTechNodesByLayer,
} from "@/features/platform/overview-config";
import {
  PAGE_HREFS,
  PLATFORM_NAME,
} from "@/features/platform/platform-config";

import styles from "./page.module.css";

// 根段页面不会套用 layout 里的 title.template，这里显式写全，与其他页面保持一致
export const metadata: Metadata = {
  title: { absolute: `平台总览 · ${PLATFORM_NAME}` },
};

/**
 * 平台总览。
 *
 * 这一页要回答的是「这个平台解决什么问题、中间经过哪些能力、最后产出什么」，
 * 所以顺序是：一句话说清定位 → 一张主链路图 → 能点的业务入口 → 三条流程细节
 * → 技术栈 → 面试视角 → 边界。
 *
 * 两处刻意为之：
 * 1. **边界放最后**。它不是不存在，而是不该成为面试官的第一印象。
 * 2. **不出现任何建设进度、完成率**。这不是一张进度表，是一个能用的平台。
 *
 * 数据来源分三处，都有各自的理由：
 * - 本页叙事（Hero、主链路、业务卡片、亮点）→ overview-config
 * - 技术分层、节点职责、三条流程 → ARCHITECTURE_MODEL（与架构页共用一份）
 * - 平台名与路径 → platform-config
 */
export default function Home() {
  const techGroups = OVERVIEW_TECH_LAYERS.map((layer) => ({
    id: layer.id,
    order: layer.order,
    title: layer.title,
    description: layer.description,
    nodes: getTechNodesByLayer(layer.id),
  }));

  return (
    <div className={styles.page}>
      <PlatformHero />

      <section className={styles.section} aria-labelledby="pipeline-title">
        <div className={styles.sectionHead}>
          <h2 className={styles.sectionTitle} id="pipeline-title">
            平台主链路
          </h2>
          <p className={styles.sectionNote}>
            从业务文档与业务数据出发，经过采集入库、RAG 检索与 Agent 编排，
            最终交付可追溯的结论与报告。每一个可跳转的环节都指向真实页面。
          </p>
        </div>

        <PlatformPipeline />
      </section>

      <section className={styles.section} aria-labelledby="applications-title">
        <div className={styles.sectionHead}>
          <h2 className={styles.sectionTitle} id="applications-title">
            四个业务入口
          </h2>
          <p className={styles.sectionNote}>
            都可以直接点开使用。每张卡片写明它解决什么问题、吃什么、怎么处理、产出什么。
          </p>
        </div>

        <ul className={styles.appGrid}>
          {OVERVIEW_APPLICATIONS.map((entry) => (
            <ApplicationCapabilityCard key={entry.id} entry={entry} />
          ))}
        </ul>
      </section>

      <section className={styles.section} aria-labelledby="workflows-title">
        <div className={styles.sectionHead}>
          <h2 className={styles.sectionTitle} id="workflows-title">
            三条业务流程
          </h2>
          <p className={styles.sectionNote}>
            平台上有三条独立链路，分别处理文档知识、结构化数据和复杂经营目标。
            点某一步可以高亮它，展开可以看到每个阶段在做什么。
          </p>
        </div>

        <div className={styles.workflowGrid}>
          {ARCHITECTURE_MODEL.workflows.map((workflow) => (
            <BusinessWorkflowCard key={workflow.id} workflow={workflow} />
          ))}
        </div>
      </section>

      <section className={styles.section} aria-labelledby="tech-title">
        <div className={styles.sectionHead}>
          <h2 className={styles.sectionTitle} id="tech-title">
            技术栈分层
          </h2>
          <p className={styles.sectionNote}>
            五层从上到下是依赖顺序。点任意技术节点，可以看到它的作用、输入输出、
            被哪些业务使用，以及对应的页面或接口。
          </p>
          <DataSourceNote label="技术分层与节点职责与「技术栈与架构」页共用同一份数据源" />
        </div>

        <TechnologyStackMap groups={techGroups} />
      </section>

      <section className={styles.section} aria-labelledby="interview-title">
        <div className={styles.sectionHead}>
          <h2 className={styles.sectionTitle} id="interview-title">
            面试视角
          </h2>
        </div>

        <InterviewHighlights />
      </section>

      {/* 边界放最后并压低视觉权重：它需要被读到，但不该是这一页的重点 */}
      <section className={styles.boundary} aria-labelledby="boundary-title">
        <h2 className={styles.boundaryTitle} id="boundary-title">
          当前边界与后续扩展方向
        </h2>
        <p className={styles.boundaryIntro}>{PROJECT_BOUNDARY_INTRO}</p>

        <ul className={styles.boundaryList}>
          {PROJECT_BOUNDARY_ITEMS.map((item) => (
            <li key={item}>{item}</li>
          ))}
        </ul>
      </section>

      <footer className={styles.footer}>
        各业务入口的详细说明见左侧导航；数据模型、技术分层与完整架构见
        <Link href={PAGE_HREFS.architecture}>技术栈与架构</Link>。
      </footer>
    </div>
  );
}
