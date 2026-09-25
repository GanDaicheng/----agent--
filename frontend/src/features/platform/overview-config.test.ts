import { describe, expect, it } from "vitest";

import {
  ARCHITECTURE_MODEL,
  FORBIDDEN_CURRENT_CAPABILITIES,
} from "../architecture/architecture-data";

import {
  INTERVIEW_HIGHLIGHTS,
  OVERVIEW_APPLICATIONS,
  OVERVIEW_HERO,
  OVERVIEW_PIPELINE,
  OVERVIEW_TECH_LAYERS,
  PROJECT_BOUNDARY_ITEMS,
} from "./overview-config";
import { PAGE_HREFS } from "./platform-config";

const REAL_ROUTES = new Set<string>(Object.values(PAGE_HREFS));

describe("平台总览配置", () => {
  it("四个业务入口都指向真实存在的路由", () => {
    expect(OVERVIEW_APPLICATIONS).toHaveLength(4);

    for (const entry of OVERVIEW_APPLICATIONS) {
      expect(REAL_ROUTES.has(entry.href)).toBe(true);
    }
  });

  it("四个业务入口覆盖数据采集与三个应用页，且不重复", () => {
    const hrefs = OVERVIEW_APPLICATIONS.map((entry) => entry.href);

    expect(new Set(hrefs).size).toBe(hrefs.length);
    expect(hrefs).toEqual([
      PAGE_HREFS.dataSources,
      PAGE_HREFS.knowledgeQa,
      PAGE_HREFS.dataQuery,
      PAGE_HREFS.businessAnalysis,
    ]);
  });

  it("每个业务入口都写明了问题、输入、处理过程与输出", () => {
    for (const entry of OVERVIEW_APPLICATIONS) {
      expect(entry.problem.length).toBeGreaterThan(0);
      expect(entry.input.length).toBeGreaterThan(0);
      expect(entry.output.length).toBeGreaterThan(0);
      expect(entry.process.length).toBeGreaterThan(0);
    }
  });

  it("主链路上带跳转的节点都指向真实路由", () => {
    for (const node of OVERVIEW_PIPELINE) {
      if (!node.href) continue;

      expect(REAL_ROUTES.has(node.href)).toBe(true);
      expect(node.hrefLabel).toBeTruthy();
    }
  });

  it("主链路的首尾是输入与输出，中间环节才有跳转", () => {
    expect(OVERVIEW_PIPELINE[0].href).toBeUndefined();
    expect(OVERVIEW_PIPELINE.at(-1)?.href).toBeUndefined();
    expect(OVERVIEW_PIPELINE.filter((node) => node.href).length).toBeGreaterThan(
      0,
    );
  });

  it("Hero 的三个能力标签与三张业务卡片对应", () => {
    expect(OVERVIEW_HERO.tags).toHaveLength(3);
    expect(new Set(OVERVIEW_HERO.tags).size).toBe(3);
  });

  it("技术栈区域复用了架构模型，且不重复列业务应用层", () => {
    expect(OVERVIEW_TECH_LAYERS.length).toBeGreaterThan(0);
    expect(OVERVIEW_TECH_LAYERS.map((layer) => layer.id)).not.toContain(
      "applications",
    );

    // 顺序按 order 升序，页面上是自上而下读的
    const orders = OVERVIEW_TECH_LAYERS.map((layer) => layer.order);
    expect([...orders].sort((a, b) => a - b)).toEqual(orders);

    // 每一层在架构模型里都得真的有节点，否则会渲染出一个空层级
    for (const layer of OVERVIEW_TECH_LAYERS) {
      const nodes = ARCHITECTURE_MODEL.nodes.filter(
        (node) => node.layerId === layer.id,
      );
      expect(nodes.length).toBeGreaterThan(0);
    }
  });

  it("边界清单包含架构页的既有边界，并补上总览页专属的条目", () => {
    for (const boundary of ARCHITECTURE_MODEL.boundaries) {
      expect(PROJECT_BOUNDARY_ITEMS).toContain(boundary);
    }

    expect(PROJECT_BOUNDARY_ITEMS.length).toBeGreaterThan(
      ARCHITECTURE_MODEL.boundaries.length,
    );
  });

  it("每条业务流程都有可直接展示的细粒度步骤", () => {
    for (const workflow of ARCHITECTURE_MODEL.workflows) {
      expect(workflow.pipeline.length).toBeGreaterThan(0);
      expect(new Set(workflow.pipeline).size).toBe(workflow.pipeline.length);
    }
  });

  it("每条面试亮点都用一句说明解释，而不是只罗列技术名", () => {
    expect(INTERVIEW_HIGHLIGHTS.length).toBeGreaterThan(0);

    for (const highlight of INTERVIEW_HIGHLIGHTS) {
      expect(highlight.title.length).toBeGreaterThan(0);
      // 只有名字没有解释的条目，detail 会短到读不出信息
      expect(highlight.detail.length).toBeGreaterThan(15);
    }
  });

  it("不在总览上宣传尚未实现的个人办公 Agent 能力", () => {
    const searchable = JSON.stringify({
      OVERVIEW_HERO,
      OVERVIEW_PIPELINE,
      OVERVIEW_APPLICATIONS,
      INTERVIEW_HIGHLIGHTS,
      PROJECT_BOUNDARY_ITEMS,
    });

    for (const capability of FORBIDDEN_CURRENT_CAPABILITIES) {
      expect(searchable).not.toContain(capability);
    }
  });
});
