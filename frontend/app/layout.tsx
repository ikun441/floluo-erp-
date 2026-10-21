import type { Metadata } from "next";
import "./style.css";
import "./login.css";
export const metadata: Metadata = {
  title: "弗洛洛 ERP",
  description: "企业工作，从这里有序开始",
  icons: {
    icon: { url: "/brand/floluo-logo.png", type: "image/png" },
    apple: "/brand/floluo-logo.png",
  },
};
export default function Layout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="zh-CN">
      <body>{children}</body>
    </html>
  );
}
