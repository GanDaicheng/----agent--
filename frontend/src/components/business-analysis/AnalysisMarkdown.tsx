import ReactMarkdown, { type Components } from "react-markdown";
import remarkGfm from "remark-gfm";

import styles from "./AnalysisMarkdown.module.css";

const EXTERNAL_LINK = /^https?:\/\//i;

/**
 * 只透传 Markdown 真正会产出的属性，不做 `...rest` 透传。
 *
 * react-markdown 默认 `passNode: true`，会把 mdast 节点塞进每个自定义组件的 props，
 * 原样展开到 DOM 上会变成无意义的 `node` 属性。链接和表格本来就只带
 * href / title / children，逐个写明比先展开再剔除更省事，也顺手挡住了这个属性。
 */
const components: Components = {
  a({ href, title, children }) {
    const external = typeof href === "string" && EXTERNAL_LINK.test(href);
    return (
      <a
        href={href}
        title={title}
        {...(external ? { target: "_blank", rel: "noreferrer noopener" } : {})}
      >
        {children}
      </a>
    );
  },
  // 宽表格在窄屏只能横向滚动，包一层滚动容器比压缩列宽可读。
  table({ children }) {
    return (
      <div className={styles.tableScroll}>
        <table>{children}</table>
      </div>
    );
  },
};

/**
 * 渲染 Agent 回答的安全 Markdown。
 *
 * 刻意不装 rehype-raw：没有它，原始 HTML 不会被解析成元素，只会作为纯文本显示，
 * 因此不存在 `dangerouslySetInnerHTML` 和 HTML 注入路径。链接 URL 由 react-markdown
 * 自带的 urlTransform 过滤，`javascript:` 一类的协议会被剥掉。
 */
export function AnalysisMarkdown({ content }: { content: string }) {
  return (
    <div className={styles.markdown}>
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={components}>
        {content}
      </ReactMarkdown>
    </div>
  );
}
