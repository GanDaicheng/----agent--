import Link from "next/link";

import { OVERVIEW_PIPELINE } from "@/features/platform/overview-config";

import styles from "./PlatformPipeline.module.css";

/**
 * 平台主链路：从输入到输出的完整闭环。
 *
 * 用有序列表而不是画一张 SVG：六个节点的先后关系本来就是「顺序」，
 * ol 的语义正好是这个意思，读屏软件会按顺序念出来，缩放也不会糊。
 *
 * 桌面端横向排列，窄屏自动转成纵向——转的是同一个列表的排布方式，
 * 不是两套 DOM，所以两种形态下的阅读顺序始终一致。
 */
export function PlatformPipeline() {
  return (
    <ol className={styles.pipeline}>
      {OVERVIEW_PIPELINE.map((node, index) => (
        <li key={node.id} className={styles.node}>
          <div className={styles.nodeTop}>
            <span className={styles.number} aria-hidden="true">
              {String(index + 1).padStart(2, "0")}
            </span>
            {index < OVERVIEW_PIPELINE.length - 1 ? (
              <span className={styles.connector} aria-hidden="true" />
            ) : null}
          </div>

          {/*
            文字整体包一层。窄屏时 .node 变成两列网格（编号 | 文字），
            编号列要跨满这一格的高度，而 grid-row: 1 / -1 只有在网格有显式行时
            才算得对——把文字包成一个子元素，行数就确定了。
            不包的话文字会被自动排进 26px 宽的编号列，每个字换一行。
          */}
          <div className={styles.nodeBody}>
            <p className={styles.nodeName}>{node.name}</p>
            <p className={styles.nodeRole}>{node.role}</p>
            <p className={styles.nodeTech}>{node.tech}</p>

            {node.href ? (
              <Link href={node.href} className={styles.nodeLink}>
                {node.hrefLabel}
                <span aria-hidden="true"> →</span>
              </Link>
            ) : null}
          </div>
        </li>
      ))}
    </ol>
  );
}
