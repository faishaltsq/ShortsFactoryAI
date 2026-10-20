'use client';

import type { AgentId, AgentView, Connection } from '../lib/contracts';
import { WORKSTATIONS } from '../lib/selectors';
import { STATUS_LABEL, STATUS_TONE } from '../lib/economy';

type Station = (typeof WORKSTATIONS)[number];

const POS: Record<string, { x: number; y: number }> = {
  control: { x: 130, y: 300 },
  research: { x: 365, y: 300 },
  writing: { x: 600, y: 300 },
  board: { x: 835, y: 300 },
  audio: { x: 250, y: 448 },
  render: { x: 700, y: 448 },
};

const TONE: Record<string, string> = {
  muted: '#a6b5b9', teal: '#83c4b4', amber: '#e8bf7b', ok: '#9fd0a5', red: '#ef9d99',
};

function Figure({ tone, animate }: { tone: string; animate: boolean }) {
  return (
    <g className={animate ? 'figure figure--work' : 'figure'} shapeRendering="crispEdges">
      <rect x={-9} y={0} width={18} height={16} fill="#f3d9c2" />
      <rect x={-9} y={0} width={18} height={5} fill="#2d2320" />
      <rect x={-11} y={16} width={22} height={16} fill={tone} />
      <rect x={-11} y={32} width={8} height={12} fill="#22303a" />
      <rect x={3} y={32} width={8} height={12} fill="#22303a" />
      <rect x={-16} y={18} width={5} height={10} fill="#f3d9c2" />
      <rect x={11} y={18} width={5} height={10} fill="#f3d9c2" />
    </g>
  );
}

function Desk({ tone }: { tone: string }) {
  return (
    <g shapeRendering="crispEdges">
      <rect x={-64} y={0} width={128} height={7} fill="#ac8060" />
      <rect x={-64} y={7} width={128} height={5} fill="#7c5942" />
      <rect x={-58} y={12} width={7} height={26} fill="#7c5942" />
      <rect x={51} y={12} width={7} height={26} fill="#7c5942" />
      <rect x={-46} y={-26} width={52} height={27} fill="#0d141a" />
      <rect x={-42} y={-22} width={44} height={19} fill={tone} opacity={0.35} />
      <rect x={-42} y={-22} width={44} height={4} fill={tone} />
      <rect x={-22} y={1} width={6} height={5} fill="#34434c" />
      <rect x={16} y={-4} width={26} height={4} fill="#dfe6df" />
      <rect x={16} y={-8} width={26} height={4} fill="#b9c4bd" />
    </g>
  );
}

function Bubble({ text, tone }: { text: string; tone: string }) {
  const width = Math.min(Math.max(text.length * 7 + 16, 74), 190);
  return (
    <g className="bubble" transform={`translate(${-width / 2},-46)`}>
      <rect x={0} y={0} width={width} height={24} rx={3} fill="#18222b" stroke={tone} />
      <rect x={width / 2 - 5} y={24} width={10} height={6} fill="#18222b" stroke={tone} />
      <text x={width / 2} y={16} textAnchor="middle" fontSize={11} fill="#edf0e9"
        fontFamily="ui-monospace, monospace">{text}</text>
    </g>
  );
}

function Rack() {
  return (
    <g shapeRendering="crispEdges" transform="translate(0,0)">
      <rect x={-34} y={-96} width={68} height={96} fill="#111a21" />
      {[0, 1, 2, 3, 4].map(row => (
        <g key={row}>
          <rect x={-28} y={-88 + row * 17} width={56} height={12} fill="#202e37" />
          <rect x={-24} y={-84 + row * 17} width={5} height={4} fill="#83c4b4" />
          <rect x={-16} y={-84 + row * 17} width={5} height={4} fill="#e8bf7b" />
        </g>
      ))}
    </g>
  );
}

export type OfficeProps = {
  groups: Array<{ station: Station; view?: AgentView; connection: Connection }>;
  economy: boolean;
  selected: AgentId;
  approval: boolean;
  onSelect(agent: AgentId): void;
};

