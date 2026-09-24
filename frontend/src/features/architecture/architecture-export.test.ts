import { describe, expect, it } from "vitest";

import { ARCHITECTURE_MODEL } from "./architecture-data";
import {
  ARCHITECTURE_PNG_FILENAME,
  ARCHITECTURE_SVG_FILENAME,
  buildArchitectureSvg,
} from "./architecture-export";

describe("architecture interview export", () => {
  it("creates a 1920 by 1080 standalone SVG", () => {
    const svg = buildArchitectureSvg(ARCHITECTURE_MODEL);

    expect(svg).toContain('<svg xmlns="http://www.w3.org/2000/svg"');
    expect(svg).toContain('width="1920" height="1080" viewBox="0 0 1920 1080"');
    expect(svg).toContain("AI 数据智能平台技术与业务全景");
    expect(svg).toContain("</svg>");
  });

  it("includes every layer, workflow and project boundary", () => {
    const svg = buildArchitectureSvg(ARCHITECTURE_MODEL);

    for (const layer of ARCHITECTURE_MODEL.layers) expect(svg).toContain(layer.title);
    for (const workflow of ARCHITECTURE_MODEL.workflows) expect(svg).toContain(workflow.title);
    for (const boundary of ARCHITECTURE_MODEL.boundaries) expect(svg).toContain(boundary);
  });

  it("uses the fixed interview attachment filenames", () => {
    expect(ARCHITECTURE_SVG_FILENAME).toBe("ai-data-platform-architecture-current.svg");
    expect(ARCHITECTURE_PNG_FILENAME).toBe("ai-data-platform-architecture-current.png");
  });
});

