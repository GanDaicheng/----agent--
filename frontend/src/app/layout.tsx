import type { Metadata } from "next";

import "./globals.css";

export const metadata: Metadata = {
  title: "数据中台 Agent",
  description: "面向业务人员的智能问数与数据分析工作台",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="zh-CN">
      <body>{children}</body>
    </html>
  );
}
