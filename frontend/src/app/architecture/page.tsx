import type { Metadata } from "next";

import { ErDiagram } from "@/components/platform/ErDiagram";
import { FlowDiagram, type FlowStepSpec } from "@/components/platform/FlowDiagram";
import { DataSourceNote } from "@/components/platform/DataSourceNote";
import { PageHeader } from "@/components/ui/PageHeader";
import { RETAIL_DATA_NOTE } from "@/features/platform/platform-config";

import styles from "./architecture.module.css";

export const metadata: Metadata = {
  title: "技术栈与架构",
  description:
    "平台用到的技术栈、系统结构与两条数据通路的实现细节。",
};

/**
 * 技术栈。分组按面试官会问的顺序排：先看用了什么，再看怎么串起来。
 *
 * 这里只列**真的在用**的东西。装了但没用的依赖、或者计划引入但尚未接入的，
 * 都不写进来——技术栈清单是最容易被追问的地方，写虚的一问就穿帮。
 */
const TECH_STACK: { group: string; items: string[] }[] = [
  {
    group: "前端",
    items: ["Next.js", "React", "TypeScript", "CSS Modules"],
  },
  {
    group: "后端",
    items: ["FastAPI", "Uvicorn", "Pydantic", "SQLAlchemy", "Alembic", "asyncpg"],
  },
  {
    group: "Agent",
    items: ["LangChain", "LangGraph", "OpenAI 兼容接口"],
  },
  {
    group: "数据",
    items: ["PostgreSQL", "pgvector", "SQLAlchemy AsyncEngine"],
  },
  {
    group: "RAG",
    items: [
      "文档处理器",
      "文本切片",
      "text-embedding-v4",
      "向量检索",
      "RAG 回答",
    ],
  },
  {
    group: "工程",
    items: ["Docker Compose", "pytest", "ESLint", "TypeScript strict"],
  },
];

/** 系统的纵向分层。并列节点表示这一步同时通向两条路径。 */
const SYSTEM_FLOW: FlowStepSpec[] = [
  { nodes: [{ label: "用户", hint: "浏览器访问前端页面" }] },
  {
    nodes: [
      {
        label: "Next.js 前端",
        hint: "平台外壳与三个功能页，只发请求、不碰数据库",
      },
    ],
  },
  {
    nodes: [
      {
        label: "FastAPI API 层",
        hint: "协议定义、请求校验、把内部异常映射成受控文案",
      },
    ],
  },
  {
    nodes: [
      {
        label: "LangGraph Agent",
        hint: "问题理解 → 资产发现 → SQL 生成 → 安全校验 → 执行",
      },
    ],
  },
  {
    caption: "两条取数路径",
    nodes: [
      { label: "PostgreSQL 数据查询", hint: "受控只读 SQL，白名单 + 只读事务" },
      { label: "pgvector 知识检索", hint: "余弦距离相似度，按 top_k 取片段" },
    ],
  },
  {
    caption: "两个出口",
    nodes: [
      { label: "智能问数", hint: "数据结论 + 明细表 + 图表建议" },
      { label: "知识问答", hint: "回答 + 检索到的文档小节" },
    ],
  },
];

/** RAG 的完整数据流：一份文件从上传到能被问答，中间经过哪几步。 */
const RAG_FLOW: FlowStepSpec[] = [
  { nodes: [{ label: "上传文档", hint: "md / txt / docx / pdf" }] },
  {
    nodes: [
      {
        label: "文件处理器",
        hint: "docx 按段落样式、PDF 按字号还原出标题层级",
      },
    ],
  },
  {
    nodes: [
      {
        label: "统一 Markdown 文本",
        hint: "所有格式先归一成带标题层级的文本，后续步骤只认这一种输入",
      },
    ],
  },
  { nodes: [{ label: "按标题切片", hint: "按二级标题切分，保留所属小节" }] },
  { nodes: [{ label: "Embedding", hint: "text-embedding-v4，1024 维" }] },
  {
    nodes: [
      { label: "pgvector", hint: "存成 vector(1024) 列，建余弦距离索引" },
    ],
  },
  {
    nodes: [
      { label: "相似度检索", hint: "按余弦距离排序，取 top_k 条作为回答依据" },
    ],
  },
  {
    nodes: [
      {
        label: "模型生成回答",
        hint: "只依据检索到的片段作答，资料不足时如实说明",
      },
    ],
  },
];

export default function Page() {
  return (
    <article className={styles.page}>
      <PageHeader
        title="技术栈与架构"
        subtitle="这一页讲平台是怎么搭起来的：用了哪些技术、请求从浏览器到数据经过哪几层、一份文档怎么变成可以被问到答案。"
      />

      <section className={styles.block}>
        <h2 className={styles.blockTitle}>技术栈</h2>
        <p className={styles.blockNote}>
          只列当前真实在用的部分。规划中但尚未接入的技术不写在这里。
        </p>

        <ul className={styles.stackGrid}>
          {TECH_STACK.map((group) => (
            <li key={group.group} className={styles.stackCard}>
              <h3 className={styles.stackGroup}>{group.group}</h3>
              <ul className={styles.stackItems}>
                {group.items.map((item) => (
                  <li key={item} className={styles.stackItem}>
                    {item}
                  </li>
                ))}
              </ul>
            </li>
          ))}
        </ul>
      </section>

      <section className={styles.block}>
        <h2 className={styles.blockTitle}>系统架构</h2>
        <p className={styles.blockNote}>
          从浏览器到数据的一次请求经过哪些层。前端只负责发请求和展示，
          取数与安全校验全部在后端完成。
        </p>

        <div className={styles.diagramWrap}>
          <FlowDiagram title="请求链路" steps={SYSTEM_FLOW} tone="dark" />
        </div>

        <p className={styles.flowNote}>
          值得一提的一层边界：<strong>Agent 不直接连数据库</strong>。
          它只调用数据服务的受控查询函数，由那一层做 AST 白名单校验和只读事务。
          这样即使模型生成了危险语句，也到不了数据库。
        </p>
      </section>

      <section className={styles.block}>
        <h2 className={styles.blockTitle}>RAG 数据流程</h2>
        <p className={styles.blockNote}>
          一份文档从上传到能被问答，中间经过的处理步骤。
        </p>

        <div className={styles.diagramWrap}>
          <FlowDiagram title="文档处理与检索" steps={RAG_FLOW} />
        </div>
      </section>

      <section className={styles.block}>
        <div className={styles.blockHead}>
          <h2 className={styles.blockTitle}>数据模型</h2>
          <DataSourceNote label="表结构与行数来自前端静态配置" />
        </div>
        <p className={styles.blockNote}>
          业务数据是标准的星型结构：四张维度表围绕一张订单事实表。
          {RETAIL_DATA_NOTE}
        </p>

        <div className={styles.diagramWrap}>
          <ErDiagram />
        </div>
      </section>

      <footer className={styles.footer}>
        各层的实现细节见左侧导航里的模块页面。
      </footer>
    </article>
  );
}
