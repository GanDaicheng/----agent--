import { LinkButton } from "@/components/ui/Button";
import { Notice } from "@/components/ui/Notice";
import {
  getRetrievalMethod,
  type RagAnswerResponse,
  type RagAnswerStatus,
  type RagRetrievalSummary,
  type RagSource,
  type RetrievalMethod,
} from "@/lib/api/rag-answer";

import styles from "./knowledge-qa.module.css";

/**
 * 一个分数是否真的存在。
 *
 * 三种「没有」都算没有：字段缺席（老后端）、null（这一路没命中）、
 * 以及类型不对的值。**不把坏值当 0**——0 是一个有意义的分数，
 * 而「没有这个数」和「这个数是 0」在界面上必须长得不一样。
 */
function isScore(value: number | null | undefined): value is number {
  return typeof value === "number" && Number.isFinite(value);
}

/** 命中方式的中文说法。判定规则在 rag-answer.ts 里（那是字段语义的一部分）。 */
const METHOD_LABEL: Record<RetrievalMethod, string> = {
  vector: "向量召回",
  keyword: "关键词召回",
  hybrid: "混合召回",
  unknown: "检索命中",
};

/**
 * 原始排序分数的展示项。
 *
 * 小数位不是随手写的：融合分和精排分都在 0~1 量级，留 4 位才有区分度；
 * 关键词分是 0~100 的层级分，留 2 位足够，多给就是假精度。
 */
function scoreParts(source: RagSource): string[] {
  const parts: string[] = [];
  if (isScore(source.rrf_score)) parts.push(`融合 ${source.rrf_score.toFixed(4)}`);
  if (isScore(source.keyword_score)) parts.push(`关键词 ${source.keyword_score.toFixed(2)}`);
  if (isScore(source.rerank_score)) parts.push(`精排 ${source.rerank_score.toFixed(4)}`);
  return parts;
}

/**
 * 把余弦相似度夹到 [0, 1] 再当横条宽度。
 *
 * 余弦相似度的理论范围是 [-1, 1]：负数表示方向相反，此时横条长度应当是 0
 * 而不是负宽度。夹一下既避免非法 CSS，也让「不相似」看起来就是不相似。
 */
function meterWidth(similarity: number): string {
  const clamped = Math.max(0, Math.min(1, similarity));
  return `${(clamped * 100).toFixed(1)}%`;
}

/**
 * 检索过程摘要。默认收起，而且**只有后端真的返回了 retrieval 才渲染**。
 *
 * 用原生 `<details>` 而不是自己写展开状态：默认收起所以不抢回答正文的层级；
 * 键盘直接可操作；不依赖 JavaScript（禁用脚本时这段内容照样读得到）；
 * 也不用为此把它变成客户端组件、引入一份状态。
 *
 * 五步流水线只展示后端真正给出的数字，**一步都不编**：
 * 后端没有「向量召回多少条 / 关键词召回多少条」这种拆分，所以这里不显示；
 * 后端没有返回耗时和费用，所以也不显示。
 */
function RetrievalDetails({ retrieval }: { retrieval: RagRetrievalSummary }) {
  const steps = [
    { label: "查询扩展", value: retrieval.query_rewritten ? "已扩展" : "使用原问题" },
    { label: "检索表达", value: `${retrieval.query_count} 条表达` },
    { label: "初选候选", value: `${retrieval.candidates_considered} 条候选` },
    {
      label: "相关性精排",
      value: retrieval.rerank_applied ? "已执行" : "未执行，沿用融合排序",
    },
    { label: "最终采用", value: `${retrieval.final_count} 条资料` },
  ];

  return (
    <details className={styles.retrieval}>
      <summary className={styles.retrievalSummary}>查看检索过程</summary>
      <div className={styles.retrievalBody}>
        <p className={styles.retrievalNote}>
          以下数据说明系统如何筛选本次回答所用的资料，只用于过程核对，不代表答案置信度。
        </p>
        <ol className={styles.pipeline}>
          {steps.map((step) => (
            <li key={step.label} className={styles.step}>
              <span className={styles.stepLabel}>{step.label}</span>
              <span className={styles.stepValue}>{step.value}</span>
            </li>
          ))}
        </ol>
      </div>
    </details>
  );
}

