import { LinkButton } from "@/components/ui/Button";
import { PageHeader } from "@/components/ui/PageHeader";
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
 *
 * 信息顺序按「读者想知道什么」排：
 * 这是什么 → 现在能做什么 → 现在还不能做什么 → 能不能去试 → 接下来做什么。
 * 「可前往的功能页」紧跟边界说明：用户读完「现在还没有 X」之后，
 * 下一个问题必然是「那我能用什么」，入口就该在这里。
 */
export function ModulePage({ section, module }: Props) {
  return (
    <article className={styles.page}>
      <PageHeader
        sectionName={section.name}
        title={module.name}
        headingSlot={<StatusBadge status={module.status} />}
        subtitle={module.summary}
        meta={
          <>
            <span className={styles.sectionTag}>{section.name}</span>
            <span>{section.duty}</span>
          </>
        }
        boundary={module.notice ? <p>{module.notice}</p> : undefined}
        boundaryTone="warning"
        boundaryLabel="建设边界"
      />

      {module.workflow ? (
        <WorkflowChain title="已跑通的处理链路" steps={module.workflow} />
      ) : null}

      {/* 只有真有页面的模块才有这个字段。没有就整块不渲染——
          不留一个点了没反应的按钮，也不跳到一个仍然只是说明的页面。 */}
      {module.livePage ? (
        <section className={styles.entry} aria-labelledby="live-page-heading">
          <div className={styles.entryBody}>
            <h2 className={styles.entryTitle} id="live-page-heading">
              前往 {module.livePage.label}
            </h2>
            <p className={styles.entryDesc}>{module.livePage.desc}</p>
          </div>
          <LinkButton href={module.livePage.href} variant="primary">
            打开 {module.livePage.label}
          </LinkButton>
        </section>
      ) : null}

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
          hint="状态是人工维护的功能进度，不是实时探测结果"
        />
      </footer>
    </article>
  );
}
