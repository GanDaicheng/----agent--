import type {
  ArchitectureModel,
  ArchitectureNode,
  WorkflowId,
} from "./architecture-data";

export function buildArchitectureView(model: ArchitectureModel) {
  return [...model.layers]
    .sort((left, right) => left.order - right.order)
    .map((layer) => ({
      layer,
      nodes: model.nodes.filter((node) => node.layerId === layer.id),
    }));
}

export function getNodeDetail(
  model: ArchitectureModel,
  selectedNodeId: string,
): ArchitectureNode {
  return (
    model.nodes.find((node) => node.id === selectedNodeId) ??
    model.nodes.find((node) => node.id === "deep-agents") ??
    model.nodes[0]
  );
}

export function getWorkflowHighlight(
  model: ArchitectureModel,
  workflowId: WorkflowId,
) {
  const workflow =
    model.workflows.find((candidate) => candidate.id === workflowId) ??
    model.workflows[0];

  return {
    workflow,
    nodeIds: new Set(workflow.nodeIds),
    edgeIds: new Set(workflow.edgeIds),
  };
}

