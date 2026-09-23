import type { Metadata } from "next";
import Link from "next/link";

import { DataSourceNote } from "@/components/platform/DataSourceNote";
import { StatusBadge } from "@/components/platform/StatusBadge";
import { WorkflowChain } from "@/components/platform/WorkflowChain";
import {
  PLATFORM_BADGE,
  PLATFORM_NAME,
  PLATFORM_SECTIONS,
  PLATFORM_TAGLINE,
  RETAIL_DATA_NOTE,
  getOverviewEntries,
} from "@/features/platform/platform-config";
import { DOCUMENT_CHAIN, QUERY_CHAIN } from "@/mocks/platform-overview";

import styles from "./page.module.css";

// 根段页面不会套用 layout 里的 title.template，这里显式写全，与其他页面保持一致
export const metadata: Metadata = {
  title: { absolute: `平台总览 · ${PLATFORM_NAME}` },
};

/**
 * 平台总览。
 *
 * 只讲已经跑通的东西。这里刻意**不显示**模块建设数量、完成度百分比、
 * 未完成模块清单——面试官需要的是「这个平台能做什么」，
 * 而不是「还有多少没做」。建设中/未建立的部分放在各模块自己的页面里说明。
 */
export default function Home() {
  const entries = getOverviewEntries();

  return (
    <div className={styles.page}>
      <section className={styles.hero}>
        <p className={styles.badge}>{PLATFORM_BADGE}</p>
        <h1 className={styles.heroTitle}>{PLATFORM_NAME}</h1>
        <p className={styles.heroSubtitle}>{PLATFORM_TAGLINE}</p>
        <p className={styles.heroNote}>{RETAIL_DATA_NOTE}</p>
      </section>

      {/* 三个核心功能排在最前：进这个页面的人多半是来用功能的 */}
      <section className={styles.section}>
        <div className={styles.sectionHead}>
          <h2 className={styles.sectionTitle}>三个核心功能</h2>
          <p className={styles.sectionNote}>
            都已可交互，点卡片直接进入。
          </p>
        </div>

        <ul className={styles.entryGrid}>
          {entries.map((entry) => (
            <li key={entry.key}>
              <Link href={entry.href} className={styles.entryCard}>
                <span className={styles.entrySection}>{entry.sectionName}</span>
                <span className={styles.entryTitle}>{entry.moduleName}</span>
                <span className={styles.entryDesc}>{entry.desc}</span>
                <span className={styles.entryAction}>
                  进入<span aria-hidden="true"> →</span>
                </span>
              </Link>
            </li>
          ))}
        </ul>
      </section>

      {/* 按层级组织的能力视图：每张卡里是这个层级的模块与它们的已完成能力 */}
      <section className={styles.section}>
        <div className={styles.sectionHead}>
          <h2 className={styles.sectionTitle}>平台能力</h2>
          <p className={styles.sectionNote}>
            按数据中台、AI 中台、智能应用三层组织。卡片里的能力清单都对应真实实现。
          </p>
          <DataSourceNote label="职责与能力清单来自前端配置" />
        </div>

        <div className={styles.layerGrid}>
          {PLATFORM_SECTIONS.map((section) => (
            <article
              key={section.id}
              className={styles.layerCard}
              data-layer={section.id}
            >
              <header className={styles.layerHead}>
                <h3 className={styles.layerName}>{section.name}</h3>
                <StatusBadge status={section.status} size="sm" />
              </header>
              <p className={styles.layerDuty}>{section.duty}</p>

              <ul className={styles.moduleList}>
                {section.modules.map((module) => {
                  const live = module.livePage;
                  const body = (
                    <>
                      <span className={styles.moduleName}>{module.name}</span>
                      <span className={styles.moduleSummary}>{module.summary}</span>
                      <ul className={styles.capList}>
                        {module.current.map((item) => (
                          <li key={item}>{item}</li>
                        ))}
                      </ul>
                      {live ? (
                        <span className={styles.moduleAction}>
                          进入 {live.label}
                          <span aria-hidden="true"> →</span>
                        </span>
                      ) : null}
                    </>
                  );

                  return (
                    <li key={module.slug}>
                      {live ? (
                        // 整张卡可点。链接里包着一段说明文字，所以用 aria-label
                        // 给出简洁的可访问名称，避免读屏把整段清单念成链接名。
                        <Link
                          href={live.href}
                          className={styles.moduleCard}
                          aria-label={`进入${live.label}`}
                        >
                          {body}
                        </Link>
                      ) : (
                        <div className={styles.moduleCard}>{body}</div>
                      )}
                    </li>
                  );
                })}
              </ul>
            </article>
          ))}
        </div>
      </section>

      <section className={styles.section}>
        <div className={styles.sectionHead}>
          <h2 className={styles.sectionTitle}>两条真实链路</h2>
          <p className={styles.sectionNote}>
            平台上有两条独立的数据通路，各自负责不同性质的问题。
          </p>
        </div>

        <div className={styles.chainGrid}>
          <WorkflowChain
            title="链路一 · 文档变成可检索的知识"
            steps={DOCUMENT_CHAIN}
            headingLevel="h3"
          />
          <WorkflowChain
            title="链路二 · 问题变成分析结论"
            steps={QUERY_CHAIN}
            headingLevel="h3"
          />
        </div>
      </section>

      <footer className={styles.footer}>
        各模块的详细说明见左侧导航；技术栈与系统结构见「技术栈与架构」。
      </footer>
    </div>
  );
}
