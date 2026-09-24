# 通用 RAG 检索增强设计

## 目标

把现有“单问题、纯向量、直接 top-k”升级为：

    原问题
    → 通用查询改写
    → 向量召回 + 关键词召回
    → RRF 融合去重
    → Reranker 精排
    → 最终 top-k
    → 原有 RAG 回答

## 约束

- 生产逻辑不得硬编码零售、财务、人事等领域词汇。
- 用户原问题始终保留；改写只用于召回，回答仍针对原问题。
- 最多生成 2 条改写，候选最多 20 条，最终上下文最多 5 条。
- 查询改写、元数据提取、关键词召回和 Reranker 都必须具备失败降级。
- 自动化测试不得调用真实 LLM、Embedding 或 Reranker 网络接口。
- 不修改零售业务表，不删除现有知识数据，不删除 Docker volume。
- 日志和响应不得包含密钥、完整向量或模型原始推理。

## 组件

### QueryRewriter

输入原问题，结构化输出原问题、最多两个改写问题和关键词。输出去空、去重；模型失败时只返回原问题。

### KnowledgeMetadataExtractor

文档入库时，根据文档标题、小节标题和正文动态提取 keywords、aliases，并构造 search_text。失败时退化为“标题 + 正文”。

### HybridRetriever

对原问题和改写问题执行 pgvector 余弦召回以及标题、小节、关键词、同义词、正文的关键词召回，再以 chunk id 去重并使用 RRF 融合排名。

### Reranker

以可替换接口对最多 20 个候选切片精排，最终保留 5 条。超时、限流、配置缺失或服务异常时退回 RRF 顺序。

### RagAnswerService

继续负责拼接最终资料和生成回答，只接收最终 top-k，不处理候选召回细节。

## 数据结构

knowledge_chunks 新增：

- keywords JSONB NOT NULL DEFAULT []
- aliases JSONB NOT NULL DEFAULT []
- search_text TEXT NOT NULL DEFAULT ''

迁移启用 pg_trgm，并为 search_text 创建 GIN trigram 索引。已有切片先使用标题和正文回填 search_text，再由幂等脚本补充关键词和同义词。

## 安全降级

- 查询改写失败：只检索原问题。
- 关键词检索失败：只使用向量结果。
- 向量检索失败：关键词成功时继续。
- Reranker 失败：使用 RRF 排名。
- 所有召回器失败：返回受控错误，不调用回答模型。

## 成功标准

- 任意领域的新文档无需修改代码即可参与混合检索。
- 同义改写、口语问题、精确字段名都能参与召回。
- 候选结果可追踪 vector rank、keyword rank、RRF score、rerank score。
- 原有 RAG 回答、知识上传、智能问数和前端页面无回归。
- 所有新增组件都支持依赖注入和离线测试。
