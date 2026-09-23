/**
 * 知识文档上传与列表接口（POST / GET /api/v1/rag/documents）的客户端。
 *
 * 职责只有四件事：定义类型、发请求、把 HTTP 失败映射成页面能用的错误、返回响应。
 * 它不认识 React，也不做展示格式化——那样才能被单独复用。
 *
 * 与 rag-answer.ts 是**两条独立的链路**，不是一个客户端的两个方法：
 * - 那条是「问一句，拿一个回答」；
 * - 这条是「交一份文件，让它进知识库」，是**写**操作，会真的花 embedding 调用。
 * 两者的错误处理、参数形态（JSON vs multipart）都不同，合在一起只会互相牵扯。
 *
 * 安全约定：
 * - 只发文件与可选标题，不附带任何内部状态；
 * - 不打印文件正文，也不打印整份响应。
 */

/** 一次入库的动作。对应后端 KnowledgeIngestionResult.action。 */
export type RagDocumentUploadAction = "insert" | "update" | "skip";

/**
 * 一次上传的结果。
 *
 * embedded_chunks 是**这次真正花了多少钱**的那一项：
 * action 为 skip 时它必然是 0（内容没变，一次 embedding 都没调）。
 * 页面上值得把它显出来——否则用户会以为每次上传都在重复付费。
 */
export type RagDocumentUploadResult = {
  source_file: string;
  action: RagDocumentUploadAction;
  chunk_count: number;
  embedded_chunks: number;
};

/**
 * 知识库里的一份文档。
 *
 * 时间戳是 ISO 字符串（后端是 datetime，JSON 序列化后就是字符串）。
 * 这里刻意不收成 Date：收成 Date 就得在解析时决定时区语义，
 * 而展示格式化是页面的事。
 */
export type RagDocumentSummary = {
  source_file: string;
  document_title: string;
  chunk_count: number;
  created_at: string;
  updated_at: string;
};

export type RagDocumentListResponse = {
  documents: RagDocumentSummary[];
};

/** 后端监听的端口。前端固定跑在 3000，后端固定跑在 8000。 */
const API_PORT = "8000";
const ENDPOINT_PATH = "/api/v1/rag/documents";

/**
 * 上传体积上限，与后端 routes.MAX_UPLOAD_BYTES 一致（10 MiB）。
 *
 * 前端先拦一道只是为了少发一次注定 422 的请求（大文件白传一遍很慢），
 * **真正的把关仍在后端**——请求可以被绕过，服务端的上限才是上限。
 */
export const RAG_UPLOAD_MAX_BYTES = 10 * 1024 * 1024;

/**
 * 支持的文件类型，与后端 SUPPORTED_UPLOAD_TYPES 一致。
 * 不一致会出现「前端放行、后端 422」这种很难解释的现象，所以两边必须同源。
 *
 * docx / pdf 会被后端还原成 Markdown 再切片，所以对用户来说和 md 没有区别。
 */
export const RAG_DOCUMENT_SUPPORTED_EXTENSIONS = [
  ".md",
  ".txt",
  ".docx",
  ".pdf",
] as const;

/** 文档标题上限，与后端 MAX_DOCUMENT_TITLE_LENGTH 一致。 */
export const RAG_DOCUMENT_TITLE_MAX_LENGTH = 255;

/**
 * 后端 422 的 detail 是**按类别预定义、面向用户**的固定文案
 * （例如「文件不是合法的 UTF-8 文本，请另存为 UTF-8 编码后重新上传。」），
 * 所以这一条链路可以展示它——非 UTF-8 这种情况用户必须知道原因才改得动。
 *
 * 但 500 / 503 的 detail 仍是内部兜底的固定话术，一律不读（与 rag-answer.ts 一致）。
 * 另外 FastAPI 自己的参数校验失败会把 detail 给成**数组**，那不是给人看的话，
 * 所以下面只接受「长度合理的字符串」，其余一律退回通用文案。
 */
const MAX_DETAIL_CHARS = 200;

/** 页面可以直接展示的错误。区分类型是为了让 UI 选择不同的视觉语义。 */
export type RagDocumentsErrorKind = "network" | "rejected" | "server" | "invalid";

