import { buildApiUrl } from "./http";

export type BusinessAnalysisEvent =
  | { type: "run_started"; run_id: string }
  | { type: "status"; label: string }
  | { type: "tool_started"; tool: string }
  | { type: "tool_completed"; tool: string; summary?: string }
  | { type: "report_delta"; content: string }
  | { type: "run_completed"; run_id: string; report_id?: string }
  | { type: "error"; error_code: string };

export type BusinessAnalysisInput = {
  threadId: string;
  message: string;
  userId?: string;
};

const EVENT_TYPES = new Set<BusinessAnalysisEvent["type"]>([
  "run_started",
  "status",
  "tool_started",
  "tool_completed",
  "report_delta",
  "run_completed",
  "error",
]);

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function parseFrame(frame: string): BusinessAnalysisEvent | null {
  let eventType = "";
  let data = "";
  for (const line of frame.split("\n")) {
    if (line.startsWith("event:")) eventType = line.slice(6).trim();
    if (line.startsWith("data:")) data += line.slice(5).trim();
  }
  if (!EVENT_TYPES.has(eventType as BusinessAnalysisEvent["type"])) return null;
  try {
    const parsed: unknown = JSON.parse(data);
    if (!isRecord(parsed)) return null;
    return {
      ...parsed,
      type: eventType,
    } as BusinessAnalysisEvent;
  } catch {
    return null;
  }
}

export function parseSseChunk(chunk: string): BusinessAnalysisEvent[] {
  return chunk
    .split("\n\n")
    .filter((frame) => frame.trim().length > 0)
    .map(parseFrame)
    .filter((event): event is BusinessAnalysisEvent => event !== null);
}

export function createAnonymousUserId(): string {
  const key = "ai_data_platform_user_id";
  try {
    const existing = window.localStorage.getItem(key);
    if (existing) return existing;
    const created = crypto.randomUUID();
    window.localStorage.setItem(key, created);
    return created;
  } catch {
    return crypto.randomUUID();
  }
}

export async function runBusinessAnalysis(
  input: BusinessAnalysisInput,
  signal: AbortSignal,
  onEvent: (event: BusinessAnalysisEvent) => void,
): Promise<void> {
  const response = await fetch(buildApiUrl("/api/v1/agent/business-analysis/runs"), {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
    body: JSON.stringify({
      thread_id: input.threadId,
      message: input.message,
      user_id: input.userId,
    }),
    signal,
  });
  if (!response.ok) {
    throw new Error(`经营分析请求失败（${response.status}）。`);
  }
  if (!response.body) throw new Error("经营分析服务没有返回事件流。");

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  while (true) {
    const { done, value } = await reader.read();
    buffer += decoder.decode(value, { stream: !done });
    const boundary = buffer.lastIndexOf("\n\n");
    if (boundary >= 0) {
      for (const event of parseSseChunk(buffer.slice(0, boundary + 2))) onEvent(event);
      buffer = buffer.slice(boundary + 2);
    }
    if (done) break;
  }
  if (buffer.trim()) {
    for (const event of parseSseChunk(`${buffer}\n\n`)) onEvent(event);
  }
}
