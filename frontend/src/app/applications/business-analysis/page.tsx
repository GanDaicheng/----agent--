import type { Metadata } from "next";

import { BusinessAnalysisWorkspace } from "./BusinessAnalysisWorkspace";

export const metadata: Metadata = {
  title: "AI 经营分析助手",
  description: "由 Deep Agents 主管 Agent 调用问数和知识库工具，完成多步骤经营分析。",
};

export default function Page() {
  return (
    <article aria-label="AI 经营分析助手">
      <BusinessAnalysisWorkspace />
    </article>
  );
}
