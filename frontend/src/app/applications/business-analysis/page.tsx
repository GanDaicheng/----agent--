import type { Metadata } from "next";

import { PageHeader } from "@/components/ui/PageHeader";
import { getSection, RETAIL_DATA_NOTE } from "@/features/platform/platform-config";

import { BusinessAnalysisWorkspace } from "./BusinessAnalysisWorkspace";

const SECTION_ID = "applications";

export const metadata: Metadata = {
  title: "AI 经营分析助手",
  description: "由 Deep Agents 主管 Agent 调用问数和知识库工具，完成多步骤经营分析。",
};

export default function Page() {
  const section = getSection(SECTION_ID);

  return (
    <article>
      <PageHeader
        sectionName={section?.name ?? "智能应用"}
        title="AI 经营分析助手"
        subtitle="输入一个复杂经营目标，主管 Agent 会自主拆解任务、调用数据与知识工具，并实时生成带证据的分析报告。"
        boundary={
          <>
            <p>{RETAIL_DATA_NOTE}</p>
            <p>
              本页面演示 Deep Agents 的多轮工具调用能力；数字仍然来自现有安全问数链路，
              规则依据来自现有知识库。
            </p>
            <p>
              当前为作品集原型，使用匿名浏览器会话标识，不包含企业登录、租户隔离或生产数据权限。
            </p>
          </>
        }
      />
      <BusinessAnalysisWorkspace />
    </article>
  );
}
