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
    const routeByNode = Object.fromEntries(
      ARCHITECTURE_MODEL.nodes
        .filter((node) => node.kind === "application")
        .map((node) => [node.id, node.href]),
    );

    expect(routeByNode).toEqual({
      "app-data-sources": PAGE_HREFS.dataSources,
      "app-warehouse": PAGE_HREFS.dataWarehouse,
      "app-knowledge-qa": PAGE_HREFS.knowledgeQa,
      "app-data-query": PAGE_HREFS.dataQuery,
      "app-business-analysis": PAGE_HREFS.businessAnalysis,
    });
    expect(new Set(Object.values(routeByNode)).size).toBe(5);
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

  it("keeps every highlighted workflow node connected to its highlighted subgraph", () => {
    const businessWorkflow = ARCHITECTURE_MODEL.workflows.find(
      (workflow) => workflow.id === "business-analysis",
    );

    expect(businessWorkflow?.edgeIds).toEqual(
      expect.arrayContaining(["safe-query-graph", "postgres-sql"]),
    );
    expect(validateArchitecture(ARCHITECTURE_MODEL)).toEqual([]);
  });

  it("reports duplicate IDs and incoherent workflow memberships", () => {
    const invalid = structuredClone(ARCHITECTURE_MODEL);
    invalid.layers[1].order = invalid.layers[0].order;
    invalid.workflows[1].id = invalid.workflows[0].id;
    invalid.workflows[1].steps[1].id = invalid.workflows[1].steps[0].id;
    invalid.workflows[1].steps[0].nodeIds = ["deep-agents"];
    invalid.workflows[1].edgeIds = invalid.workflows[1].edgeIds.filter(
      (edgeId) => edgeId !== "safe-query-graph" && edgeId !== "postgres-sql",
    );

    expect(validateArchitecture(invalid)).toEqual(
      expect.arrayContaining([
        "Duplicate layer order: 1",
        "Duplicate workflow id: document-rag",
        "Duplicate step id query-understand in workflow document-rag",
        "Node deep-agents in step query-understand is not part of workflow document-rag",
        "Node safe-sql is disconnected in workflow document-rag",
      ]),
    );
  });
});
