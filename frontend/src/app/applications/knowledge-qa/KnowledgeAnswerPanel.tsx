import { LinkButton } from "@/components/ui/Button";
import { Notice } from "@/components/ui/Notice";
import type {
  RagAnswerResponse,
  RagAnswerStatus,
  RagSource,
} from "@/lib/api/rag-answer";

import styles from "./knowledge-qa.module.css";

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
 * 检索参考资料列表。
 *
 * 每条展示四样东西，各有各的用途：
 * - **命中片段预览**：切片原文的摘要（后端截到 120 字），用来判断「这条到底相不相关」；
 * - 小节与文档名：用来回原文里找；
 * - 片段位置：同一份文档里的第几段；
 * - 相似度：用来横向比较这一批结果的相对好坏。
 *
 * 预览通常比回答本身更值得看——回答是模型的转述，预览才是原文。
 * 但它在外观上要**让位于回答**：淡色、小字、引文式的左边框，一眼看得出是从属信息。
 *
 * 两句话必须写在标题下面，因为它们是这一块最容易被误读的地方：
 * 1. 这些是**本次检索命中的资料**，不是「模型确认引用过的资料」；
 * 2. 相似度是**检索排序用的相对分数**，不是答案正确率或置信度。
 */
function SourceList({ sources }: { sources: RagSource[] }) {
  return (
    <div className={styles.sources}>
      <h3 className={styles.sourcesTitle}>检索参考资料</h3>
      <p className={styles.sourcesNote}>
        按检索相似度从高到低排列，是本次检索命中的知识库小节，不代表模型逐条引用过。
        片段为文档原文的截断摘录。
      </p>
      <p className={styles.sourcesNote}>
        相似度表示片段与问题的接近程度，只用于比较同一批结果的相对好坏，
        不是答案的正确率或置信度。
      </p>

      <ol className={styles.sourceList}>
        {sources.map((source, index) => (
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
              <span
                className={styles.similarity}
                title={`余弦距离 ${source.distance.toFixed(4)}（越小越相似）`}
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
            </div>
          </li>
        ))}
      </ol>
    </div>
  );
}

/**
 * 回答面板：按 status 决定渲染什么。
 *
 * status 是后端给的三种取值，页面**不看别的字段去猜**。
 * 这样后端调整检索策略时，页面不需要跟着改判断逻辑。
 */
export function KnowledgeAnswerPanel({ result }: { result: RagAnswerResponse }) {
  if (result.status !== "ok") {
    return <NonAnswerNotice status={result.status} answer={result.answer} />;
  }

  return (
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
  );
}
