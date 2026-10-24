"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
const NAV = [
  { href: "/", label: "Overview", hint: "Lobi studio", glyph: "M2 7h12v7H2z M4 2h8v3H4z" },
  { href: "/studio", label: "Studio", hint: "Tim & pengaturan", glyph: "M3 2h4v4H3z M9 2h4v4H9z M1 8h7v6H1z M9 8h6v6H9z" },
  { href: "/jobs", label: "Jobs", hint: "Antrean produksi", glyph: "M2 2h12v3H2z M2 7h12v3H2z M2 12h12v2H2z" },
  { href: "/schedule", label: "Schedule", hint: "Proyeksi produksi", glyph: "M2 2h12v12H2z M2 6h12 M5 1v3 M11 1v3 M4 9h2 M8 9h4 M4 11h2" },
  { href: "/providers", label: "Providers", hint: "Ruang mesin", glyph: "M3 1h10v14H3z M5 3h6v2H5z M5 7h6v2H5z" },
  { href: "/usage", label: "Usage", hint: "Buku produksi", glyph: "M2 9h3v5H2z M7 5h3v9H7z M12 1h3v13h-3z" },
];
export function Sidebar() {
  const path = usePathname();
  return <aside className="px-sidebar">
    <Link href="/" className="px-brand"><span aria-hidden="true">▦</span><span>Pixel Studio<small>SHORTS FACTORY AI</small></span></Link>
    <nav aria-label="Navigasi utama">
      {NAV.map((item) => {
        const active = item.href === "/" ? path === "/" : path.startsWith(item.href);
        return <Link key={item.href} href={item.href} aria-current={active ? "page" : undefined}>
          <svg viewBox="0 0 16 16" width="20" height="20" aria-hidden="true" shapeRendering="crispEdges"><path d={item.glyph} fill="currentColor" /></svg>
          <span>{item.label}<small>{item.hint}</small></span>
        </Link>;
      })}
    </nav>
    <p className="px-local-label">LOCAL-FIRST · OPERATOR CONSOLE</p>
  </aside>;
}
