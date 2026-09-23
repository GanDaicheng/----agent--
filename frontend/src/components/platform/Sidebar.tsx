import Link from "next/link";

import {
  EXTRA_NAV_ITEMS,
  OVERVIEW_NAV_ITEM,
  PLATFORM_SECTIONS,
  STATUS_LABEL,
  getModuleHref,
} from "@/features/platform/platform-config";

import { StatusBadge } from "./StatusBadge";
import styles from "./Sidebar.module.css";

type Props = {
  /** 当前路由，用于高亮。 */
  activeHref: string;
  /** 窄屏下是否展开，桌面端忽略该状态。 */
  open: boolean;
  /** 点击任意链接后收起窄屏导航。 */
  onNavigate: () => void;
};

export function Sidebar({ activeHref, open, onNavigate }: Props) {
  return (
    <nav
      id="platform-sidebar"
      className={styles.sidebar}
      data-open={open}
      aria-label="平台导航"
    >
      <ul className={styles.overviewList}>
        <li>
          <Link
            href={OVERVIEW_NAV_ITEM.href}
            className={styles.overviewLink}
            data-active={activeHref === OVERVIEW_NAV_ITEM.href}
            aria-current={activeHref === OVERVIEW_NAV_ITEM.href ? "page" : undefined}
            onClick={onNavigate}
          >
            {OVERVIEW_NAV_ITEM.name}
          </Link>
        </li>
      </ul>

      {PLATFORM_SECTIONS.map((section) => (
        <section key={section.id} className={styles.group}>
          <div className={styles.groupHead}>
            <h2 className={styles.groupTitle}>{section.name}</h2>
            <StatusBadge status={section.status} size="sm" />
          </div>

          <ul className={styles.moduleList}>
            {section.modules.map((module) => {
              const href = getModuleHref(section, module);
              const active = href === activeHref;

              return (
                <li key={module.slug}>
                  <Link
                    href={href}
                    className={styles.moduleLink}
                    data-active={active}
                    aria-current={active ? "page" : undefined}
                    title={`${module.name} · ${STATUS_LABEL[module.status]}`}
                    onClick={onNavigate}
                  >
                    <span className={styles.moduleName}>{module.name}</span>
                    <span
                      className={styles.dot}
                      data-status={module.status}
                      aria-hidden="true"
                    />
                    <span className={styles.srOnly}>
                      {STATUS_LABEL[module.status]}
                    </span>
                  </Link>
                </li>
              );
            })}
          </ul>
        </section>
      ))}

      {/* 不属于任何层级的独立页面。没有状态点——它是讲解性质的一页，没有建设进度。 */}
      <ul className={styles.extraList}>
        {EXTRA_NAV_ITEMS.map((item) => {
          const active = item.href === activeHref;

          return (
            <li key={item.href}>
              <Link
                href={item.href}
                className={styles.extraLink}
                data-active={active}
                aria-current={active ? "page" : undefined}
                title={item.desc}
                onClick={onNavigate}
              >
                {item.name}
              </Link>
            </li>
          );
        })}
      </ul>

      <p className={styles.footnote}>
        导航里的圆点表示模块的建设进度。它是人工维护的功能状态，
        与顶栏检测到的服务连通性是两回事。
      </p>
    </nav>
  );
}
