import Link from "next/link";

import type {
  PlatformModule,
  PlatformSection,
} from "@/features/platform/platform-config";

import { CapabilityCard } from "./CapabilityCard";
import { DataSourceNote } from "./DataSourceNote";
import { StatusBadge } from "./StatusBadge";
import { WorkflowChain } from "./WorkflowChain";
import styles from "./ModulePage.module.css";

type Props = {
  section: PlatformSection;
  module: PlatformModule;
};

/**
 * 所有二级模块共用的页面模板。
 *
 * 页面内容全部来自 platform-config 中的模块元信息，页面文件本身只负责
 * 把路由参数解析成 section + module 后交给这里渲染。
 */
export function ModulePage({ section, module }: Props) {
  return (
    <article className={styles.page}>
      <nav className={styles.breadcrumb} aria-label="面包屑">
        <Link href="/">平台总览</Link>
        <span className={styles.sep} aria-hidden="true">
          /
        </span>
        <span>{section.name}</span>
        <span className={styles.sep} aria-hidden="true">
          /
        </span>
        <span className={styles.current} aria-current="page">
          {module.name}
        </span>
      </nav>

      <header className={styles.header}>
        <div className={styles.titleRow}>
          <h1 className={styles.title}>{module.name}</h1>
          <StatusBadge status={module.status} />
        </div>
        <p className={styles.summary}>{module.summary}</p>
        <p className={styles.sectionLine}>
          <span className={styles.sectionName}>{section.name}</span>
          {section.duty}
        </p>
      </header>

      {module.notice ? (
        <aside className={styles.notice}>
          <span className={styles.noticeLabel}>建设边界</span>
          <p className={styles.noticeText}>{module.notice}</p>
        </aside>
      ) : null}

      {module.workflow ? (
        <WorkflowChain title="已跑通的受控问数流程" steps={module.workflow} />
      ) : null}

      {module.blocks?.map((block) => (
        <section key={block.title} className={styles.block}>
          <div className={styles.blockHead}>
            <h2 className={styles.blockTitle}>{block.title}</h2>
            {block.caption ? (
              <p className={styles.blockCaption}>{block.caption}</p>
            ) : null}
          </div>

          <ul className={styles.blockList}>
            {block.items.map((item) => (
              <li key={item.name} className={styles.blockItem}>
                <span className={styles.blockName}>{item.name}</span>
                <span className={styles.blockDesc}>{item.desc}</span>
              </li>
            ))}
          </ul>
        </section>
      ))}

      <div className={styles.grid}>
        <CapabilityCard
          title="当前能力"
          status={module.status}
          items={module.current}
        />
        <CapabilityCard title="后续接入内容" items={module.upcoming} />
        <CapabilityCard
          title="依赖关系"
          caption="该模块在平台中的上下游位置。"
          items={module.dependencies}
          variant="chain"
        />
      </div>

      <footer className={styles.footer}>
        <DataSourceNote
          label="本页为平台建设说明，内容来自前端静态配置"
          hint="不代表任何真实运行数据"
        />
      </footer>
    </article>
  );
}
