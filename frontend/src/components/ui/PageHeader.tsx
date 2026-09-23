import Link from "next/link";
import type { ReactNode } from "react";

import styles from "./PageHeader.module.css";

type Props = {
  /** 面包屑中间那一段，例如「数据中台」。省略时不渲染。 */
  sectionName?: string;
  title: string;
  /** 标题右侧的槽位，模块页用来放建设状态徽章。 */
  headingSlot?: ReactNode;
  /** 一句职责说明。 */
  subtitle?: ReactNode;
  /** 副标题下方的补充信息，例如模块所属层级。 */
  meta?: ReactNode;
  /** 使用边界 / 建设边界的内容。传了就渲染成一条提示。 */
  boundary?: ReactNode;
  /** 边界的语气：普通说明用 info，声明「现在还没有什么」用 warning。 */
  boundaryTone?: "info" | "warning";
  /** 边界的标签文案。 */
  boundaryLabel?: string;
};

/**
 * 页面页头。
 *
 * 抽出来是为了让全站的主标题只有一种字号、面包屑只有一种写法——
 * 改造前三交互页与模块页的 h1 分别是 26px 和 24px、面包屑各自手写一遍。
 *
 * 面包屑的中间段用 sectionName 而不是让调用方拼节点：路由结构是固定的三层，
 * 拼法散在各页面里迟早会出现某页少一层。
 */
export function PageHeader({
  sectionName,
  title,
  headingSlot,
  subtitle,
  meta,
  boundary,
  boundaryTone = "info",
  boundaryLabel = "使用边界",
}: Props) {
  return (
    <header className={styles.header}>
      <nav className={styles.breadcrumb} aria-label="面包屑">
        <Link href="/">平台总览</Link>
        {sectionName ? (
          <>
            <span className={styles.sep} aria-hidden="true">
              /
            </span>
            <span>{sectionName}</span>
          </>
        ) : null}
        <span className={styles.sep} aria-hidden="true">
          /
        </span>
        <span className={styles.current} aria-current="page">
          {title}
        </span>
      </nav>

      <div className={styles.titleRow}>
        <h1 className={styles.title}>{title}</h1>
        {headingSlot}
      </div>

      {subtitle ? <p className={styles.subtitle}>{subtitle}</p> : null}
      {meta ? <div className={styles.meta}>{meta}</div> : null}

      {boundary ? (
        <aside className={styles.boundary} data-tone={boundaryTone}>
          <span className={styles.boundaryTag}>{boundaryLabel}</span>
          <div className={styles.boundaryBody}>{boundary}</div>
        </aside>
      ) : null}
    </header>
  );
}
