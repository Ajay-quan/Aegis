// SPDX-License-Identifier: FSL-1.1-ALv2
// Copyright 2026 AegisTrace contributors
"use client";
import { useEffect, useMemo, useRef, useState } from "react";

export interface Point { t: string; [k: string]: number | string }
export interface Series { key: string; label: string; color: string }

/** Stacked bar time series. Crosshair + one tooltip listing every series;
 * 2px surface gap between stacked segments; recessive grid; legend above. */
export function StackedBars({ points, series, step, height = 220, dim = false }: {
  points: Point[]; series: Series[]; step: string; height?: number; dim?: boolean;
}) {
  const wrap = useRef<HTMLDivElement>(null);
  const [w, setW] = useState(800);
  const [hover, setHover] = useState<number | null>(null);

  useEffect(() => {
    if (!wrap.current) return;
    const ro = new ResizeObserver(([e]) => setW(Math.max(280, Math.floor(e!.contentRect.width))));
    ro.observe(wrap.current);
    return () => ro.disconnect();
  }, []);

  const pad = { l: 36, r: 8, t: 8, b: 22 };
  const iw = w - pad.l - pad.r;
  const ih = height - pad.t - pad.b;
  const totals = points.map((p) => series.reduce((a, s) => a + Number(p[s.key] ?? 0), 0));
  const rawMax = Math.max(1, ...totals);
  const nice = useMemo(() => {
    const mag = 10 ** Math.floor(Math.log10(rawMax));
    const n = [1, 2, 2.5, 5, 10].find((m) => m * mag >= rawMax) ?? 10;
    return n * mag;
  }, [rawMax]);
  const y = (v: number) => pad.t + ih - (v / nice) * ih;
  const slot = iw / Math.max(1, points.length);
  const bw = Math.max(2, Math.min(28, slot - 2));
  const ticks = [0, nice / 2, nice];
  const fmtT = (iso: string) => {
    const d = new Date(iso);
    return step.includes("hour") && !step.startsWith("1 ")
      ? d.toLocaleString([], { weekday: "short", hour: "numeric" })
      : d.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
  };
  const labelEvery = Math.max(1, Math.ceil(points.length / Math.max(2, Math.floor(iw / 90))));

  function onMove(e: React.PointerEvent<SVGSVGElement>) {
    const r = e.currentTarget.getBoundingClientRect();
    const i = Math.floor((e.clientX - r.left - pad.l) / slot);
    setHover(i >= 0 && i < points.length ? i : null);
  }

  const hp = hover !== null ? points[hover] : null;
  const tipLeft = hover !== null ? Math.min(w - 190, Math.max(0, pad.l + hover * slot + slot / 2 + 12)) : 0;

  return (
    <div ref={wrap} className={`relative ${dim ? "refetching" : ""}`}>
      <svg width={w} height={height} role="img" aria-label={`Stacked bar chart of ${series.map((s) => s.label).join(", ")}`}
           onPointerMove={onMove} onPointerLeave={() => setHover(null)} className="block touch-none">
        {ticks.map((t) => (
          <g key={t}>
            <line x1={pad.l} x2={w - pad.r} y1={y(t)} y2={y(t)} stroke="var(--grid)" strokeWidth={1} />
            <text x={pad.l - 8} y={y(t) + 3.5} textAnchor="end" fontSize={10.5} fill="var(--muted)" className="tnum">{Math.round(t)}</text>
          </g>
        ))}
        {hover !== null ? (
          <rect x={pad.l + hover * slot} y={pad.t} width={slot} height={ih} fill="rgba(255,255,255,0.035)" />
        ) : null}
        {points.map((p, i) => {
          let acc = 0;
          const x = pad.l + i * slot + (slot - bw) / 2;
          const segs = series.map((s) => {
            const v = Number(p[s.key] ?? 0);
            const y0 = y(acc), y1 = y(acc + v);
            acc += v;
            return { s, v, y0, y1 };
          }).filter((g) => g.v > 0);
          return (
            <g key={p.t} opacity={hover === null || hover === i ? 1 : 0.55}>
              {segs.map((g, j) => {
                const top = j === segs.length - 1;
                const h = Math.max(1, g.y0 - g.y1 - (top ? 0 : 2)); // 2px surface gap between segments
                return top ? (
                  <path key={g.s.key} fill={g.s.color}
                        d={`M${x},${g.y0} V${g.y0 - h + Math.min(4, h)} q0,-${Math.min(4, h)} ${Math.min(4, bw / 2)},-${Math.min(4, h)}
                            H${x + bw - Math.min(4, bw / 2)} q${Math.min(4, bw / 2)},0 ${Math.min(4, bw / 2)},${Math.min(4, h)} V${g.y0} Z`} />
                ) : <rect key={g.s.key} x={x} y={g.y0 - h} width={bw} height={h} fill={g.s.color} />;
              })}
            </g>
          );
        })}
        {points.map((p, i) => {
          const cx = pad.l + i * slot + slot / 2;
          // Skip labels that would be clipped at the right edge.
          return i % labelEvery === 0 && cx < w - pad.r - 28 ? (
            <text key={p.t} x={cx} y={height - 6} textAnchor={i === 0 ? "start" : "middle"} fontSize={10.5} fill="var(--muted)">{fmtT(p.t)}</text>
          ) : null;
        })}
      </svg>
      {hp ? (
        <div className="pointer-events-none absolute top-2 z-10 w-[180px] rounded-lg border px-3 py-2.5 text-[13px] shadow-2xl fade-in"
             style={{ left: tipLeft, background: "var(--panel-2)", borderColor: "var(--border-strong)" }}>
          <div className="mb-1.5 text-[12px] muted">{new Date(hp.t).toLocaleString([], { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" })}</div>
          {series.map((s) => (
            <div key={s.key} className="flex items-center gap-2 py-0.5">
              <span className="h-[2px] w-3 rounded" style={{ background: s.color }} />
              <span className="flex-1 text-2">{s.label}</span>
              <span className="tnum font-semibold">{Number(hp[s.key] ?? 0).toLocaleString()}</span>
            </div>
          ))}
        </div>
      ) : null}
    </div>
  );
}

export function Legend({ series }: { series: Series[] }) {
  return (
    <ul className="flex flex-wrap items-center gap-x-4 gap-y-1 text-[13px] text-2">
      {series.map((s) => (
        <li key={s.key} className="flex items-center gap-1.5">
          <span className="h-2.5 w-2.5 rounded-[3px]" style={{ background: s.color }} />{s.label}
        </li>
      ))}
    </ul>
  );
}

export function Sparkline({ values, color, height = 28 }: { values: number[]; color: string; height?: number }) {
  const w = 120;
  const max = Math.max(1, ...values);
  const step = w / Math.max(1, values.length - 1);
  const pts = values.map((v, i) => `${(i * step).toFixed(1)},${(height - 2 - (v / max) * (height - 4)).toFixed(1)}`);
  return (
    <svg viewBox={`0 0 ${w} ${height}`} preserveAspectRatio="none" className="h-7 w-full" aria-hidden>
      <polyline points={pts.join(" ")} fill="none" stroke={color} strokeWidth={2} strokeLinejoin="round" strokeLinecap="round"
                vectorEffect="non-scaling-stroke" />
    </svg>
  );
}
