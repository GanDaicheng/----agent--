import type { Metadata } from "next";
import Link from "next/link";

import { DataQueryWorkspace } from "@/components/data-query/DataQueryWorkspace";
import styles from "@/components/data-query/data-query.module.css";
import { getModule, getSection } from "@/features/platform/platform-config";

const SECTION_ID = "applications";
const MODULE_SLUG = "data-query";

export const metadata: Metadata = {
  title: "智能问数",
  description: "用自然语言查询零售样例数据，生成分析结论和图表建议。",
};

/**
 * 示例问题。
 *
 * 定义在服务端组件里、以 props 传给客户端工作台——数组是可序列化的，
 * 不会把整份配置或函数带进客户端包。
 *
 * 点击示例只填入输入框，不自动提交：每次提问都会真实调用模型服务，
 * 不能因为一次误点就花掉一次调用。
 */
const EXAMPLES = [
  "华东地区近六个月销售额趋势怎么样？",
  "销售额最高的 10 个商品是什么？",
  "不同区域的销售额和订单数有什么差异？",
  "不同会员等级的复购率有什么差异？",
] as const;

/**
 * 智能问数页面。
 *
 * 路由文件刻意保持很薄：只负责页头、边界说明和示例清单这些静态内容，
 * 交互与取数全部交给 DataQueryWorkspace（客户端组件）。
 * 这样绝大部分内容仍然是服务端渲染的。
 */
export default function Page() {
  const section = getSection(SECTION_ID);
  const moduleConfig = getModule(SECTION_ID, MODULE_SLUG);

  return (
    <article className={styles.page}>
      <nav className={styles.breadcrumb} aria-label="面包屑">
        <Link href="/">平台总览</Link>
        <span className={styles.sep} aria-hidden="true">
          /
        </span>
        <span>{section?.name ?? "智能应用"}</span>
        <span className={styles.sep} aria-hidden="true">
          /
        </span>
        <span aria-current="page">智能问数</span>
      </nav>

      <header className={styles.header}>
        <div className={styles.titleRow}>
          <h1 className={styles.title}>智能问数</h1>
        </div>
        <p className={styles.subtitle}>
          用自然语言查询零售样例数据，生成分析结论和图表建议。
        </p>

        {/* 边界说明放在最顶上：用户提交的内容会被送到模型服务，
            这件事必须在动手输入之前就讲清楚 */}
        <aside className={styles.boundary}>
          <span className={styles.boundaryTag}>使用边界</span>
          <div>
            <p style={{ margin: 0 }}>
              当前为本地零售样例数据演示。提交问题会调用模型服务，不适合输入敏感信息。
            </p>
            {moduleConfig?.notice ? (
              <p style={{ margin: "6px 0 0" }}>{moduleConfig.notice}</p>
            ) : null}
          </div>
        </aside>
      </header>

      <DataQueryWorkspace examples={EXAMPLES} />
    </article>
  );
}
