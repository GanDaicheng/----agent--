import type { Metadata } from "next";

import { ErDiagram } from "@/components/platform/ErDiagram";
import { DataSourceNote } from "@/components/platform/DataSourceNote";
import { PageHeader } from "@/components/ui/PageHeader";
import { ARCHITECTURE_MODEL } from "@/features/architecture/architecture-data";
import { ArchitectureExplorer } from "@/features/architecture/ArchitectureExplorer";
import { ArchitectureExportButtons } from "@/features/architecture/ArchitectureExportButtons";
import { RETAIL_DATA_NOTE } from "@/features/platform/platform-config";

import styles from "./architecture.module.css";

export const metadata: Metadata = {
  title: "技术与业务全景",
  description: "AI 数据智能平台当前技术分层、平台能力、Agent 编排与业务链路全景。",
};

export default function Page() {
  const applicationCount = ARCHITECTURE_MODEL.nodes.filter(
    (node) => node.kind === "application",
  ).length;

  return (
    <article className={styles.page}>
      <PageHeader
        title="技术与业务全景"
        subtitle="从工程底座到业务应用，解释每项技术为什么存在、如何协作，以及三条完整链路如何落到当前五个可演示功能。"
      />

      <section className={styles.intro} aria-label="页面说明与导出">
        <div>
          <p className={styles.eyebrow}>CURRENT SYSTEM MAP</p>
          <h2>一张图看懂平台，而不是一份技术名词清单</h2>
          <p>
            主图按“技术分层 → 平台能力 → 业务应用”组织，只呈现仓库中已经实现的能力。
            面试时可先用全景图讲系统，再展开任意节点和链路回答追问。
          </p>
        </div>
        <div className={styles.introSide}>
          <dl className={styles.metrics}>
            <div><dt>{ARCHITECTURE_MODEL.layers.length}</dt><dd>技术层级</dd></div>
            <div><dt>{ARCHITECTURE_MODEL.workflows.length}</dt><dd>核心链路</dd></div>
            <div><dt>{applicationCount}</dt><dd>当前应用</dd></div>
          </dl>
          <ArchitectureExportButtons />
        </div>
      </section>

      <ArchitectureExplorer />

      <section className={styles.block} aria-labelledby="technology-map-title">
        <div className={styles.blockHead}>
          <div>
            <p className={styles.eyebrow}>TECHNOLOGY RESPONSIBILITY MAP</p>
            <h2 id="technology-map-title">完整技术栈与职责映射</h2>
          </div>
          <p>每项技术都对应具体输入、输出和业务职责；仅安装但未使用的依赖不计入。</p>
        </div>

        <div className={styles.techGroups}>
          {[...ARCHITECTURE_MODEL.layers]
            .sort((left, right) => left.order - right.order)
            .filter((layer) => layer.id !== "applications")
            .map((layer) => (
              <section key={layer.id} className={styles.techGroup}>
                <header>
                  <span>{String(layer.order).padStart(2, "0")}</span>
                  <div><h3>{layer.title}</h3><p>{layer.description}</p></div>
                </header>
                <ul>
                  {ARCHITECTURE_MODEL.nodes
                    .filter((node) => node.layerId === layer.id)
                    .map((node) => (
                      <li key={node.id}>
                        <div className={styles.techName}>
                          <strong>{node.title}</strong>
                          <span>{node.detail.technologies.join(" · ")}</span>
                        </div>
                        <p>{node.detail.role}</p>
                        <small>支撑：{node.detail.supports.join(" / ")}</small>
                      </li>
                    ))}
                </ul>
              </section>
            ))}
        </div>
      </section>

      <section className={styles.block} aria-labelledby="data-model-title">
        <div className={styles.blockHead}>
          <div>
            <p className={styles.eyebrow}>DATA FOUNDATION</p>
            <h2 id="data-model-title">零售星型数据模型</h2>
          </div>
          <DataSourceNote label="表结构与行数来自当前零售样例配置" />
        </div>
        <p className={styles.blockNote}>
          四张维度表围绕一张订单事实表，为安全 SQL、智能问数和经营分析提供结构化数据。
          {RETAIL_DATA_NOTE}
        </p>
        <div className={styles.diagramWrap}><ErDiagram /></div>
      </section>

      <section className={styles.boundary} aria-labelledby="boundary-title">
        <div>
          <p className={styles.eyebrow}>SCOPE &amp; SECURITY</p>
          <h2 id="boundary-title">当前项目边界</h2>
          <p>这些限制是当前作品集版本的真实边界，也是继续工程化时优先补齐的部分。</p>
        </div>
        <ul>
          {ARCHITECTURE_MODEL.boundaries.map((boundary, index) => (
            <li key={boundary}><span>{String(index + 1).padStart(2, "0")}</span>{boundary}</li>
          ))}
        </ul>
      </section>
    </article>
  );
}

