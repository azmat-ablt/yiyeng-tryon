import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "ATELIER · 虚拟试衣间",
  description: "上传一张正面照片，选择一件单品，几秒内生成试穿效果",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="zh-CN">
      <body>{children}</body>
    </html>
  );
}
