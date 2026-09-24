"use client";

import Link from "next/link";
import {
  useCallback,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
} from "react";

import {
  ARCHITECTURE_MODEL,
  type ArchitectureEdge,
  type WorkflowId,
} from "./architecture-data";
import {
  buildArchitectureView,
  getNodeDetail,
  getWorkflowHighlight,
} from "./architecture-view-model";

import styles from "./ArchitectureExplorer.module.css";

type EdgeGeometry = ArchitectureEdge & {
  path: string;
  labelX: number;
  labelY: number;
};

function makePath(
  source: DOMRect,
  target: DOMRect,
  container: DOMRect,
): Pick<EdgeGeometry, "path" | "labelX" | "labelY"> {
  const horizontal = target.left - source.right > 24;
  if (horizontal) {
    const x1 = source.right - container.left;
    const y1 = source.top + source.height / 2 - container.top;
    const x2 = target.left - container.left;
    const y2 = target.top + target.height / 2 - container.top;
    const bend = Math.max(28, (x2 - x1) * 0.48);
    return {
      path: `M ${x1} ${y1} C ${x1 + bend} ${y1}, ${x2 - bend} ${y2}, ${x2} ${y2}`,
      labelX: (x1 + x2) / 2,
      labelY: (y1 + y2) / 2 - 5,
    };
  }

  const x1 = source.left + source.width / 2 - container.left;
  const y1 = source.bottom - container.top;
  const x2 = target.left + target.width / 2 - container.left;
  const y2 = target.top - container.top;
  const bend = Math.max(24, Math.abs(y2 - y1) * 0.45);
  return {
    path: `M ${x1} ${y1} C ${x1} ${y1 + bend}, ${x2} ${y2 - bend}, ${x2} ${y2}`,
    labelX: (x1 + x2) / 2 + 7,
    labelY: (y1 + y2) / 2,
  };
}

