import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "金融分析智能体",
  description: "A股多 Agent 金融分析 Web UI",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="zh-CN">
      <body>{children}</body>
    </html>
  );
}
