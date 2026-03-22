/**
 * BalanceCards — treasury balance, burn rate, and runway cards.
 */
import React from 'react';
import type { TreasuryOverview } from '../../types/treasuryDashboard';

interface BalanceCardsProps {
  overview: TreasuryOverview;
  className?: string;
}

function fmt(n: number, decimals = 0): string {
  return n.toLocaleString(undefined, {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  });
}

function RunwayBadge({ days }: { days: number | null }) {
  if (days === null) return <span className="text-xs text-gray-500">No burn</span>;
  const color = days > 365 ? 'text-[#14F195]' : days > 90 ? 'text-amber-400' : 'text-red-400';
  return <span className={`text-2xl font-bold ${color}`}>{fmt(days)} days</span>;
}

export function BalanceCards({ overview, className = '' }: BalanceCardsProps) {
  return (
    <div
      className={`grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3 ${className}`}
      data-testid="balance-cards"
    >
      {/* $FNDRY balance */}
      <div className="col-span-2 rounded-xl border border-[#9945FF]/30 bg-[#9945FF]/5 p-4">
        <p className="text-xs text-gray-400 uppercase tracking-wide mb-1">Treasury $FNDRY</p>
        <p className="text-2xl font-bold text-white">{fmt(overview.fndry_balance)}</p>
        <p className="text-xs text-gray-500 mt-1">$FNDRY</p>
      </div>

      {/* SOL balance */}
      <div className="rounded-xl border border-white/10 bg-white/5 p-4">
        <p className="text-xs text-gray-400 uppercase tracking-wide mb-1">SOL balance</p>
        <p className="text-2xl font-bold text-white">{fmt(overview.sol_balance, 3)}</p>
        <p className="text-xs text-gray-500 mt-1">SOL</p>
      </div>

      {/* Runway */}
      <div className="rounded-xl border border-white/10 bg-white/5 p-4">
        <p className="text-xs text-gray-400 uppercase tracking-wide mb-1">Runway</p>
        <RunwayBadge days={overview.runway_days} />
        <p className="text-xs text-gray-500 mt-1">at current burn</p>
      </div>

      {/* Burn rate */}
      <div className="rounded-xl border border-white/10 bg-white/5 p-4">
        <p className="text-xs text-gray-400 uppercase tracking-wide mb-1">Burn / day</p>
        <p className="text-xl font-bold text-amber-400">{fmt(overview.burn_rate_daily)}</p>
        <p className="text-xs text-gray-500 mt-1">$FNDRY (30d avg)</p>
      </div>

      {/* Payouts */}
      <div className="rounded-xl border border-white/10 bg-white/5 p-4">
        <p className="text-xs text-gray-400 uppercase tracking-wide mb-1">Total paid out</p>
        <p className="text-xl font-bold text-white">{fmt(overview.total_paid_out_fndry)}</p>
        <p className="text-xs text-gray-500 mt-1">{overview.total_payouts} payouts</p>
      </div>
    </div>
  );
}
