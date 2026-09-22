"use client";

import { usePathname } from "next/navigation";
import { useState, type ReactNode } from "react";

import { resolveActiveModule } from "@/features/platform/platform-config";

import { Sidebar } from "./Sidebar";
import { Topbar } from "./Topbar";
import styles from "./PlatformShell.module.css";

/**
 * 平台外壳：顶栏 + 左侧导航 + 内容区。
 *
 * 只有这一层是客户端组件，因为它需要读取当前路由来决定高亮与顶栏标题；
 * 各页面本身仍是服务端组件，通过 children 传入。
 */
export function PlatformShell({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const [menuOpen, setMenuOpen] = useState(false);

  const current = pathname ?? "/";
  const active = resolveActiveModule(current);

  // 路由不在模块配置中时给出准确文案，不假装这是一个正常页面
  const pageName = active
    ? active.module.name
    : current === "/"
      ? "平台总览"
      : "未找到页面";

  return (
    <div className={styles.shell}>
      <a className="skipLink" href="#platform-main">
        跳到主要内容
      </a>

      <Topbar
        pageName={pageName}
        sectionName={active?.section.name}
        menuOpen={menuOpen}
        onToggleMenu={() => setMenuOpen((open) => !open)}
      />

      <div className={styles.body}>
        <Sidebar
          activeHref={current}
          open={menuOpen}
          onNavigate={() => setMenuOpen(false)}
        />

        <main id="platform-main" className={styles.content} tabIndex={-1}>
          {children}
        </main>
      </div>
    </div>
  );
}
