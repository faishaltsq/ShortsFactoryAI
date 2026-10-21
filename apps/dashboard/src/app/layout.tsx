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
      <body className="min-h-screen bg-zinc-950 text-zinc-100 antialiased">
        <div className="mx-auto flex min-h-screen max-w-[1400px]">
          <Sidebar />
          <main className="flex-1 px-6 py-8 lg:px-10">{children}</main>
        </div>
      </body>
    </html>
  );
}
