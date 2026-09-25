"use client";

import { useState } from "react";

import type { ArchitectureNode } from "@/features/architecture/architecture-data";

import styles from "./TechnologyStackMap.module.css";

export type TechStackGroup = {
  id: string;
  order: number;
  title: string;
  description: string;
  nodes: ArchitectureNode[];
};

type Props = {
  groups: TechStackGroup[];
};

const tabId = (nodeId: string) => `tech-node-${nodeId}`;
const panelId = (nodeId: string) => `tech-detail-${nodeId}`;

/**
 * 技术栈分层与节点详情。
 *
 * 详情**内联展开在所属层级的下面**，而不是放进侧边浮层：
 * 点哪个节点，说明就出现在哪一行下面，桌面和移动端行为一致，
 * 也不用处理窄屏下浮层要往哪搁的问题。
 *
 * 一次只展开一个。再点同一个节点即收起——留一个明显的「我不看了」的出口。
 *
 * 「对应页面或接口」取自节点的 interfaces，而不是渲染一条跳转链接：
 * 这一层视图刻意不含业务应用层（业务入口在上面已有卡片），
 * 而只有应用层节点才有 href，所以在这里渲染链接永远是个空判断。
 */
export function TechnologyStackMap({ groups }: Props) {
  const [selectedId, setSelectedId] = useState<string | null>(null);

  return (
    <div className={styles.stack}>
      {groups.map((group) => {
        const selected = group.nodes.find((node) => node.id === selectedId);

        return (
          <section key={group.id} className={styles.layer}>
            <header className={styles.layerHead}>
              <span className={styles.layerOrder} aria-hidden="true">
                {String(group.order).padStart(2, "0")}
              </span>
              <div>
                <h3 className={styles.layerTitle}>{group.title}</h3>
                <p className={styles.layerDesc}>{group.description}</p>
              </div>
            </header>

            <ul className={styles.nodes}>
              {group.nodes.map((node) => {
                const open = node.id === selectedId;

                return (
                  <li key={node.id}>
                    <button
                      type="button"
                      id={tabId(node.id)}
                      className={styles.nodeButton}
                      data-open={open}
                      aria-expanded={open}
                      aria-controls={panelId(node.id)}
                      onClick={() => setSelectedId(open ? null : node.id)}
                    >
                      {node.title}
                    </button>
                  </li>
                );
              })}
            </ul>

            {/* 详情紧跟在它所属的那一层下面，不另起一处 */}
            {selected ? (
              <div
                className={styles.detail}
                id={panelId(selected.id)}
                role="region"
                aria-labelledby={tabId(selected.id)}
              >
                <div className={styles.detailHead}>
                  <h4 className={styles.detailTitle}>{selected.title}</h4>
                  <p className={styles.detailSubtitle}>{selected.subtitle}</p>
                </div>

                <p className={styles.detailRole}>{selected.detail.role}</p>

                <dl className={styles.detailFacts}>
                  <div className={styles.detailFact}>
                    <dt>输入</dt>
                    <dd>{selected.detail.inputs.join("、")}</dd>
                  </div>
                  <div className={styles.detailFact}>
                    <dt>输出</dt>
                    <dd>{selected.detail.outputs.join("、")}</dd>
                  </div>
                  <div className={styles.detailFact}>
                    <dt>被哪些业务使用</dt>
                    <dd>{selected.detail.supports.join("、")}</dd>
                  </div>
                  <div className={styles.detailFact}>
                    <dt>对应页面或接口</dt>
                    <dd>
                      <span className={styles.mono}>
                        {selected.detail.interfaces.join(" · ")}
                      </span>
                    </dd>
                  </div>
                  <div className={styles.detailFact}>
                    <dt>涉及技术</dt>
                    <dd>
                      <span className={styles.mono}>
                        {selected.detail.technologies.join(" · ")}
                      </span>
                    </dd>
                  </div>
                </dl>
              </div>
            ) : null}
          </section>
        );
      })}
    </div>
  );
}
