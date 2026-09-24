import { describe, expect, it } from "vitest";

import type {
  AnalysisThreadRun,
  BusinessAnalysisEvent,
} from "@/lib/api/business-analysis";

import {
  CANCELLED_STATUS_TEXT,
  createMessagesFromRuns,
  reduceAssistantEvent,
  type ChatMessage,
} from "./business-analysis-view-model";

function run(overrides: Partial<AnalysisThreadRun> = {}): AnalysisThreadRun {
  return {
    id: "run-1",
    thread_id: "thread-1",
    title: "分析华东第三季度销售下降原因",
    status: "completed",
    report: { summary: "## 结论\n\n华东下滑主要来自空调品类。" },
    ...overrides,
  };
}

function assistant(overrides: Partial<ChatMessage> = {}): ChatMessage {
  return {
    id: "assistant-run-1",
    role: "assistant",
    content: "",
    status: "streaming",
    ...overrides,
  };
}

describe("createMessagesFromRuns", () => {
  it("reverses the newest-first backend order into oldest-first", () => {
    const messages = createMessagesFromRuns([
      run({ id: "newest", title: "第二个问题" }),
      run({ id: "oldest", title: "第一个问题" }),
    ]);

    expect(messages.map((message) => message.content)).toEqual([
      "第一个问题",
      "## 结论\n\n华东下滑主要来自空调品类。",
      "第二个问题",
      "## 结论\n\n华东下滑主要来自空调品类。",
    ]);
  });

  it("turns every run into one user message and one assistant message", () => {
    const messages = createMessagesFromRuns([run()]);

    expect(messages).toHaveLength(2);
    expect(messages[0]).toMatchObject({ role: "user", status: "complete" });
    expect(messages[1]).toMatchObject({ role: "assistant", status: "complete" });
  });

  it("uses the run title as the user message and the report summary as the reply", () => {
    const [user, reply] = createMessagesFromRuns([run()]);

    expect(user.content).toBe("分析华东第三季度销售下降原因");
    expect(reply.content).toBe("## 结论\n\n华东下滑主要来自空调品类。");
  });

  it("keeps message ids stable and unique per run", () => {
    const messages = createMessagesFromRuns([
      run({ id: "b" }),
      run({ id: "a" }),
    ]);

    expect(new Set(messages.map((message) => message.id)).size).toBe(4);
    expect(messages.map((message) => message.id)).toEqual([
      "user-a",
      "assistant-a",
      "user-b",
      "assistant-b",
    ]);
  });

  it("explains a completed run that stored no report", () => {
    const [, reply] = createMessagesFromRuns([
      run({ status: "completed", report: null }),
    ]);

    expect(reply.status).toBe("complete");
    expect(reply.content).toBe("分析已完成，但没有返回可展示的内容。");
  });

  it("restores failed, timed out and cancelled runs with readable Chinese", () => {
    const [, failed] = createMessagesFromRuns([run({ id: "f", status: "failed", report: null })]);
    const [, timedOut] = createMessagesFromRuns([run({ id: "t", status: "timeout", report: null })]);
    const [, cancelled] = createMessagesFromRuns([run({ id: "c", status: "cancelled", report: null })]);

    expect(failed).toMatchObject({ status: "error", statusText: "本次分析未完成，请稍后重试。" });
    expect(timedOut).toMatchObject({ status: "error", statusText: "本次分析超时，请缩小问题范围后重试。" });
    expect(cancelled).toMatchObject({ status: "cancelled", statusText: CANCELLED_STATUS_TEXT });
  });

  it("returns an empty list when the thread has no runs", () => {
    expect(createMessagesFromRuns([])).toEqual([]);
  });
});

describe("reduceAssistantEvent", () => {
  it("appends report deltas in arrival order without dropping earlier content", () => {
    const first = reduceAssistantEvent(assistant(), {
      type: "report_delta",
      content: "## 结论",
    });
    const second = reduceAssistantEvent(first, {
      type: "report_delta",
      content: "\n\n华东下滑 12%。",
    });

    expect(second.content).toBe("## 结论\n\n华东下滑 12%。");
  });

  it("annotates report deltas with a generating status", () => {
    const next = reduceAssistantEvent(assistant(), { type: "report_delta", content: "x" });

    expect(next.status).toBe("streaming");
    expect(next.statusText).toBe("正在生成分析回答…");
  });

  it("maps every tool event to one dynamic status sentence", () => {
    const statuses = [
      [{ type: "run_started", run_id: "r1" }, "正在理解你的问题…"],
      [{ type: "tool_started", tool: "analyze_business_data" }, "正在查询经营数据…"],
      [{ type: "tool_started", tool: "search_business_knowledge" }, "正在检索业务知识…"],
      [{ type: "tool_started", tool: "get_metric_definition" }, "正在核对指标口径…"],
      [{ type: "tool_completed", tool: "analyze_business_data" }, "正在整理分析结果…"],
      [{ type: "tool_started", tool: "save_analysis_report" }, "正在分析…"],
    ] as const;

    for (const [event, expected] of statuses) {
      const next = reduceAssistantEvent(assistant(), event as BusinessAnalysisEvent);
      expect(next.statusText).toBe(expected);
      expect(next.status).toBe("streaming");
    }
  });

  it("keeps tool statuses from touching the answer body", () => {
    const next = reduceAssistantEvent(
      assistant({ content: "已有内容" }),
      { type: "tool_started", tool: "analyze_business_data" },
    );

    expect(next.content).toBe("已有内容");
  });

  it("marks the message complete on run_completed", () => {
    const next = reduceAssistantEvent(
      assistant({ content: "## 结论" }),
      { type: "run_completed", run_id: "r1" },
    );

    expect(next.status).toBe("complete");
    expect(next.statusText).toBeUndefined();
    expect(next.content).toBe("## 结论");
  });

  it("explains a completed run that streamed no report content", () => {
    const next = reduceAssistantEvent(assistant(), {
      type: "run_completed",
      run_id: "r1",
    });

    expect(next.status).toBe("complete");
    expect(next.content).toBe("分析已完成，但没有返回可展示的内容。");
  });

  it("turns error codes into readable Chinese without discarding partial answers", () => {
    const cases = [
      ["AGENT_CONFIGURATION_ERROR", "模型服务尚未配置，请检查模型配置。"],
      ["AGENT_RUN_TIMEOUT", "本次分析超时，请缩小问题范围后重试。"],
      ["AGENT_RUN_LIMIT_REACHED", "本次分析步骤过多，请将问题拆分后重试。"],
      ["AGENT_RUN_FAILED", "本次分析未完成，请稍后重试。"],
    ] as const;

    for (const [error_code, expected] of cases) {
      const next = reduceAssistantEvent(
        assistant({ content: "部分回答" }),
        { type: "error", error_code },
      );
      expect(next.status).toBe("error");
      expect(next.statusText).toBe(expected);
      expect(next.content).toBe("部分回答");
    }
  });

  it("falls back to the backend status label for generic status events", () => {
    const next = reduceAssistantEvent(assistant(), {
      type: "status",
      label: "正在拆分分析步骤。",
    });

    expect(next.statusText).toBe("正在拆分分析步骤。");
  });

  it("falls back to a readable status when the label is blank", () => {
    const next = reduceAssistantEvent(assistant(), { type: "status", label: "   " });

    expect(next.statusText).toBe("正在分析…");
  });

  it("never mutates the message it receives", () => {
    const original = assistant({ content: "原文" });
    reduceAssistantEvent(original, { type: "report_delta", content: "追加" });

    expect(original.content).toBe("原文");
    expect(original.status).toBe("streaming");
  });
});