export function ArchitectureExplorer() {
  const model = ARCHITECTURE_MODEL;
  const columns = useMemo(() => buildArchitectureView(model), [model]);
  const [selectedNodeId, setSelectedNodeId] = useState("deep-agents");
  const [workflowId, setWorkflowId] = useState<WorkflowId>("business-analysis");
  const [edgeGeometry, setEdgeGeometry] = useState<EdgeGeometry[]>([]);
  const canvasRef = useRef<HTMLDivElement | null>(null);
  const nodeRefs = useRef(new Map<string, HTMLButtonElement>());
  const selectedNode = getNodeDetail(model, selectedNodeId);
  const highlight = getWorkflowHighlight(model, workflowId);

  const registerNode = useCallback(
    (nodeId: string) => (element: HTMLButtonElement | null) => {
      if (element) nodeRefs.current.set(nodeId, element);
      else nodeRefs.current.delete(nodeId);
    },
    [],
  );

  useLayoutEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;

    const calculate = () => {
      const containerRect = canvas.getBoundingClientRect();
      const next = model.edges.flatMap((edge) => {
        const source = nodeRefs.current.get(edge.source);
        const target = nodeRefs.current.get(edge.target);
        if (!source || !target) return [];
        return [
          {
            ...edge,
            ...makePath(
              source.getBoundingClientRect(),
              target.getBoundingClientRect(),
              containerRect,
            ),
          },
        ];
      });
      setEdgeGeometry(next);
    };

    calculate();
    const observer = new ResizeObserver(calculate);
    observer.observe(canvas);
    for (const node of nodeRefs.current.values()) observer.observe(node);
    window.addEventListener("resize", calculate);

    return () => {
      observer.disconnect();
      window.removeEventListener("resize", calculate);
    };
  }, [model.edges]);

  const nodeTitle = useMemo(
    () => new Map(model.nodes.map((node) => [node.id, node.title])),
    [model.nodes],
  );

  return (
    <>
      <section className={styles.graphSection} aria-labelledby="architecture-map-title">
        <div className={styles.sectionHeading}>
          <div>
            <p className={styles.kicker}>TECH → BUSINESS</p>
            <h2 id="architecture-map-title">技术—业务全景主图</h2>
            <p>
              从左到右阅读技术如何逐层变成业务能力。点击节点查看职责；切换链路会同时高亮节点和依赖边。
            </p>
          </div>
          <div className={styles.legend} aria-label="图例">
            <span><i className={styles.legendCurrent} />当前能力</span>
            <span><i className={styles.legendActive} />所选链路</span>
            <span><i className={styles.legendSelected} />当前节点</span>
          </div>
        </div>

        <div className={styles.workflowTabs} role="group" aria-label="选择要高亮的业务链路">
          {model.workflows.map((workflow) => (
            <button
              key={workflow.id}
              type="button"
              className={workflow.id === workflowId ? styles.workflowTabActive : styles.workflowTab}
              style={{ "--workflow-color": workflow.color } as React.CSSProperties}
              aria-pressed={workflow.id === workflowId}
              onClick={() => setWorkflowId(workflow.id)}
            >
              <span>{workflow.shortTitle}</span>
              {workflow.title}
            </button>
          ))}
        </div>

        <div className={styles.canvasViewport}>
          <div ref={canvasRef} className={styles.canvas}>
            <svg className={styles.edges} aria-hidden="true">
              <defs>
                <marker id="architecture-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="5" markerHeight="5" orient="auto-start-reverse">
                  <path d="M 0 0 L 10 5 L 0 10 z" />
                </marker>
                <marker id="architecture-arrow-active" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
                  <path d="M 0 0 L 10 5 L 0 10 z" />
                </marker>
              </defs>
              {edgeGeometry.map((edge) => {
                const active = highlight.edgeIds.has(edge.id);
                return (
                  <g key={edge.id} className={active ? styles.edgeActive : styles.edgeMuted}>
                    <path
                      d={edge.path}
                      markerEnd={active ? "url(#architecture-arrow-active)" : "url(#architecture-arrow)"}
                      markerStart={edge.direction === "bidirectional" ? (active ? "url(#architecture-arrow-active)" : "url(#architecture-arrow)") : undefined}
                    />
                    {active ? <text x={edge.labelX} y={edge.labelY}>{edge.label}</text> : null}
                  </g>
                );
              })}
            </svg>

            <div className={styles.columns}>
              {columns.map(({ layer, nodes }) => (
                <section key={layer.id} className={styles.layer} aria-labelledby={`layer-${layer.id}`}>
                  <header className={styles.layerHeader}>
                    <span>{String(layer.order).padStart(2, "0")} · {layer.eyebrow}</span>
                    <h3 id={`layer-${layer.id}`}>{layer.title}</h3>
                    <p>{layer.description}</p>
                  </header>
                  <div className={styles.nodeList}>
                    {nodes.map((node) => {
                      const active = highlight.nodeIds.has(node.id);
                      const selected = selectedNode.id === node.id;
                      return (
                        <button
                          ref={registerNode(node.id)}
                          key={node.id}
                          type="button"
                          className={`${styles.node} ${active ? styles.nodeActive : styles.nodeDimmed} ${selected ? styles.nodeSelected : ""}`}
                          aria-pressed={selected}
                          onClick={() => setSelectedNodeId(node.id)}
                        >
                          <span className={styles.nodeKind}>{node.kind === "application" ? "业务入口" : "当前能力"}</span>
                          <strong>{node.title}</strong>
                          <small>{node.subtitle}</small>
                        </button>
                      );
                    })}
                  </div>
                </section>
              ))}
            </div>
          </div>
        </div>

        <details className={styles.textAlternative}>
          <summary>查看架构图的完整文字说明</summary>
          <ol>
            {columns.map(({ layer, nodes }) => (
              <li key={layer.id}>
                <strong>{layer.title}：</strong>{nodes.map((node) => node.title).join("、")}
              </li>
            ))}
          </ol>
          <p>当前高亮链路：{highlight.workflow.title}（{highlight.workflow.lineLabel}）。</p>
          <ul>
            {model.edges.map((edge) => (
              <li key={edge.id}>{nodeTitle.get(edge.source)} → {nodeTitle.get(edge.target)}：{edge.label}</li>
            ))}
          </ul>
        </details>
      </section>

      <section className={styles.detailSection} aria-labelledby="node-detail-title">
        <div className={styles.detailLead}>
          <p className={styles.kicker}>SELECTED NODE</p>
          <h2 id="node-detail-title">{selectedNode.title}</h2>
          <p>{selectedNode.detail.role}</p>
          {selectedNode.href ? (
            <Link className={styles.openLink} href={selectedNode.href}>打开功能 <span aria-hidden="true">↗</span></Link>
          ) : null}
        </div>
        <dl className={styles.detailGrid}>
          <div><dt>技术组成</dt><dd>{selectedNode.detail.technologies.join(" · ")}</dd></div>
          <div><dt>输入</dt><dd>{selectedNode.detail.inputs.join("；")}</dd></div>
          <div><dt>输出</dt><dd>{selectedNode.detail.outputs.join("；")}</dd></div>
          <div><dt>接口 / 调用面</dt><dd>{selectedNode.detail.interfaces.join("；")}</dd></div>
          <div><dt>支撑业务</dt><dd>{selectedNode.detail.supports.join("；")}</dd></div>
          <div><dt>代码事实</dt><dd>{selectedNode.detail.evidence}</dd></div>
        </dl>
      </section>

      <section className={styles.workflowSection} aria-labelledby="workflow-detail-title">
        <div className={styles.workflowIntro}>
          <p className={styles.kicker}>END-TO-END FLOW</p>
          <h2 id="workflow-detail-title">{highlight.workflow.title}</h2>
          <p>{highlight.workflow.summary}</p>
          <span className={styles.lineCode} style={{ "--workflow-color": highlight.workflow.color } as React.CSSProperties}>
            {highlight.workflow.lineLabel}
          </span>
        </div>
        <ol className={styles.stepList}>
          {highlight.workflow.steps.map((step, index) => (
            <li key={step.id}>
              <span>{String(index + 1).padStart(2, "0")}</span>
              <div><h3>{step.title}</h3><p>{step.description}</p></div>
            </li>
          ))}
        </ol>
        <p className={styles.outcome}><strong>最终产出</strong>{highlight.workflow.outcome}</p>
      </section>
    </>
  );
}

