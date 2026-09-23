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
  /** 余弦距离，越小越相似。 */
  distance: number;
  /** 1 - distance，余弦相似度。 */
  similarity: number;
};

export type RagAnswerResponse = {
  status: RagAnswerStatus;
  answer: string;
  sources: RagSource[];
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

function isSource(value: unknown): value is RagSource {
  if (!isRecord(value)) return false;
  if (
    typeof value.source_file !== "string" ||
    typeof value.document_title !== "string" ||
    typeof value.section_title !== "string" ||
    typeof value.chunk_index !== "number" ||
    !Number.isFinite(value.distance) ||
    !Number.isFinite(value.similarity)
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
 */
function isRagAnswerResponse(value: unknown): value is RagAnswerResponse {
  if (!isRecord(value)) return false;
  if (!isStatus(value.status)) return false;
  if (typeof value.answer !== "string") return false;
  if (!Array.isArray(value.sources)) return false;
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
