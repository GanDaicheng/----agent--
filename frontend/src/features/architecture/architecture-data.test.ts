import { describe, expect, it } from "vitest";

import { PAGE_HREFS } from "../platform/platform-config";

import {
  ARCHITECTURE_MODEL,
  FORBIDDEN_CURRENT_CAPABILITIES,
  validateArchitecture,
} from "./architecture-data";

describe("ARCHITECTURE_MODEL", () => {
  it("has unique layer and node identifiers", () => {
    const layerIds = ARCHITECTURE_MODEL.layers.map((layer) => layer.id);
    const nodeIds = ARCHITECTURE_MODEL.nodes.map((node) => node.id);

    expect(new Set(layerIds).size).toBe(layerIds.length);
    expect(new Set(nodeIds).size).toBe(nodeIds.length);
  });

  it("only references existing nodes from edges and workflows", () => {
    expect(validateArchitecture(ARCHITECTURE_MODEL)).toEqual([]);
  });

  it("maps every current application to the canonical platform route", () => {
    const routes = Object.values(PAGE_HREFS);
    const applicationNodes = ARCHITECTURE_MODEL.nodes.filter(
      (node) => node.kind === "application",
    );

    expect(applicationNodes).toHaveLength(5);
    expect(applicationNodes.every((node) => node.href && routes.includes(node.href))).toBe(
      true,
    );
  });

  it("defines exactly the three implemented end-to-end workflows", () => {
    expect(ARCHITECTURE_MODEL.workflows.map((workflow) => workflow.id)).toEqual([
      "document-rag",
      "data-query",
      "business-analysis",
    ]);
  });

  it("does not advertise planned personal-office Agent capabilities", () => {
    const searchableText = JSON.stringify(ARCHITECTURE_MODEL);

    for (const capability of FORBIDDEN_CURRENT_CAPABILITIES) {
      expect(searchableText).not.toContain(capability);
    }
  });
});