const ERROR_MESSAGE: Record<RagDocumentsErrorKind, string> = {
  network: "暂时无法连接后端服务，请确认服务已启动。",
  // 「被拒绝」是用户能自己修的（换个文件、换个编码），所以它有专门的颜色，
  // 不能和下面的服务故障混成一种。拿不到后端说明时才用这句兜底。
  rejected: "这个文件无法入库，请检查文件类型与编码后重试。",
  server: "知识库服务返回异常，请稍后重试。",
  invalid: "知识库服务返回的内容无法识别，请稍后重试。",
};

export class RagDocumentsError extends Error {
  readonly kind: RagDocumentsErrorKind;

  constructor(kind: RagDocumentsErrorKind, message?: string) {
    // rejected 允许带后端给的说明（见 MAX_DETAIL_CHARS 的说明）；
    // 其余三类只用固定文案，绝不把后端 detail 或异常原文拼进来。
    super(kind === "rejected" && message ? message : ERROR_MESSAGE[kind]);
    this.name = "RagDocumentsError";
    this.kind = kind;
  }
}

/**
 * 拼接后端地址。
 *
 * 用当前页面的协议和主机名 + 固定端口 8000，而不是写死 IP：
 * 从 localhost:3000 打开的页面会请求 localhost:8000，
 * 从 127.0.0.1:3000 打开的会请求 127.0.0.1:8000。
 * 这样既不会把某台机器的 IP 固化进代码，也顺带满足了后端的 CORS 白名单
 * （它是按来源逐个列出的，写死 IP 反而会被拦）。
 *
 * **只能在浏览器里调用**：服务端渲染时没有 window。
 */
function buildEndpointUrl(): string {
  const { protocol, hostname } = window.location;
  return `${protocol}//${hostname}:${API_PORT}${ENDPOINT_PATH}`;
}

