/**
 * 首页的编辑性文案。
 *
 * 只放**没法从配置算出来**的内容：两条真实链路的步骤。
 * 模块清单、建设状态、功能入口全部从 platform-config 计算，不在这里重写第二遍——
 * 同一件事写两份，早晚会不一致。
 *
 * 这个文件里也**不许**出现任何看起来像实时指标的数字（访问量、成功率、成本）。
 */

/** 凡是展示前端静态配置的位置都要带上这句话。 */
export const MOCK_NOTICE = "静态配置数据 · 非实时运行数据";

/**
 * 链路一：文档如何变成可被回答的知识。
 *
 * 每一步都对应后端真实存在的处理环节（见 app/services/document_processors.py
 * 与 knowledge_ingestion.py），不是示意图里编出来的步骤。
 */
export const DOCUMENT_CHAIN = [
  "文档上传",
  "文件解析",
  "文本切片",
  "Embedding",
  "pgvector",
  "知识问答",
];

/**
 * 链路二：一个中文问题如何变成一份分析结论。
 *
 * 对应 LangGraph 图的真实节点（见 app/agent/data_query/graph.py）。
 */
export const QUERY_CHAIN = [
  "中文问题",
  "LangGraph Agent",
  "SQL 安全校验",
  "PostgreSQL 查询",
  "分析结论",
];
