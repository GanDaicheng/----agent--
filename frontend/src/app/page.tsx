import type { Metadata } from "next";

import { CapabilityCard } from "@/components/platform/CapabilityCard";
import { DataSourceNote } from "@/components/platform/DataSourceNote";
import { LayerFlow } from "@/components/platform/LayerFlow";
import {
  PLATFORM_NAME,
  PLATFORM_SECTIONS,
  PLATFORM_TAGLINE,
} from "@/features/platform/platform-config";
import {
  COMPLETED_GROUPS,
  HERO_FACTS,
  ROADMAP,
  SECTION_NEXT_STEP,
} from "@/mocks/platform-overview";

import styles from "./page.module.css";

// 根段页面不会套用 layout 里的 title.template，这里显式写全，与其他页面保持一致
export const metadata: Metadata = {
  title: { absolute: `平台总览 · ${PLATFORM_NAME}` },
};

export default function Home() {
  return (
    <div className={styles.page}>
      <section className={styles.hero}>
        <div className={styles.heroMain}>
          <p className={styles.eyebrow}>阶段 1 · 全平台前端骨架</p>
          <h1 className={styles.heroTitle}>{PLATFORM_NAME}</h1>
          <p className={styles.heroSubtitle}>{PLATFORM_TAGLINE}</p>
        </div>

        <dl className={styles.facts}>
          {HERO_FACTS.map((fact) => (
            <div key={fact.label} className={styles.fact}>
              <dt>{fact.label}</dt>
              <dd>{fact.value}</dd>
            </div>
          ))}
        </dl>
      </section>

      <section className={styles.section}>
        <div className={styles.sectionHead}>
          <div>
            <h2 className={styles.sectionTitle}>分层能力链路</h2>
            <p className={styles.sectionNote}>
              数据从业务系统流入业务中台，经数据中台沉淀后由 AI 中台加工，
              最终在智能应用中交付给业务人员。
            </p>
          </div>
          <DataSourceNote label="层级职责与状态来自前端配置" />
        </div>

        <LayerFlow />
      </section>

      <section className={styles.section}>
        <div className={styles.sectionHead}>
          <div>
            <h2 className={styles.sectionTitle}>平台建设进度</h2>
            <p className={styles.sectionNote}>
              只显示真实状态与下一步，不使用完成度百分比。
            </p>
          </div>
          <DataSourceNote label="状态为人工维护的配置，不是实时探测结果" />
        </div>

        <div className={styles.progressGrid}>
          {PLATFORM_SECTIONS.map((section) => (
            <CapabilityCard
              key={section.id}
              title={section.name}
              status={section.status}
              description={section.statusNote}
              footer={
                <>
                  <span className={styles.nextLabel}>下一步</span>
                  {SECTION_NEXT_STEP[section.id]}
                </>
              }
            />
          ))}
        </div>
      </section>

      <section className={styles.section}>
        <div className={styles.sectionHead}>
          <div>
            <h2 className={styles.sectionTitle}>当前已完成能力</h2>
            <p className={styles.sectionNote}>
              明确区分已完成的基础设施、已完成的 Agent 原型，
              以及尚未接入的真实业务数据。
            </p>
          </div>
        </div>

        <div className={styles.completedGrid}>
          {COMPLETED_GROUPS.map((group) => (
            <CapabilityCard
              key={group.key}
              title={group.title}
              caption={group.caption}
              items={group.items}
            />
          ))}
        </div>
      </section>

      <section className={styles.section}>
        <div className={styles.sectionHead}>
          <div>
            <h2 className={styles.sectionTitle}>推荐下一步</h2>
            <p className={styles.sectionNote}>
              按依赖顺序推进，前一步完成后再开始下一步。
            </p>
          </div>
        </div>

        <ol className={styles.roadmap}>
          {ROADMAP.map((item, index) => (
            <li key={item.step} className={styles.roadmapItem}>
              <span className={styles.roadmapIndex} aria-hidden="true">
                {index + 1}
              </span>
              <div className={styles.roadmapBody}>
                <p className={styles.roadmapStep}>{item.step}</p>
                <p className={styles.roadmapDetail}>{item.detail}</p>
              </div>
            </li>
          ))}
        </ol>
      </section>

      <footer className={styles.footer}>
        本页展示的是平台建设状态，不包含实时运行数据。各模块详情见左侧导航。
      </footer>
    </div>
  );
}