/** fetch 被 AbortController 取消时抛的就是这个，用它把「取消」和「失败」分开。 */
export function isAbortError(error: unknown): boolean {
  return error instanceof Error && error.name === "AbortError";
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

// --------------------------------------------------------------------------
// 上传前的本地校验
//
// 抽成导出的纯函数而不是写在组件里：组件要拿它来提示、按钮要拿它来禁用、
// 提交前还要再判一次，三处各写一遍规则，早晚会漂。
// --------------------------------------------------------------------------

/** 取扩展名（小写、带点）。没有扩展名时返回空串。 */
export function fileExtension(name: string): string {
  const dot = name.lastIndexOf(".");
  // dot <= 0 涵盖两种情况：没有点；点在开头（`.gitignore` 这种，整体是文件名不是后缀）
  if (dot <= 0) return "";
  return name.slice(dot).toLowerCase();
}

/** 扩展名是否在支持范围内。 */
export function isSupportedDocumentName(name: string): boolean {
  return (RAG_DOCUMENT_SUPPORTED_EXTENSIONS as readonly string[]).includes(
    fileExtension(name),
  );
}

/**
 * 检查一个文件能不能上传，返回阻止它的原因（null 表示没问题）。
 *
 * 返回原因而不是布尔量，是为了让页面直接把它显示出来——
 * 「不能传」而不说为什么，用户只会反复重试同一个文件。
 */
export function describeUploadRejection(file: File): string | null {
  if (!isSupportedDocumentName(file.name)) {
    return `只支持 ${RAG_DOCUMENT_SUPPORTED_EXTENSIONS.join(" / ")} 文件，当前选的是「${file.name}」。`;
  }
  if (file.size === 0) {
    return "这个文件是空的，没有可入库的内容。";
  }
  if (file.size > RAG_UPLOAD_MAX_BYTES) {
    const limit = RAG_UPLOAD_MAX_BYTES / (1024 * 1024);
    return `文件过大，单个文件不能超过 ${limit} MiB。`;
  }
  return null;
}

// --------------------------------------------------------------------------
// 响应校验
// --------------------------------------------------------------------------

function isUploadAction(value: unknown): value is RagDocumentUploadAction {
  return value === "insert" || value === "update" || value === "skip";
}

function isUploadResult(value: unknown): value is RagDocumentUploadResult {
  if (!isRecord(value)) return false;
  return (
    typeof value.source_file === "string" &&
    isUploadAction(value.action) &&
    typeof value.chunk_count === "number" &&
    typeof value.embedded_chunks === "number"
  );
}

function isDocumentSummary(value: unknown): value is RagDocumentSummary {
  if (!isRecord(value)) return false;
  return (
    typeof value.source_file === "string" &&
    typeof value.document_title === "string" &&
    typeof value.chunk_count === "number" &&
    typeof value.created_at === "string" &&
    typeof value.updated_at === "string"
  );
}

function isDocumentListResponse(value: unknown): value is RagDocumentListResponse {
  if (!isRecord(value)) return false;
  if (!Array.isArray(value.documents)) return false;
  return value.documents.every(isDocumentSummary);
}

function extractRejectionDetail(payload: unknown): string | null {
  if (!isRecord(payload)) return null;
  const detail = payload.detail;
  // FastAPI 的参数校验失败会把 detail 给成数组，那不是给人看的话，直接弃用
  if (typeof detail !== "string") return null;
  const trimmed = detail.trim();
  if (!trimmed || trimmed.length > MAX_DETAIL_CHARS) return null;
  return trimmed;
}

async function readRejectionDetail(response: Response): Promise<string | null> {
  try {
    return extractRejectionDetail(await response.json());
  } catch {
    return null;
  }
}

// --------------------------------------------------------------------------
// 接口调用
// --------------------------------------------------------------------------

/**
 * 上传一份知识文档，让后端切片、向量化后入库。
 *
 * 幂等由后端保证，所以重复上传同一份文件是安全的：内容没变时
 * 返回的 action 是 "skip"，一次 embedding 都不会调。
 *
 * signal 用于「取消本次上传」：取消时 fetch 会抛 AbortError，
 * 这里**原样往上抛**——取消是用户的正常操作，不该被包装成服务故障。
 */
export async function uploadDocument(
  file: File,
  title?: string,
  signal?: AbortSignal,
): Promise<RagDocumentUploadResult> {
  const form = new FormData();
  // 第三个参数显式给文件名：不写的话浏览器会用它自己的默认值，
  // 而文件名正是后端用来判定类型、做幂等主键的东西。
  form.append("file", file, file.name);

  const trimmedTitle = title?.trim();
  if (trimmedTitle) {
    form.append("title", trimmedTitle);
  }

  let response: Response;
  try {
    response = await fetch(buildEndpointUrl(), {
      method: "POST",
      // **不要手写 Content-Type**：multipart 的分隔符边界由浏览器生成，
      // 手写成 "multipart/form-data" 会缺 boundary，后端直接解析失败。
      body: form,
      signal,
    });
  } catch (error) {
    if (isAbortError(error)) throw error;
    throw new RagDocumentsError("network");
  }

  if (!response.ok) {
    if (response.status === 422) {
      // 这一档的 detail 是后端按类别预定义的、面向用户的说明，可以展示
      throw new RagDocumentsError("rejected", (await readRejectionDetail(response)) ?? undefined);
    }
    throw new RagDocumentsError("server");
  }

  let payload: unknown;
  try {
    payload = await response.json();
  } catch {
    throw new RagDocumentsError("invalid");
  }

  if (!isUploadResult(payload)) {
    throw new RagDocumentsError("invalid");
  }

  return payload;
}

/**
 * 列出知识库里已有的文档，最近更新的排在最前。
 *
 * 空知识库返回空数组，而不是错误——页面上要显示成「还没有文档」。
 */
export async function listDocuments(
  signal?: AbortSignal,
): Promise<RagDocumentListResponse> {
  let response: Response;

  try {
    response = await fetch(buildEndpointUrl(), { method: "GET", signal });
  } catch (error) {
    if (isAbortError(error)) throw error;
    throw new RagDocumentsError("network");
  }

  if (!response.ok) {
    throw new RagDocumentsError("server");
  }

  let payload: unknown;
  try {
    payload = await response.json();
  } catch {
    throw new RagDocumentsError("invalid");
  }

  if (!isDocumentListResponse(payload)) {
    throw new RagDocumentsError("invalid");
  }

  return payload;
}