/**
 * 非 ok 状态的提示。
 *
 * 两种都用琥珀色而不是红色：它们是**正常结果**，不是故障。
 * 把「诚实地说不知道」渲染成报警色，会让人误以为系统坏了，
 * 进而去排查一个并不存在的问题。
 *
 * 两种的区别值得说清楚：
 * - insufficient：确实检索到了资料，但不足以回答这个问题；
 * - no_knowledge：这一条都没检索到。
 *   这里**不说成「知识库是空的」**——那是一个更强的断言，而接口给出的只是
 *   「本次没有检索到任何切片」，两种原因都会导致它：库里确实还没有文档，
 *   或者文档都在但没有一段跟这个问题相关。所以两种情况都列出来，并给出下一步。
 */
function NonAnswerNotice({
  status,
  answer,
}: {
  status: Exclude<RagAnswerStatus, "ok">;
  answer: string;
}) {
  if (status === "insufficient") {
    return (
      <Notice tone="warning" tag="资料不足">
        {/* 文案来自后端，是它给的固定说明，不是模型自由发挥的 */}
        <p className={styles.noticeText}>{answer}</p>
        <p className={styles.noticeText}>
          检索到了相关资料，但不足以回答这个问题。为了不编造，这里如实说明。
          可以换个更贴近文档用词的说法再试。
        </p>
      </Notice>
    );
  }

  return (
    <Notice tone="warning" tag="没有检索到资料">
      <p className={styles.noticeText}>{answer}</p>
      <p className={styles.noticeText}>
        本次没有检索到任何可用于回答的知识切片。常见原因有两个：
        知识库里还没有相关文档，或者已有文档里没有一段与这个问题相关。
        可以先去「数据采集」确认知识库里有哪些文档，再换个说法提问。
      </p>
      <div className={styles.noticeActions}>
        <LinkButton href="/data/sources" variant="secondary">
          去数据采集查看文档
        </LinkButton>
      </div>
    </Notice>
  );
}

/**
 * 这条来源有没有向量分数。
 *
 * 混合检索之后，来源可能是**只被关键词命中**的：它没有向量距离，
 * distance / similarity 都是 null。写成类型谓词是为了让下面的分支
 * 能安全地调用 .toFixed()——不窄化的话 TypeScript 会（正确地）拦住我们。
 */
function hasVectorScore(
  source: RagSource,
): source is RagSource & { distance: number; similarity: number } {
  return source.distance !== null && source.similarity !== null;
}

/**
 * 检索参考资料列表。
 *
 * 每条展示四样东西，各有各的用途：
 * - **命中片段预览**：切片原文的摘要（后端截到 120 字），用来判断「这条到底相不相关」；
 * - 小节与文档名：用来回原文里找；
 * - 片段位置：同一份文档里的第几段；
 * - 命中方式与分数：说明这条是**怎么被找到的**，以及它在本批里的相对位置。
 *
 * 预览通常比回答本身更值得看——回答是模型的转述，预览才是原文。
 * 但它在外观上要**让位于回答**：淡色、小字、引文式的左边框，一眼看得出是从属信息。
 *
 * 三句话必须写在标题下面，因为它们是这一块最容易被误读的地方：
 * 1. 这些是**本次检索命中的资料**，不是「模型确认引用过的资料」；
 * 2. 排序来自混合检索与精排，分数只用于本次请求内的排序；
 * 3. 分数不是答案正确率；带「关键词召回」标签的来源**没有**向量相似度，
 *    那不是相似度为 0。
 */
