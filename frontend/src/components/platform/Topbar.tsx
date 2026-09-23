import { PLATFORM_NAME } from "@/features/platform/platform-config";

import { ServiceHealthCheck } from "./ServiceHealthCheck";
import styles from "./Topbar.module.css";

type Props = {
  /** 当前页面名称，由 PlatformShell 依据路由解析。 */
  pageName: string;
  /** 当前页面所属层级，总览页没有层级。 */
  sectionName?: string;
  menuOpen: boolean;
  onToggleMenu: () => void;
};

/**
 * 顶栏：品牌、当前位置、服务连通性检查。
 *
 * 这里曾经写死两块状态文案（大意是「未连接后端」和「前端骨架阶段」），
 * 接口接通之后两句都成了假的，而且它们是**硬编码在组件里的**——
 * 改配置不会让它们更新。现在只放真实探测出来的结果。
 */
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

      <ServiceHealthCheck />
    </header>
  );
}
