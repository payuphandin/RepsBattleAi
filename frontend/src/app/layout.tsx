import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import "./globals.css";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "RepBattle AI | แข่งวิดพื้น",
  description:
    "แพลตฟอร์มแข่งขันวิดพื้นแบบเรียลไทม์ 1 ต่อ 1 พร้อม AI ตรวจจับท่าทางและนับจำนวนครั้ง",

  openGraph: {
    title: "RepBattle AI | แข่งวิดพื้น",
    description:
      "ท้าประลองวิดพื้นกับเพื่อน แข่งขันแบบ 1 ต่อ 1 พร้อม AI ช่วยตรวจจับและนับจำนวนครั้ง",
    type: "website",
    locale: "th_TH",
    siteName: "RepBattle AI",
  },
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html
      lang="th"
      className={`${geistSans.variable} ${geistMono.variable} h-full antialiased`}
    >
      <body className="min-h-full flex flex-col">{children}</body>
    </html>
  );
}
