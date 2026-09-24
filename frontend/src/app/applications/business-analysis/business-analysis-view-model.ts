import type {
  AnalysisThreadRun,
  BusinessAnalysisEvent,
} from "@/lib/api/business-analysis";

export type ChatMessageStatus = "complete" | "streaming" | "error" | "cancelled";

export type ChatMessage = {
  id: string;
  role: "user" | "assistant";
  content: string;
  status: ChatMessageStatus;
  statusText?: string;
};

/**
 * 对话状态模型：把 SSE 事件和历史运行记录收敛成一份消息流。
 *
 * 这里只做纯计算，不碰网络和 React——工作区负责何时调用、组件负责怎么显示。
 * 状态文案集中在此处定义，避免同一句话在多个组件里各写一遍。
 */

export const CANCELLED_STATUS_TEXT = "已停止生成";
export const EMPTY_REPORT_TEXT = "分析已完成，但没有返回可展示的内容。";
export const INCOMPLETE_STREAM_TEXT = "连接已结束，但没有收到完整分析结果，请重试。";
/** 请求在 SSE 之前就失败了（网络中断、非 2xx）。 */
export const GENERIC_ERROR_TEXT = "本次分析未完成，请稍后重试。";

const RUN_STARTED_TEXT = "正在理解你的问题…";
const TOOL_COMPLETED_TEXT = "正在整理分析结果…";
const REPORT_DELTA_TEXT = "正在生成分析回答…";
const FALLBACK_STATUS_TEXT = "正在分析…";

/** 工具名 → 动态状态。未列出的工具统一落到兜底文案。 */
const TOOL_STATUS_TEXT: Record<string, string> = {
  analyze_business_data: "正在查询经营数据…",
  search_business_knowledge: "正在检索业务知识…",
  get_metric_definition: "正在核对指标口径…",
};

const ERROR_STATUS_TEXT: Record<string, string> = {
  AGENT_CONFIGURATION_ERROR: "模型服务尚未配置，请检查模型配置。",
  AGENT_RUN_TIMEOUT: "本次分析超时，请缩小问题范围后重试。",
  AGENT_RUN_LIMIT_REACHED: "本次分析步骤过多，请将问题拆分后重试。",
};

function describeErrorCode(code: string): string {
  return ERROR_STATUS_TEXT[code] ?? GENERIC_ERROR_TEXT;
}

/**
 * 数据库里保存的运行状态 → 消息状态。
 *
 * `running` 只可能来自中途中断的进程，历史里读到它说明那次分析没有收尾，
 * 因此和 `failed` 一样按未完成处理，而不是假装它还在进行。
 */
function restoreStatus(status: string): {
  status: ChatMessageStatus;
  statusText?: string;
} {
  if (status === "completed") return { status: "complete" };
  if (status === "cancelled") {
    return { status: "cancelled", statusText: CANCELLED_STATUS_TEXT };
  }
  if (status === "timeout") {
    return { status: "error", statusText: ERROR_STATUS_TEXT.AGENT_RUN_TIMEOUT };
  }
  return { status: "error", statusText: GENERIC_ERROR_TEXT };
}

function reportSummary(run: AnalysisThreadRun): string {
  const summary = run.report?.summary;
  return typeof summary === "string" ? summary.trim() : "";
}

/**
 * 把后端的运行记录还原成完整消息流。
 *
 * 后端按 `updated_at DESC` 返回（最新在前），这里翻成最早在前，
 * 否则恢复出来的对话会颠三倒四。
 */
export function createMessagesFromRuns(runs: AnalysisThreadRun[]): ChatMessage[] {
  const messages: ChatMessage[] = [];
  for (const run of [...runs].reverse()) {
    const summary = reportSummary(run);
    const { status, statusText } = restoreStatus(run.status);
    messages.push({
      id: `user-${run.id}`,
      role: "user",
      content: run.title,
      status: "complete",
    });
    messages.push({
      id: `assistant-${run.id}`,
      role: "assistant",
      // 只有「成功但没有报告」才需要解释；失败的运行不该伪造正文。
      content: summary || (status === "complete" ? EMPTY_REPORT_TEXT : ""),
      status,
      ...(statusText ? { statusText } : {}),
    });
  }
  return messages;
}

/** 把一条 SSE 事件叠加到正在生成的 Agent 消息上。 */
export function reduceAssistantEvent(
  message: ChatMessage,
  event: BusinessAnalysisEvent,
): ChatMessage {
  switch (event.type) {
    case "run_started":
      return { ...message, status: "streaming", statusText: RUN_STARTED_TEXT };
    case "status":
      return {
        ...message,
        status: "streaming",
        statusText: event.label.trim() || FALLBACK_STATUS_TEXT,
      };
    case "tool_started":
      return {
        ...message,
        status: "streaming",
        statusText: TOOL_STATUS_TEXT[event.tool] ?? FALLBACK_STATUS_TEXT,
      };
    case "tool_completed":
      return { ...message, status: "streaming", statusText: TOOL_COMPLETED_TEXT };
    case "report_delta":
      return {
        ...message,
        content: message.content + event.content,
        status: "streaming",
        statusText: REPORT_DELTA_TEXT,
      };
    case "run_completed":
      return {
        ...message,
        content: message.content.trim() ? message.content : EMPTY_REPORT_TEXT,
        status: "complete",
        statusText: undefined,
      };
    case "error":
      return {
        ...message,
        status: "error",
        statusText: describeErrorCode(event.error_code),
      };
  }
}
