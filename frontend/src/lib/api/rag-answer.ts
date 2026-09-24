/**
 * 知识库问答接口（POST /api/v1/rag/answer）的客户端。
 *
 * 职责只有四件事：定义类型、发请求、把 HTTP 失败映射成页面能用的错误、返回响应。
 * 它不认识 React，也不做任何展示格式化——那样才能被单独复用。
 *
 * 与 agent-data-query.ts 是**两条独立的链路**，不是一个客户端的两个方法：
 * - 那条问「销售额是多少」，去查数据库算数；
 * - 这条问「销售额怎么算」，去查知识库文档。
 * 两者的错误文案、参数、响应结构都不同，合在一起只会互相牵扯。
 *
 * 安全约定（与智能问数客户端一致）：
 * - 只发 question 和 top_k，不附带任何内部状态；
 * - 不把后端返回的 detail 原样交给页面（那是内部信息）；
 * - 不打印问题全文，也不打印整份响应。
 */

/** 拼接后端地址、取消判断、对象判断都来自 ./http，三个客户端共用一份。 */
import { buildApiUrl, isAbortError, isRecord } from "./http";

/** 三种结果状态，与后端 app/services/rag_answer.py 的定义一一对应。 */
export type RagAnswerStatus = "ok" | "insufficient" | "no_knowledge";

/**
 * 一条资料来源。
 *
 * preview 是**检索命中的切片正文摘要**（后端截到 120 字），不是模型生成的。
 * 它让用户能核对「这条来源到底写了什么」，所以是来源列表里最有价值的一项。
 *
 * 为什么标成可选？因为后端是老版本时（没有 preview 字段），
 * 我们希望**降级成不显示预览**，而不是让整个响应被判为「无法识别」——
 * 预览只是显示增强，answer 和其它来源字段才是主体，不该被一个装饰性字段拖垮。
 */
export type RagSource = {
  source_file: string;
  document_title: string;
  section_title: string;
  chunk_index: number;
  preview?: string;
  /**
   * 余弦距离，越小越相似；**可能是 null**。
   *
   * 混合检索之后，一条来源完全可能只被关键词找到——它没有向量距离，
   * 这时这里是 null。**不是 0**：0 的含义是「做过向量检索、而且完全不相关」，
   * 而 null 的含义是「压根没参与向量检索」。展示时必须区分这两件事，
   * 否则用户会看到「相似度 0.0000」却排在前面，越看越糊涂。
   */
  distance: number | null;
  /** 1 - distance，余弦相似度；语义与可空规则同 distance。 */
  similarity: number | null;
  /**
   * 混合检索之后才知道的三个分数。老后端没有这三个字段，所以全部可选。
   *
   * 它们**量纲各不相同**，谁也不能和谁比大小、更不能相加：
   * - `keyword_score`：关键词那一路内部的命中层级分（我们自己定的序数）；
   * - `rrf_score`：名次倒数累加出来的融合分（两路都命中才累加）；
   * - `rerank_score`：精排模型给的请求内相对分。
   *
   * 注意 `rrf_score` / `rerank_score` 存在与否**不能**反推「这条来自哪种召回」：
   * 它们是融合与精排的产物，跟初始召回路径无关。判定召回方式只看
   * distance/similarity 与 keyword_score（见下面的 getRetrievalMethod）。
   */
  keyword_score?: number | null;
  rrf_score?: number | null;
  rerank_score?: number | null;
};

/**
 * 一条来源是被哪一路召回找出来的。
 *
 * 判据**只有**两组字段：
 * - `distance` 与 `similarity` 同时是有效数字 → 向量召回命中了它；
 * - `keyword_score` 是有效数字 → 关键词召回命中了它。
 *
 * 刻意**不看** `rrf_score` / `rerank_score` / 排名：它们是融合与精排的产物，
 * 一条只被关键词命中的切片照样会有 `rrf_score` 和 `rerank_score`。靠它们
 * 反推召回来源，会把「关键词召回」误报成「混合召回」——而使用者看这个标签，
 * 正是想知道「系统是凭什么找到这条的」。
 *
 * 放在这里而不是展示组件里，是因为这是「怎么读这几个字段」的领域知识，
 * 和上面的字段说明是同一件事；顺带也让它可以被单独验证。
 */
export type RetrievalMethod = "vector" | "keyword" | "hybrid" | "unknown";

/** 一个分数是否真的存在：缺席、null、坏值都算「没有」。 */
function isPresentScore(value: number | null | undefined): value is number {
  return typeof value === "number" && Number.isFinite(value);
}