function SourceList({ sources }: { sources: RagSource[] }) {
  return (
    <div className={styles.sources}>
      <h3 className={styles.sourcesTitle}>检索参考资料</h3>
      <p className={styles.sourcesNote}>
        按混合检索（向量 + 关键词）与精排的结果排序，是本次检索命中的知识库小节，
        不代表模型逐条引用过。片段为文档原文的截断摘录。
      </p>
      <p className={styles.sourcesNote}>
        标签说明这条资料的命中方式；分数只用于本次请求内的排序，
        不是答案的正确率或置信度。标着「关键词召回」的来源没有向量相似度可显示——
        那是「没有这个数」，不是相似度为 0。
      </p>

      <ol className={styles.sourceList}>
        {sources.map((source, index) => {
          const method = getRetrievalMethod(source);
          const parts = scoreParts(source);

          return (
            <li key={`${source.source_file}-${source.chunk_index}`} className={styles.source}>
              <div className={styles.sourceHead}>
                <span className={styles.rank}>#{index + 1}</span>
                <span className={styles.sectionTitle}>{source.section_title}</span>
                <span className={styles.documentTitle}>{source.document_title}</span>
              </div>

              {/* 预览是可选字段：后端老版本没有它时整块不渲染，不留空框。
                  纯文本渲染，绝不按 HTML / Markdown 执行 */}
              {source.preview ? (
                <p className={styles.preview} title="检索命中的文档原文（已截断）">
                  {source.preview}
                </p>
              ) : null}

              <div className={styles.sourceMeta}>
                <span className={styles.fileName}>{source.source_file}</span>
                <span className={styles.chunkIndex}>第 {source.chunk_index} 段</span>

                {/* 命中方式与精排状态：小型文本标签，含义由文字承担，不靠颜色 */}
                <span className={styles.tags}>
                  <span className={styles.tag}>{METHOD_LABEL[method]}</span>
                  {isScore(source.rerank_score) ? (
                    <span className={styles.tag}>已精排</span>
                  ) : null}
                </span>

                {/* 有向量分数才画横条，而且横条只属于相似度这一个量：
                    精排分和融合分不复用它——它们不是同一个尺度，
                    画成同一种条状图会让人以为可以直接比长短。 */}
                {hasVectorScore(source) ? (
                  <span
                    className={styles.similarity}
                    title={`余弦距离 ${source.distance.toFixed(4)}（越小越相似，仅用于本次请求内排序）`}
                  >
                    相似度
                    <span className={styles.meter} aria-hidden="true">
                      <span
                        className={styles.meterFill}
                        style={{ width: meterWidth(source.similarity) }}
                      />
                    </span>
                    <span className={styles.similarityValue}>
                      {source.similarity.toFixed(4)}
                    </span>
                  </span>
                ) : null}
              </div>

              {/* 原始分数：次级信息，等宽小字。它们量纲不同，
                  所以只并列罗列，既不相加也不做高低配色。 */}
              {parts.length > 0 ? (
                <p
                  className={styles.scores}
                  title="这些分数含义各不相同，只用于本次请求内的排序；不能互相比较，也不能相加"
                >
                  {parts.join(" · ")}
                </p>
              ) : null}
            </li>
          );
        })}
      </ol>
    </div>
  );
}

/**
 * 回答面板：按 status 决定渲染什么。
 *
 * status 是后端给的三种取值，页面**不看别的字段去猜**。
 * 这样后端调整检索策略时，页面不需要跟着改判断逻辑。
 *
 * 检索过程摘要在三种 status 下都会展示（只要后端给了 retrieval）：
 * 「资料不足」和「没有检索到」同样需要能解释「系统是怎么筛的」——
 * 尤其 no_knowledge 时，用户最想知道的正是「到底检索了没有、走了几步」。
 * 所以摘要不能跟着回答正文一起被提前 return 挡掉。
 */
export function KnowledgeAnswerPanel({ result }: { result: RagAnswerResponse }) {
  // 缺席（老后端）与 null（旧检索路径）都当成「没有摘要」
  const retrieval = result.retrieval ?? null;

  if (result.status !== "ok") {
    return (
      <>
        <NonAnswerNotice status={result.status} answer={result.answer} />
        {retrieval ? <RetrievalDetails retrieval={retrieval} /> : null}
      </>
    );
  }

  return (
    <>
      <section className={styles.card} aria-labelledby="kq-answer-heading">
        <h2 id="kq-answer-heading" className={styles.cardTitle}>
          知识库回答
        </h2>
        <p className={styles.cardCaption}>
          由模型依据下方检索到的知识文档生成，只复述文档里写过的内容。
        </p>

        {/* 纯文本渲染：保留换行，但绝不按 HTML / Markdown 执行 */}
        <p className={styles.answerText}>{result.answer}</p>

        {result.sources.length > 0 ? <SourceList sources={result.sources} /> : null}
      </section>

      {retrieval ? <RetrievalDetails retrieval={retrieval} /> : null}
    </>
  );
}
