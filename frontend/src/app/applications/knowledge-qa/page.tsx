import type { Metadata } from "next";
import Link from "next/link";

import { getSection } from "@/features/platform/platform-config";

import { KnowledgeQaWorkspace } from "./KnowledgeQaWorkspace";
import styles from "./knowledge-qa.module.css";

const SECTION_ID = "applications";

export const metadata: Metadata = {
  title: "知识问答",
  description: "基于零售知识库回答问题，给出回答并列出参考来源。",
};

/**
 * 示例问题。
 *
 * 全部取自知识库文档里确实写了答案的小节，覆盖 5 份文档各一次——
 * 点进去就能看到一次成功的回答，而不是先撞上「资料不足」。
 * 这也让页面本身成了一条可演示的验收路径。
 *
 * 定义在服务端组件里、以 props 传给客户端工作台——数组是可序列化的，
 * 不会把整份配置或函数带进客户端包。
 *
 * 点击示例只填入输入框，不自动提交：每次提问都会真实调用 embedding 与模型服务，
 * 不能因为一次误点就花掉两次调用。
 */
const EXAMPLES = [
  "客单价怎么算？",
  "为什么高等级会员复购率更高？",
  "为什么 12 月销售额通常更高？",
  "订单分析要关联哪些表？",
  "华东销售额为什么通常更高？",
] as const;

/**
 * 知识库问答页面。
 *
 * 路由文件刻意保持很薄：只负责页头、边界说明和示例清单这些静态内容，
 * 交互与取数全部交给 KnowledgeQaWorkspace（客户端组件）。
 * 这样绝大部分内容仍然是服务端渲染的。
 *
 * 与同层的「智能问数」页面是**两条独立链路**：
 * 那条查业务数据（销售额是多少），这条查知识文档（销售额怎么算）。
 */
export default function Page() {
  const section = getSection(SECTION_ID);

  return (
    <article>
      <nav className={styles.breadcrumb} aria-label="面包屑">
        <Link href="/">平台总览</Link>
        <span className={styles.sep} aria-hidden="true">
          /
        </span>
        <span>{section?.name ?? "智能应用"}</span>
        <span className={styles.sep} aria-hidden="true">
          /
        </span>
        <span aria-current="page">知识问答</span>
      </nav>

      <header className={styles.header}>
        <div className={styles.titleRow}>
          <h1 className={styles.title}>知识问答</h1>
        </div>
        <p className={styles.subtitle}>
          基于零售知识库回答问题：业务口径、指标定义、规则说明与数据字典。
          回答只依据知识库文档，并列出参考来源。
        </p>

        {/* 边界说明放在最顶上：用户提交的内容会被送到 embedding 与模型服务，
            而且模型可能答不出来——这两件事都必须在动手输入之前讲清楚 */}
        <aside className={styles.boundary}>
          <span className={styles.boundaryTag}>使用边界</span>
          <div>
            <p style={{ margin: 0 }}>
              当前为本地零售知识库演示（5 份文档、44 个知识切片）。
              提交问题会调用 embedding 与模型服务，不适合输入敏感信息。
            </p>
            <p style={{ margin: "6px 0 0" }}>
              回答只依据知识库中已有的文档。资料不足时会明确说明「没有足够信息」，
              不会用模型自身的知识补全。这是新建的独立链路，与「智能问数」查业务数据不是同一条。
            </p>
          </div>
        </aside>
      </header>

      <KnowledgeQaWorkspace examples={EXAMPLES} />
    </article>
  );
}