export function getRetrievalMethod(source: RagSource): RetrievalMethod {
  const byVector = isPresentScore(source.distance) && isPresentScore(source.similarity);
  const byKeyword = isPresentScore(source.keyword_score);

  if (byVector && byKeyword) return "hybrid";
  if (byVector) return "vector";
  if (byKeyword) return "keyword";
  // 两组都没有：老后端的响应，或者两路都没留下分数。
  // 这不是错误，给一个中性说法，不编造来源。
  return "unknown";
}

/**
 * 一次检索的过程统计，对应后端的 `retrieval` 字段。
 *
 * 五个字段回答的都是「这次检索干了什么」，没有一个是「检索到了什么」
 * ——后者在 sources 里。它们全是计数和布尔值，不含任何正文、Prompt、
 * 向量或内部主键，所以可以安全地展示给使用者。
 *
 * 老版本后端（RAG-13.6 之前）完全没有这个字段；走旧纯向量检索路径时
 * 它会是 null。两种都必须兼容：没有就不展示，而不是当成错误。
 */
export type RagRetrievalSummary = {
  /** 是否做过查询扩展（改写出一问之外的其他检索表达）。 */
  query_rewritten: boolean;
  /** 本次一共用了几条检索表达。 */
  query_count: number;
  /** 融合之后、精排之前有多少条候选。 */
  candidates_considered: number;
  /** **本次请求**是否真的执行了精排并拿到分数（不是「功能开着」）。 */
  rerank_applied: boolean;
  /** 最终交给回答模型的资料条数。 */
  final_count: number;
};

export type RagAnswerResponse = {
  status: RagAnswerStatus;
  answer: string;
  sources: RagSource[];
  /** 检索过程统计；老后端没有这个字段，旧检索路径为 null。 */
  retrieval?: RagRetrievalSummary | null;
};

/**
 * 问题长度上限，与后端 RagAnswerRequest 的 max_length 一致（它复用了问数的 500）。
 * 前端先拦一道只是为了少发一次注定 422 的请求，真正的把关仍在后端。
 */
export const RAG_QUESTION_MAX_LENGTH = 500;

/**
 * top_k 的取值区间，与后端 knowledge_search 的 MIN_TOP_K / MAX_TOP_K 一致。
 * 不一致会出现「前端放行、后端 422」这种很难解释的现象，所以两边必须同源。
 */
export const RAG_MIN_TOP_K = 1;
export const RAG_MAX_TOP_K = 10;
export const RAG_DEFAULT_TOP_K = 3;

/** 页面可以直接展示的错误。区分类型是为了让 UI 选择不同的视觉语义。 */
export type RagAnswerErrorKind = "network" | "server" | "invalid";

const ERROR_MESSAGE: Record<RagAnswerErrorKind, string> = {
  network: "暂时无法连接知识库问答服务，请确认后端服务已启动。",
  server: "知识库问答服务返回异常，请稍后重试。",
  invalid: "知识库问答服务返回的内容无法识别，请稍后重试。",
};

export class RagAnswerError extends Error {
  readonly kind: RagAnswerErrorKind;

  constructor(kind: RagAnswerErrorKind) {
    // 只用固定的中文文案，绝不把后端的 detail 或异常原文拼进来
    super(ERROR_MESSAGE[kind]);
    this.name = "RagAnswerError";
    this.kind = kind;
  }
}

function isStatus(value: unknown): value is RagAnswerStatus {
  return value === "ok" || value === "insufficient" || value === "no_knowledge";
}

/**
 * 一个「数字或 null」字段的校验。
 *
 * null 是**合法值**（表示没有这个数）；数字必须有限。
 * NaN / Infinity / 字符串 / undefined 一律非法——它们不是「没有」，
 * 而是「后端给了个不该给的东西」，那种情况要报出来，不能当成 null 混过去。
 */
function isFiniteNumberOrNull(value: unknown): value is number | null {
  return value === null || (typeof value === "number" && Number.isFinite(value));
}

/**
 * 「数字、null 或缺席」都合法——混合检索新增的那三个可选分数字段用的规则。
 *
 * 缺席（undefined）是老后端的情况，null 是新后端「这条来源没有这个分数」的
 * 情况，两者都表示「没有这个数」。但给了别的（字符串 / NaN / Infinity /
 * 数组 / 对象）就是契约被改坏了：**不能静默当成 null**。
 * 把坏值悄悄抹平，等于让界面一直显示「没有分数」，而真正的问题
 * ——后端在发垃圾——再也不会有人发现。
 */
function isFiniteNumberOrNullOrUndefined(
  value: unknown,
): value is number | null | undefined {
  return value === undefined || isFiniteNumberOrNull(value);
}

