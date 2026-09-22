import type { Metadata } from "next";

import { PlatformShell } from "@/components/platform/PlatformShell";

import "./globals.css";

export const metadata: Metadata = {
  title: {
    default: "零售企业智能化平台",
    template: "%s · 零售企业智能化平台",
  },
  description:
    "从业务能力、数据资产到 AI 智能应用的一体化建设原型，展示业务中台、数据中台、AI 中台与智能应用的分层建设状态。",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="zh-CN">
      <body>
        <PlatformShell>{children}</PlatformShell>
      </body>
    </html>
  );
}
