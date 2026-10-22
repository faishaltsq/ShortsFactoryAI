import type { Metadata } from "next";
import "./globals.css";
import { Sidebar } from "@/components/Sidebar";

export const metadata: Metadata = {
  title: "Pixel Studio",
  description: "Orchestrator console untuk ShortsFactoryAI",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="id">
      <body className="px-app">
        <a className="px-skip" href="#main-content">Lewati ke konten</a>
        <div className="px-shell">
          <Sidebar />
          <main id="main-content" tabIndex={-1} className="px-main">{children}</main>
        </div>
      </body>
    </html>
  );
}