export function Office({ groups, economy, selected, approval, onSelect }: OfficeProps) {
  return (
    <svg viewBox="0 0 960 540" className="office" role="img"
      aria-label="Pixel Production Studio: enam meja kerja agen produksi">
      <defs>
        <linearGradient id="dusk" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="#3b5f7a" />
          <stop offset="100%" stopColor="#e8bf7b" />
        </linearGradient>
      </defs>

      <rect x={0} y={0} width={960} height={252} fill="#16303a" shapeRendering="crispEdges" />
      {[60, 350, 640].map(x => (
        <g key={x} shapeRendering="crispEdges">
          <rect x={x} y={40} width={220} height={120} fill="url(#dusk)" />
          <rect x={x} y={40} width={220} height={120} fill="none" stroke="#0d141a" strokeWidth={6} />
          <rect x={x + 107} y={40} width={6} height={120} fill="#0d141a" />
          <rect x={x} y={97} width={220} height={6} fill="#0d141a" />
        </g>
      ))}
      <rect x={0} y={244} width={960} height={8} fill="#0d141a" shapeRendering="crispEdges" />

      <rect x={0} y={252} width={960} height={288} fill="#9c7054" shapeRendering="crispEdges" />
      {Array.from({ length: 24 }, (_, i) => (
        <rect key={`v${i}`} x={i * 40} y={252} width={2} height={288} fill="#8a6149" shapeRendering="crispEdges" />
      ))}
      {Array.from({ length: 6 }, (_, i) => (
        <rect key={`h${i}`} x={0} y={252 + i * 48} width={960} height={2} fill="#8a6149" shapeRendering="crispEdges" />
      ))}
      <rect x={0} y={378} width={960} height={54} fill="#ac8060" opacity={0.35} shapeRendering="crispEdges" />

      <g transform="translate(60,330)" shapeRendering="crispEdges">
        <rect x={-40} y={-46} width={80} height={46} fill="#4a5b5f" />
        <rect x={-34} y={-40} width={68} height={16} fill="#34434c" />
        <rect x={-40} y={-8} width={80} height={8} fill="#34434c" />
      </g>
      <g transform="translate(900,300)" shapeRendering="crispEdges">
        <rect x={-22} y={-14} width={44} height={14} fill="#7c5942" />
        <rect x={-16} y={-34} width={32} height={20} fill="#5d7a5a" />
        <rect x={-10} y={-48} width={20} height={16} fill="#6f8f6b" />
      </g>

      {groups.map(({ station, view, connection }) => {
        const pos = POS[station.id];
        const status = view?.status ?? 'idle';
        const tone = TONE[STATUS_TONE[status] ?? 'muted'];
        const label = (view?.description ?? '').slice(0, 26);
        const on = station.roles.includes(selected);
        const primary = station.roles.find(role => role === selected) ?? view?.agent_id ?? station.roles[0];
        const animate = !economy && connection === 'connected' && status === 'working' && !view?.stale;
        const showBubble = view != null && ['working', 'blocked', 'waiting', 'failed'].includes(status);

        return (
          <g key={station.id} transform={`translate(${pos.x},${pos.y})`}
            className={on ? 'station station--on' : 'station'}
            role="button" tabIndex={0} data-testid={`station-${station.id}`}
            aria-label={`${station.label}: ${STATUS_LABEL[status]}`}
            onClick={() => onSelect(primary)}
            onKeyDown={event => { if (event.key === 'Enter' || event.key === ' ') onSelect(primary); }}>
            {/* Full-area hit target: pixel art leaves gaps, and an SVG group is only
                clickable where a child is painted. */}
            <rect className="station__hit" x={-70} y={-32} width={210} height={98}
              fill="transparent" pointerEvents="all" />
            <Desk tone={tone} />
            <g transform="translate(-96,14)">
              <Figure tone={tone} animate={animate} />
            </g>
            {station.id === 'render' && <g transform="translate(74,0)"><Rack /></g>}
            {showBubble && <Bubble text={label} tone={tone} />}
            <text x={-64} y={48} fontSize={11} fill="#edf0e9"
              fontFamily="ui-monospace, monospace">{station.label}</text>
            <text x={-64} y={62} fontSize={11} fill={tone}
              fontFamily="ui-monospace, monospace">{STATUS_LABEL[status]}</text>
          </g>
        );
      })}

      <g transform="translate(480,60)">
        <rect x={-96} y={0} width={192} height={30} fill="#18222b" stroke="#34434c" shapeRendering="crispEdges" />
        <text x={0} y={20} textAnchor="middle" fontSize={12} fill="#edf0e9"
          fontFamily="ui-monospace, monospace">PIXEL PRODUCTION STUDIO</text>
      </g>

      <g transform="translate(480,110)">
        <rect x={-70} y={0} width={140} height={26} fill="#18222b"
          stroke={approval ? '#e8bf7b' : '#34434c'} shapeRendering="crispEdges" />
        <text x={0} y={17} textAnchor="middle" fontSize={11}
          fill={approval ? '#e8bf7b' : '#a6b5b9'}
          fontFamily="ui-monospace, monospace">
          {approval ? 'APPROVAL REQUIRED' : 'NO APPROVAL WAITING'}
        </text>
      </g>
    </svg>
  );
}
