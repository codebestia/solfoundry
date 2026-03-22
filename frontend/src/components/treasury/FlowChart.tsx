/**
 * FlowChart — pure-SVG inflow/outflow bar chart with daily/weekly/monthly tabs.
 * No external charting library required.
 */
import React, { useState } from 'react';
import type { FlowView, FlowPoint } from '../../types/treasuryDashboard';
import { useTreasuryFlow } from '../../hooks/useTreasuryDashboard';

const VIEWS: { label: string; value: FlowView }[] = [
  { label: 'Daily', value: 'daily' },
  { label: 'Weekly', value: 'weekly' },
  { label: 'Monthly', value: 'monthly' },
];

const CHART_H = 180;
const BAR_GAP = 2;

function formatDate(iso: string, view: FlowView): string {
  const d = new Date(iso);
  if (view === 'monthly') return d.toLocaleDateString(undefined, { month: 'short', year: '2-digit' });
  if (view === 'weekly') return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
  return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
}

function SvgBars({ points, view }: { points: FlowPoint[]; view: FlowView }) {
  if (!points.length) {
    return (
      <div className="flex items-center justify-center h-[180px] text-gray-600 text-sm">
        No data for this period
      </div>
    );
  }

  const maxVal = Math.max(...points.flatMap((p) => [p.inflow, p.outflow]), 1);
  const totalW = 600;
  const barW = Math.max(4, Math.floor((totalW - BAR_GAP) / points.length / 2) - BAR_GAP);
  const [tooltip, setTooltip] = useState<{ x: number; y: number; p: FlowPoint } | null>(null);

  return (
    <div className="relative" data-testid="flow-chart-svg">
      <svg
        viewBox={`0 0 ${totalW} ${CHART_H + 24}`}
        className="w-full"
        aria-label={`Inflow/outflow ${view} chart`}
      >
        {/* Y-axis gridlines */}
        {[0, 0.25, 0.5, 0.75, 1].map((frac) => {
          const y = CHART_H - frac * CHART_H;
          return (
            <g key={frac}>
              <line x1={0} x2={totalW} y1={y} y2={y} stroke="rgba(255,255,255,0.05)" strokeWidth={1} />
              <text x={2} y={y - 2} fontSize={8} fill="rgba(255,255,255,0.3)">
                {Math.round(frac * maxVal).toLocaleString()}
              </text>
            </g>
          );
        })}

        {points.map((p, i) => {
          const groupW = totalW / points.length;
          const groupX = i * groupW;
          const inH = Math.max(1, (p.inflow / maxVal) * CHART_H);
          const outH = Math.max(1, (p.outflow / maxVal) * CHART_H);

          return (
            <g key={p.date}
               onMouseEnter={(e) => setTooltip({ x: groupX + groupW / 2, y: e.clientY, p })}
               onMouseLeave={() => setTooltip(null)}
               style={{ cursor: 'pointer' }}>
              {/* Inflow bar */}
              <rect
                x={groupX + BAR_GAP}
                y={CHART_H - inH}
                width={barW}
                height={inH}
                fill="#14F195"
                fillOpacity={0.7}
                rx={2}
              />
              {/* Outflow bar */}
              <rect
                x={groupX + BAR_GAP + barW + BAR_GAP}
                y={CHART_H - outH}
                width={barW}
                height={outH}
                fill="#9945FF"
                fillOpacity={0.7}
                rx={2}
              />
              {/* X-axis label — show every N-th */}
              {i % Math.max(1, Math.floor(points.length / 8)) === 0 && (
                <text
                  x={groupX + groupW / 2}
                  y={CHART_H + 16}
                  textAnchor="middle"
                  fontSize={8}
                  fill="rgba(255,255,255,0.4)"
                >
                  {formatDate(p.date, view)}
                </text>
              )}
            </g>
          );
        })}
      </svg>

      {/* Tooltip */}
      {tooltip && (
        <div
          className="absolute pointer-events-none z-10 rounded-lg bg-[#1a1a2e] border border-white/10 px-3 py-2 text-xs shadow-xl"
          style={{ left: `${Math.min(tooltip.x, totalW - 120)}px`, top: 0 }}
        >
          <p className="text-gray-300 font-medium mb-1">{formatDate(tooltip.p.date, view)}</p>
          <p className="text-[#14F195]">In: {tooltip.p.inflow.toLocaleString()}</p>
          <p className="text-[#9945FF]">Out: {tooltip.p.outflow.toLocaleString()}</p>
          <p className={tooltip.p.net >= 0 ? 'text-[#14F195]' : 'text-red-400'}>
            Net: {tooltip.p.net >= 0 ? '+' : ''}{tooltip.p.net.toLocaleString()}
          </p>
        </div>
      )}

      {/* Legend */}
      <div className="flex gap-4 mt-2">
        <span className="flex items-center gap-1 text-xs text-gray-400">
          <span className="inline-block w-3 h-3 rounded-sm bg-[#14F195]/70" /> Inflow (buybacks)
        </span>
        <span className="flex items-center gap-1 text-xs text-gray-400">
          <span className="inline-block w-3 h-3 rounded-sm bg-[#9945FF]/70" /> Outflow (payouts)
        </span>
      </div>
    </div>
  );
}

interface FlowChartProps {
  className?: string;
}

export function FlowChart({ className = '' }: FlowChartProps) {
  const [view, setView] = useState<FlowView>('daily');
  const { data, isLoading } = useTreasuryFlow(view);

  return (
    <div
      className={`rounded-xl border border-white/10 bg-white/5 p-5 ${className}`}
      data-testid="flow-chart"
    >
      <div className="flex items-center justify-between mb-4 flex-wrap gap-2">
        <h3 className="text-sm font-semibold text-gray-300 uppercase tracking-wide">
          Inflow / Outflow
        </h3>
        <div className="flex gap-1">
          {VIEWS.map((v) => (
            <button
              key={v.value}
              onClick={() => setView(v.value)}
              className={`px-3 py-1 text-xs rounded-lg transition-all ${
                view === v.value
                  ? 'bg-[#9945FF]/30 text-[#9945FF] font-medium'
                  : 'text-gray-400 hover:text-white hover:bg-white/10'
              }`}
              data-testid={`flow-tab-${v.value}`}
            >
              {v.label}
            </button>
          ))}
        </div>
      </div>

      {isLoading ? (
        <div className="h-[180px] flex items-center justify-center">
          <div className="w-5 h-5 border-2 border-[#9945FF] border-t-transparent rounded-full animate-spin" />
        </div>
      ) : (
        <SvgBars points={data?.points ?? []} view={view} />
      )}
    </div>
  );
}
