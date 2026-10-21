# Pixel Production Studio — implementation design

Primary surface: **Monitor**. Secondary surface: **Inspect**.
Approved contract: `docs/superpowers/specs/2026-10-20-pixel-production-studio-design.md`.

## Composition
- Compact masthead with database, Hermes feed, source mode and connection truth.
- Dominant illustrated production office (six workstations), paired with a fixed-width inspector.
- A continuous evidence workbench below: production queue, full pipeline, quality and validated video.
- Narrow displays retain a horizontally scroll-contained office and stack inspector/evidence. The document itself must not overflow.

## Tokens
| Token | Value | Role |
|---|---|---|
| canvas | #10171e | navy outer shell |
| surface | #18222b | panels |
| raised | #202e37 | controls and rows |
| border | #34434c | structural edges |
| text | #edf0e9 | primary information |
| muted | #a6b5b9 | supporting information |
| teal | #83c4b4 | selection and genuine working status |
| amber | #e8bf7b | waiting / blocked / fixture indication |
| red | #ef9d99 | failed / disconnected |
| wood | #9c7054 / #ac8060 | original office floor |

Typography is intentionally Segoe UI/system sans: this is an operator console, not pixel text. Mono accents are limited to canonical IDs, timestamps and counters. Native controls, visible keyboard focus, 44px touch targets at narrow widths. No remote fonts, analytics, image packs, or providers.

## Illustration
Original orthographic cutaway office in a 960×540 viewbox: warm parquet floor, deep teal walls, broad evening windows, a center aisle, six furnished work areas, plants, records, render racks and a quiet lounge. Each character has a different silhouette and limited palette. SVG geometry is integer-aligned and crisp; original CSS/SVG assets are CC0-1.0 (see asset ledger).

## Motion and truth
Only transform/opacity transitions or keyframes. Character placement changes only with persisted task status. Working animation requires connected SSE + non-stale working event. No idle loops, random motion, invented metrics or simulated progress. Reduced-motion, animation toggle, hidden tab, narrow viewport, save-data or low reported hardware concurrency enable render economy.

## Data discipline
A snapshot is authoritative and history bounded. Reject regressing cursors and same-cursor older timestamps; accept same-cursor newer snapshots for lease freshness. Preserve snapshot across disconnect; reconnect from accepted cursor with bounded exponential retry. Mode changes clear state and close prior connections. Production never imports fixtures or falls back to them. Video URLs are constructed from selected job identity and confined to the same-origin video endpoint; response-provided foreign URLs are never used.

## Read-only boundaries
No job creation, approval, upload or publishing controls. Unavailable media, unknown quality, stale feed and unsupported publishing remain explicit. Model labels come from real events or read “Not reported”; the UI does not infer provider health from database health.
