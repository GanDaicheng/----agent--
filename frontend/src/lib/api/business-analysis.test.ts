import { describe, expect, it } from "vitest";

import { parseSseChunk } from "./business-analysis";

describe("parseSseChunk", () => {
  it("parses multiple SSE events and preserves report deltas", () => {
    const events = parseSseChunk(
      'event: status\ndata: {"label":"正在查询"}\n\n' +
        'event: report_delta\ndata: {"content":"## 结论"}\n\n',
    );

    expect(events).toEqual([
      { type: "status", label: "正在查询" },
      { type: "report_delta", content: "## 结论" },
    ]);
  });

  it("ignores malformed frames instead of throwing", () => {
    expect(parseSseChunk("event: status\ndata: not-json\n\n")).toEqual([]);
  });
});