/**
 * 非负整数。
 *
 * `Number.isInteger` 一次排掉了 NaN、Infinity、小数，`typeof` 排掉了字符串和
 * 布尔。计数字段用这一条而不是「是个数字就行」：负数和小数说明后端算错了，
 * 而「-1 条候选」这种值看起来像数字，最容易被顺手放过去。
 */
function isNonNegativeInteger(value: unknown): value is number {
  return typeof value === "number" && Number.isInteger(value) && value >= 0;
}

/**
 * 校验检索过程统计。
 *
 * 只校验形状，不校验字段之间的约定（比如「最终条数不该超过候选数」）——
 * 那是后端的算术，前端把它当硬约束，只会让后端将来合法地调整一下
 * 就让整个响应被判为「无法识别」。
 */
function isRetrievalSummary(value: unknown): value is RagRetrievalSummary {
  if (!isRecord(value)) return false;
  return (
    typeof value.query_rewritten === "boolean" &&
    typeof value.rerank_applied === "boolean" &&
    isNonNegativeInteger(value.query_count) &&
    isNonNegativeInteger(value.candidates_considered) &&
    isNonNegativeInteger(value.final_count)
  );
}

function isSource(value: unknown): value is RagSource {
  if (!isRecord(value)) return false;
  if (
    typeof value.source_file !== "string" ||
    typeof value.document_title !== "string" ||
    typeof value.section_title !== "string" ||
    typeof value.chunk_index !== "number" ||
    // 距离与相似度可以是 null（关键词独占的来源没有向量分数），
    // 但给了数字就必须是有限数。
    !isFiniteNumberOrNull(value.distance) ||
    !isFiniteNumberOrNull(value.similarity) ||
    // 这三个是老后端没有、新后端可能为 null 的可选分数
    !isFiniteNumberOrNullOrUndefined(value.keyword_score) ||
    !isFiniteNumberOrNullOrUndefined(value.rrf_score) ||
    !isFiniteNumberOrNullOrUndefined(value.rerank_score)
  ) {
    return false;
  }
  // preview 可以缺席（后端老版本），但一旦出现就必须是字符串——
  // 类型不对说明契约被改坏了，那种情况要报出来，不能悄悄当空串。
  if (value.preview !== undefined && typeof value.preview !== "string") {
    return false;
  }
  return true;
}

/**
 * 校验响应形状。
 *
 * 只校验**类型**，不校验「status 不是 ok 时 sources 必须为空」这类跨字段约定。
 * 那个约定是后端的设计，由页面按 status 决定渲染什么来兜住——
 * 客户端如果把它当成硬约束，后端将来合法地调整一下就会让整个页面报「无法识别」。
 *
 * 导出是为了能被直接验证：它是一个纯函数，一份输入一份输出，
 * 不需要渲染页面就能断言「distance 为 null 的响应能不能通过」。
 */
export function isRagAnswerResponse(value: unknown): value is RagAnswerResponse {
  if (!isRecord(value)) return false;
  if (!isStatus(value.status)) return false;
  if (typeof value.answer !== "string") return false;
  if (!Array.isArray(value.sources)) return false;
  // retrieval 三种形态都合法：缺席（老后端）、null（旧检索路径）、完整对象。
  // 只有它真的给了东西、且不是 null 的时候才校验形状。
  if (
    value.retrieval !== undefined &&
    value.retrieval !== null &&
    !isRetrievalSummary(value.retrieval)
  ) {
    return false;
  }
  return value.sources.every(isSource);
}

/**
 * 提交一个问题，返回基于知识库的回答。
 *
 * signal 用于「取消本次请求」：取消时 fetch 会抛 AbortError，
 * 这里**原样往上抛**——取消是用户的正常操作，不该被包装成服务故障。
 */
export async function askKnowledge(
  question: string,
  topK: number = RAG_DEFAULT_TOP_K,
  signal?: AbortSignal,
): Promise<RagAnswerResponse> {
  let response: Response;

  try {
    response = await fetch(buildApiUrl("/api/v1/rag/answer"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      // 只发这两个字段：请求体里出现别的字段就说明有地方越界了
      body: JSON.stringify({ question, top_k: topK }),
      signal,
    });
  } catch (error) {
    if (isAbortError(error)) throw error;
    throw new RagAnswerError("network");
  }

  if (!response.ok) {
    // 刻意不读 response.json() 里的 detail：那是后端内部信息，
    // 页面只需要知道「服务这次没给出可用结果」。
    throw new RagAnswerError("server");
  }

  let payload: unknown;
  try {
    payload = await response.json();
  } catch {
    throw new RagAnswerError("invalid");
  }

  if (!isRagAnswerResponse(payload)) {
    throw new RagAnswerError("invalid");
  }

  return payload;
}
