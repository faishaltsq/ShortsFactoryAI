"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const NAV = [
  { href: "/", label: "Overview", hint: "Ringkasan hari ini" },
  { href: "/studio", label: "Studio", hint: "Model, prompt, budget" },
  { href: "/jobs", label: "Jobs", hint: "Antrean produksi" },
  { href: "/providers", label: "Providers", hint: "Kesehatan model" },
  { href: "/usage", label: "Usage", hint: "Token & biaya" },
];

export function Sidebar() {
  const path = usePathname();
  return (
    <aside className="sticky top-0 h-screen w-56 shrink-0 border-r border-zinc-800 px-4 py-8">
      <div className="mb-8 px-2">
        <p className="text-lg font-semibold tracking-tight">Pixel Studio</p>
        <p className="text-xs text-zinc-500">ShortsFactoryAI console</p>
      </div>
      <nav className="flex flex-col gap-1">
        {NAV.map((item) => {
          const active = item.href === "/" ? path === "/" : path.startsWith(item.href);
          return (
            <Link
              key={item.href}
              href={item.href}
              className={`rounded-md px-2 py-2 text-sm outline-none transition focus-visible:ring-2 focus-visible:ring-sky-500 ${
                active
                  ? "bg-zinc-800 font-medium text-white"
                  : "text-zinc-400 hover:bg-zinc-900 hover:text-zinc-100"
              }`}
              aria-current={active ? "page" : undefined}
            >
              {item.label}
              <span className="block text-[11px] text-zinc-500">{item.hint}</span>
            </Link>
          );
        })}
      </nav>
    </aside>
  );
}
