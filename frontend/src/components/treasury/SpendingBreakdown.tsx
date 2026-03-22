/**
 * SpendingBreakdown — FNDRY bounty spending by tier with period selector.
 */
import React, { useState } from 'react';
import type { SpendingBreakdownResponse } from '../../types/treasuryDashboard';
import { useTreasurySpending } from '../../hooks/useTreasuryDashboard';

const TIER_LABELS: Record<string, { label: string; color: string }> = {
  '1': { label: 'T1 · Entry', color: 'bg-amber-700' },
  '2': { label: 'T2 · Mid',   color: 'bg-gray-400' },
  '3': { label: 'T3 · Senior', color: 'bg-yellow-500' },
  unlinked: { label: 'Unlinked', color: 'bg-gray-600' },
};

const PERIODS = [
  { label: '7d',   value: 7 },
  { label: '30d',  value: 30 },
  { label: '90d',  value: 90 },
  { label: '365d', value: 365 },
];

function TierBar({ tier, pct, color }: { tier: string; pct: number; color: string }) {
  return (
    <div className="flex items-center gap-3">
      <span className="text-xs text-gray-400 w-24 shrink-0">
        {TIER_LABELS[tier]?.label ?? tier}
      </span>
      <div className="flex-1 h-2 rounded-full bg-white/5">
        <div
          className={`h-2 rounded-full ${color} transition-all duration-500`}
          style={{ width: `${pct}%` }}
        />
      </div>
      <span className="text-xs text-gray-300 w-12 text-right">{pct}%</span>
    </div>
  );
}

interface SpendingBreakdownProps {
  className?: string;
}

export function SpendingBreakdown({ className = '' }: SpendingBreakdownProps) {
  const [period, setPeriod] = useState(30);
  const { data, isLoading } = useTreasurySpending(period);

  return (
    <div
      className={`rounded-xl border border-white/10 bg-white/5 p-5 ${className}`}
      data-testid="spending-breakdown"
    >
      <div className="flex items-center justify-between mb-4 flex-wrap gap-2">
        <h3 className="text-sm font-semibold text-gray-300 uppercase tracking-wide">
          Spending by tier
        </h3>
        <div className="flex gap-1">
          {PERIODS.map((p) => (
            <button
              key={p.value}
              onClick={() => setPeriod(p.value)}
              className={`px-2 py-1 text-xs rounded transition-all ${
                period === p.value
                  ? 'bg-[#9945FF]/30 text-[#9945FF] font-medium'
                  : 'text-gray-500 hover:text-white hover:bg-white/10'
              }`}
              data-testid={`period-${p.value}`}
            >
              {p.label}
            </button>
          ))}
        </div>
      </div>

      {isLoading ? (
        <div className="space-y-3">
          {[1, 2, 3].map((i) => (
            <div key={i} className="flex items-center gap-3 animate-pulse">
              <div className="h-3 w-24 bg-white/10 rounded" />
              <div className="flex-1 h-2 bg-white/10 rounded-full" />
            </div>
          ))}
        </div>
      ) : data && data.tiers.length > 0 ? (
        <div className="space-y-3">
          {data.tiers.map((t) => (
            <TierBar
              key={t.tier}
              tier={t.tier}
              pct={t.pct_of_total}
              color={TIER_LABELS[t.tier]?.color ?? 'bg-gray-500'}
            />
          ))}
          <div className="pt-2 border-t border-white/5 flex items-center justify-between text-xs text-gray-500">
            <span>Total: {data.total_fndry.toLocaleString(undefined, { maximumFractionDigits: 0 })} $FNDRY</span>
            <span>Last {data.period_days} days</span>
          </div>
        </div>
      ) : (
        <p className="text-sm text-gray-500 py-4 text-center" data-testid="spending-empty">
          No payout data for this period
        </p>
      )}
    </div>
  );
}
