"use client";

import { usePathname } from "next/navigation";
import { useEffect, useState, type ReactNode } from "react";

import { resolveNav } from "@/features/platform/platform-config";

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
  const nav = resolveNav(current);

  /**
   * 换页面时收起窄屏菜单。
   *
   * 写成「渲染期调整 state」而不是放进 useEffect：在 effect 里同步 setState 会多跑
   * 一轮渲染（先渲染出旧状态、effect 再改、然后重渲染），React 官方明确建议避免。
   * 这里记下上一次的路由，发现变了就地重置——渲染的结果从头到尾就是对的。
   *
   * 点侧边栏链接本来就会关（Sidebar 的 onNavigate），这一手管的是另一条路：
   * 菜单开着时从内容区点到别的页面（面包屑、入口卡），菜单不该留在展开状态。
   */
  const [lastPath, setLastPath] = useState(current);
  if (current !== lastPath) {
    setLastPath(current);
    setMenuOpen(false);
  }

  // 窄屏菜单展开后，Esc 应当能关掉它——只用鼠标点得到的面板对键盘用户等于不存在。
  // 菜单是 display:none 切换而非弹层，没有焦点陷阱，所以这里只需要管关闭。
  useEffect(() => {
    if (!menuOpen) return;

    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") {
        setMenuOpen(false);
      }
    }

    window.addEventListener("keydown", handleKeyDown);
    return () => {
      window.removeEventListener("keydown", handleKeyDown);
    };
  }, [menuOpen]);

  // 路由不在配置里（既不是模块页也不是总览或独立页）时给出准确文案，
  // 不假装这是一个正常页面
  const pageName = nav?.pageName ?? "未找到页面";

  return (
    <div className={styles.shell}>
      <a className="skipLink" href="#platform-main">
        跳到主要内容
      </a>

      <Topbar
        pageName={pageName}
        sectionName={nav?.sectionName}
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
