import type { ArchitectureModel } from "./architecture-data";

export const ARCHITECTURE_SVG_FILENAME = "ai-data-platform-architecture-current.svg";
export const ARCHITECTURE_PNG_FILENAME = "ai-data-platform-architecture-current.png";

function escapeXml(value: string) {
  return value
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&apos;");
}

function text(value: string) {
  return escapeXml(value);
}

export function buildArchitectureSvg(model: ArchitectureModel): string {
  const orderedLayers = [...model.layers].sort((left, right) => left.order - right.order);
  const layerWidth = 278;
  const layerGap = 32;
  const layerStartX = 48;
  const nodeHeight = 69;
  const nodeGap = 10;

  const layerMarkup = orderedLayers
    .map((layer, index) => {
      const x = layerStartX + index * (layerWidth + layerGap);
      const layerNodes = model.nodes.filter((node) => node.layerId === layer.id);
      const nodesMarkup = layerNodes
        .map((node, nodeIndex) => {
          const y = 274 + nodeIndex * (nodeHeight + nodeGap);
          const application = node.kind === "application";
          return `
            <g>
              <rect x="${x + 14}" y="${y}" width="250" height="${nodeHeight}" rx="12" fill="${application ? "#152f52" : "#1c2940"}" stroke="${application ? "#60a5fa" : "#43516a"}"/>
              <text x="${x + 30}" y="${y + 27}" class="node-title">${text(node.title)}</text>
              <text x="${x + 30}" y="${y + 49}" class="node-subtitle">${text(node.subtitle)}</text>
            </g>`;
        })
        .join("");

      return `
        <g>
          <rect x="${x}" y="172" width="${layerWidth}" height="500" rx="16" fill="#121c2e" stroke="#2e3d57"/>
          <text x="${x + 18}" y="205" class="eyebrow">${String(layer.order).padStart(2, "0")} · ${text(layer.eyebrow)}</text>
          <text x="${x + 18}" y="235" class="layer-title">${text(layer.title)}</text>
          <line x1="${x + 18}" y1="253" x2="${x + layerWidth - 18}" y2="253" stroke="#34445e"/>
          ${nodesMarkup}
        </g>`;
    })
    .join("");

  const connectorMarkup = orderedLayers
    .slice(0, -1)
    .map((_, index) => {
      const x1 = layerStartX + index * (layerWidth + layerGap) + layerWidth;
      const x2 = x1 + layerGap;
      return `<path d="M ${x1 + 4} 420 L ${x2 - 4} 420" stroke="#5a759d" stroke-width="2" marker-end="url(#arrow)"/>`;
    })
    .join("");

  const workflowMarkup = model.workflows
    .map((workflow, index) => {
      const y = 744 + index * 68;
      const lineMarkup = workflow.lineStyle === "double"
        ? `<line data-line-style="double" x1="54" y1="${y + 22}" x2="174" y2="${y + 22}" stroke="${workflow.color}" stroke-width="2"/>
          <line data-line-style="double" x1="54" y1="${y + 30}" x2="174" y2="${y + 30}" stroke="${workflow.color}" stroke-width="2"/>`
        : `<line data-line-style="${workflow.lineStyle}" x1="54" y1="${y + 26}" x2="174" y2="${y + 26}" stroke="${workflow.color}" stroke-width="3"${workflow.lineStyle === "dashed" ? ' stroke-dasharray="10 8"' : ""}/>`;
      const stepLabels = workflow.steps.map((step) => step.title).join(" → ");
      return `
        <g>
          ${lineMarkup}
          <circle cx="54" cy="${y + 26}" r="6" fill="${workflow.color}"/>
          <text x="196" y="${y + 18}" class="workflow-title">${text(workflow.title)}</text>
          <text x="196" y="${y + 41}" class="workflow-steps">${text(stepLabels)}</text>
        </g>`;
    })
    .join("");

  const boundaryMarkup = model.boundaries
    .map((boundary, index) => {
      const x = 54 + index * 610;
      return `<text x="${x}" y="1028" class="boundary">• ${text(boundary)}</text>`;
    })
    .join("");

  return `<svg xmlns="http://www.w3.org/2000/svg" width="1920" height="1080" viewBox="0 0 1920 1080" role="img" aria-labelledby="title description">
  <title id="title">${text(model.title)}</title>
  <desc id="description">${text(model.subtitle)}。包含六层当前架构、三条业务链路和项目安全边界。</desc>
  <defs>
    <linearGradient id="background" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0" stop-color="#0b1220"/><stop offset="0.62" stop-color="#111c31"/><stop offset="1" stop-color="#0c1526"/>
    </linearGradient>
    <radialGradient id="glow" cx="82%" cy="8%" r="60%"><stop offset="0" stop-color="#1d4ed8" stop-opacity=".28"/><stop offset="1" stop-color="#1d4ed8" stop-opacity="0"/></radialGradient>
    <marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto"><path d="M 0 0 L 10 5 L 0 10 z" fill="#5a759d"/></marker>
    <style>
      text { font-family: Inter, "Microsoft YaHei", "Noto Sans SC", sans-serif; }
      .brand { fill:#60a5fa; font-size:16px; font-weight:700; letter-spacing:3px; }
      .title { fill:#f8fafc; font-size:46px; font-weight:750; letter-spacing:-1px; }
      .subtitle { fill:#9fb0c8; font-size:20px; }
      .eyebrow { fill:#60a5fa; font-family:ui-monospace,monospace; font-size:12px; font-weight:700; letter-spacing:1.6px; }
      .layer-title { fill:#f1f5f9; font-size:21px; font-weight:700; }
      .node-title { fill:#eff6ff; font-size:15px; font-weight:700; }
      .node-subtitle { fill:#9fb0c8; font-size:11px; }
      .workflow-title { fill:#f8fafc; font-size:17px; font-weight:700; }
      .workflow-steps { fill:#aebbd0; font-size:13px; }
      .boundary { fill:#94a3b8; font-size:11px; }
    </style>
  </defs>
  <rect width="1920" height="1080" fill="url(#background)"/>
  <rect width="1920" height="1080" fill="url(#glow)"/>
  <text x="50" y="58" class="brand">CURRENT IMPLEMENTATION · 2026</text>
  <text x="50" y="113" class="title">${text(model.title)}</text>
  <text x="50" y="147" class="subtitle">${text(model.subtitle)}｜页面与导出图共用同一架构数据源</text>
  ${connectorMarkup}
  ${layerMarkup}
  <text x="50" y="712" class="brand">THREE END-TO-END WORKFLOWS</text>
  ${workflowMarkup}
  <line x1="50" y1="986" x2="1870" y2="986" stroke="#2f405c"/>
  <text x="50" y="1009" class="eyebrow">PROJECT BOUNDARIES / SECURITY CONTEXT</text>
  ${boundaryMarkup}
</svg>`;
}
