import Link from "next/link";

import {
  EXTRA_NAV_ITEMS,
  NAV_SECTIONS,
  OVERVIEW_NAV_ITEM,
  getModuleHref,
} from "@/features/platform/platform-config";

import styles from "./Sidebar.module.css";

type Props = {
  /** 当前路由，用于高亮。 */
  activeHref: string;
  /** 窄屏下是否展开，桌面端忽略该状态。 */
  open: boolean;
  /** 点击任意链接后收起窄屏导航。 */
  onNavigate: () => void;
};

/**
 * 左侧导航。
 *
 * 只渲染 NAV_SECTIONS——`platform-config` 里过滤掉 navHidden 的那一份。
 * 这里不再显示任何建设状态：状态属于模块自己的页面，放在导航里会让
 * 一个可以直接使用的平台看起来像一张项目进度表。
 */
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
            title={OVERVIEW_NAV_ITEM.desc}
            onClick={onNavigate}
          >
            {OVERVIEW_NAV_ITEM.name}
          </Link>
        </li>
      </ul>

      {NAV_SECTIONS.map((section) => (
        <section
          key={section.id}
          className={styles.group}
          data-section={section.id}
        >
          <h2 className={styles.groupTitle}>{section.name}</h2>

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
                    title={module.summary}
                    onClick={onNavigate}
                  >
                    {module.name}
                  </Link>
                </li>
              );
            })}
          </ul>
        </section>
      ))}

      {/* 辅助入口：不属于任何业务层级，用分隔线隔开并推到导航底部 */}
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
    </nav>
  );
}
