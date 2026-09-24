import { describe, expect, it } from "vitest";

import { ARCHITECTURE_MODEL } from "./architecture-data";
import {
  buildArchitectureView,
  getNodeDetail,
  getWorkflowHighlight,
} from "./architecture-view-model";

describe("architecture view model", () => {
  it("groups every node into ordered layers", () => {
    const view = buildArchitectureView(ARCHITECTURE_MODEL);

    expect(view.map((column) => column.layer.id)).toEqual([
      "engineering",
      "resources",
      "capabilities",
      "orchestration",
      "delivery",
      "applications",
    ]);
    expect(view.flatMap((column) => column.nodes)).toHaveLength(
      ARCHITECTURE_MODEL.nodes.length,
    );
  });

  it("returns the selected node and falls back to the supervisor Agent", () => {
    expect(getNodeDetail(ARCHITECTURE_MODEL, "app-data-query").title).toBe("智能问数");
    expect(getNodeDetail(ARCHITECTURE_MODEL, "missing").id).toBe("deep-agents");
  });

  it("derives node and edge highlights for the selected workflow", () => {
    const highlight = getWorkflowHighlight(ARCHITECTURE_MODEL, "business-analysis");

    expect(highlight.nodeIds.has("deep-agents")).toBe(true);
    expect(highlight.nodeIds.has("app-business-analysis")).toBe(true);
    expect(highlight.edgeIds.has("deep-agents-sse")).toBe(true);
    expect(highlight.nodeIds.has("app-data-sources")).toBe(false);
  });
});
