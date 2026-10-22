import type { CSSProperties, ReactNode } from "react";
import type { ActivityKind, Member } from "@/lib/team";
const TOOLS: Record<string, ReactNode> = {
  headset: <path d="M6 10h2v8H6z M24 10h2v8h-2z M21 18h5v2h-5z" />,
  goggles: <><path d="M8 10h6v5H8z M18 10h6v5h-6z M14 11h4v2h-4z" /><path fill="var(--px-paper)" d="M10 11h2v2h-2z M20 11h2v2h-2z" /></>,
  beret: <path d="M8 4h14v4H6V6h2z M18 2h2v2h-2z" />,
  pencil: <path d="M25 18h2v12h-2z M25 30h2v2h-2z" />,
  cap: <path d="M10 3h12v5H8V5h2z M20 7h8v2h-8z" />,
  visor: <path d="M7 8h19v3H7z M23 11h5v2h-5z" />,
  scarf: <path d="M9 19h14v3H9z M19 22h4v9h-4z" />,
  headphones: <path d="M8 6h16v3H8z M5 9h4v10H5z M23 9h4v10h-4z" />,
  wrench: <path d="M24 20h2v9h-2z M22 17h2v4h-2z M26 17h2v4h-2z M22 21h6v2h-6z" />,
  glasses: <><path d="M8 11h7v5H8z M17 11h7v5h-7z M15 12h2v2h-2z" /><path fill="var(--px-paper)" d="M10 12h3v2h-3z M19 12h3v2h-3z" /></>,
  pin: <path d="M20 23h4v4h-4z M21 27h2v2h-2z" />,
  badge: <><path d="M11 20h2v7h-2z M19 20h2v7h-2z M13 27h6v5h-6z" /><path fill="var(--px-paper)" d="M14 28h4v2h-4z" /></>,
};
const HAIR: Record<string, string> = {
  short: "M9 4h14v5H9z M7 7h3v6H7z M22 7h3v4h-3z",
  bob: "M9 4h14v5H9z M7 7h4v13H7z M21 7h4v13h-4z",
  ponytail: "M9 4h14v5H9z M7 7h3v7H7z M22 7h5v4h-5z M25 11h3v12h-3z",
  curls: "M9 3h5v3H9z M16 3h5v3h-5z M7 6h18v4H7z M6 9h4v7H6z M22 9h4v7h-4z",
};
export function PixelAvatar({ member, kind, size = 48 }: { member: Member; kind: ActivityKind; size?: number }) {
  const skin = ["warm", "deep", "light"].includes(member.skin ?? "") ? member.skin : "warm";
  const accessory = TOOLS[member.accessory ?? ""] ? member.accessory! : "badge";
  return <svg className="px-avatar" data-kind={kind} aria-hidden="true" focusable="false"
    viewBox="0 0 32 40" width={size} height={size * 1.25} shapeRendering="crispEdges"
    style={{ "--agent-accent": member.accent } as CSSProperties}>
    <path d="M6 37h21v2H6z" fill="var(--px-shadow)" />
    <g className="px-avatar-body">
      <path d="M10 30h5v7h-5z M18 30h5v7h-5z" fill="var(--px-edge)" />
      <path d="M8 36h7v2H8z M18 36h7v2h-7z" fill="var(--px-shadow)" />
      <rect x="8" y="20" width="17" height="13" fill="var(--agent-accent)" />
      <path d="M8 22h3v10H8z M22 22h3v10h-3z" fill="var(--px-edge)" />
      <rect x="12" y="18" width="8" height="4" fill={`var(--px-skin-${skin})`} />
      <rect x="9" y="7" width="15" height="12" fill={`var(--px-skin-${skin})`} />
      <path d={HAIR[member.hair ?? "short"] ?? HAIR.short} fill="var(--px-hair)" />
      <g className="px-avatar-eyes" fill="var(--px-eye)"><rect x="12" y="12" width="2" height="2" /><rect x="19" y="12" width="2" height="2" /></g>
      <path d={kind === "failed" || kind === "blocked" ? "M14 17h5v1h-5z" : "M14 16h2v1h3v-1h1v2h-6z"} fill="var(--px-eye)" />
      <path d="M5 25h4v6H5z M24 25h4v6h-4z" fill={`var(--px-skin-${skin})`} />
      <g className="px-avatar-tool" data-accessory={accessory} fill="var(--px-paper)">{TOOLS[accessory]}</g>
    </g>
  </svg>;
}
