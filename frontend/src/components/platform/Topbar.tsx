import { PLATFORM_NAME } from "@/features/platform/platform-config";

import styles from "./Topbar.module.css";

type Props = {
  /** 当前页面名称，由 PlatformShell 依据路由解析。 */
  pageName: string;
  /** 当前页面所属层级，总览页没有层级。 */
  sectionName?: string;
  menuOpen: boolean;
  onToggleMenu: () => void;
};

export function Topbar({
  pageName,
  sectionName,
  menuOpen,
  onToggleMenu,
}: Props) {
  return (
    <header className={styles.topbar}>
      <div className={styles.left}>
        <button
          type="button"
          className={styles.menuButton}
          aria-expanded={menuOpen}
          aria-controls="platform-sidebar"
          aria-label={menuOpen ? "收起导航" : "展开导航"}
          onClick={onToggleMenu}
        >
          <span aria-hidden="true">{menuOpen ? "✕" : "☰"}</span>
        </button>

        <span className={styles.brand}>{PLATFORM_NAME}</span>

        <span className={styles.divider} aria-hidden="true" />

        <p className={styles.current}>
          <span className={styles.currentLabel}>当前页面</span>
          <span className={styles.currentValue}>
            {sectionName ? `${sectionName} / ${pageName}` : pageName}
          </span>
        </p>
      </div>

      <dl className={styles.meta}>
        <div className={styles.metaItem}>
          <dt>环境状态</dt>
          <dd>本地静态预览 · 未连接后端</dd>
        </div>
        <div className={styles.metaItem}>
          <dt>项目阶段</dt>
          <dd>阶段 1 · 前端骨架</dd>
        </div>
      </dl>
    </header>
  );
}
