/**
 * TransactionsTable — recent payout and buyback records with Solscan links.
 */
import React from 'react';
import type { TreasuryTransaction } from '../../types/treasuryDashboard';

interface TransactionsTableProps {
  items: TreasuryTransaction[];
  total: number;
  loading?: boolean;
  className?: string;
}

const TYPE_META: Record<string, { label: string; color: string }> = {
  payout:  { label: 'Payout',  color: 'text-[#9945FF]' },
  buyback: { label: 'Buyback', color: 'text-[#14F195]' },
};

function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString(undefined, {
    month: 'short', day: 'numeric', year: 'numeric',
    hour: '2-digit', minute: '2-digit',
  });
}

export function TransactionsTable({
  items,
  total,
  loading = false,
  className = '',
}: TransactionsTableProps) {
  return (
    <div
      className={`rounded-xl border border-white/10 bg-white/5 overflow-hidden ${className}`}
      data-testid="transactions-table"
    >
      <div className="px-4 py-3 border-b border-white/5 flex items-center justify-between">
        <h3 className="text-sm font-semibold text-gray-300 uppercase tracking-wide">
          Recent transactions
        </h3>
        <span className="text-xs text-gray-500">{total} total</span>
      </div>

      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-white/5 text-left">
              <th className="px-4 py-2 text-xs text-gray-500 font-medium">Type</th>
              <th className="px-4 py-2 text-xs text-gray-500 font-medium">Amount</th>
              <th className="px-4 py-2 text-xs text-gray-500 font-medium">Recipient</th>
              <th className="px-4 py-2 text-xs text-gray-500 font-medium">Status</th>
              <th className="px-4 py-2 text-xs text-gray-500 font-medium">Date</th>
              <th className="px-4 py-2 text-xs text-gray-500 font-medium">Explorer</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-white/5">
            {loading
              ? Array.from({ length: 6 }).map((_, i) => (
                  <tr key={i}>
                    {Array.from({ length: 6 }).map((__, j) => (
                      <td key={j} className="px-4 py-3">
                        <div className="h-3 bg-white/10 rounded animate-pulse w-16" />
                      </td>
                    ))}
                  </tr>
                ))
              : items.map((tx) => {
                  const meta = TYPE_META[tx.type] ?? { label: tx.type, color: 'text-gray-400' };
                  return (
                    <tr key={tx.id} className="hover:bg-white/5 transition-colors">
                      <td className="px-4 py-3">
                        <span className={`text-xs font-semibold ${meta.color}`}>{meta.label}</span>
                      </td>
                      <td className="px-4 py-3 font-mono text-white">
                        {tx.amount.toLocaleString(undefined, { maximumFractionDigits: 2 })} {tx.token}
                      </td>
                      <td className="px-4 py-3 text-gray-400 truncate max-w-[120px]">
                        {tx.recipient ?? <span className="text-gray-600">—</span>}
                      </td>
                      <td className="px-4 py-3">
                        <span
                          className={`inline-block text-xs px-2 py-0.5 rounded-full ${
                            tx.status === 'confirmed'
                              ? 'bg-[#14F195]/10 text-[#14F195]'
                              : tx.status === 'pending'
                                ? 'bg-amber-500/10 text-amber-400'
                                : 'bg-white/5 text-gray-400'
                          }`}
                        >
                          {tx.status ?? '—'}
                        </span>
                      </td>
                      <td className="px-4 py-3 text-gray-500 text-xs whitespace-nowrap">
                        {formatDate(tx.created_at)}
                      </td>
                      <td className="px-4 py-3">
                        {tx.solscan_url ? (
                          <a
                            href={tx.solscan_url}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="text-xs text-[#9945FF] hover:text-[#9945FF]/80 font-mono"
                            data-testid={`tx-link-${tx.id}`}
                          >
                            {tx.tx_hash?.slice(0, 8)}…
                          </a>
                        ) : (
                          <span className="text-gray-600 text-xs">—</span>
                        )}
                      </td>
                    </tr>
                  );
                })}
          </tbody>
        </table>
      </div>

      {!loading && items.length === 0 && (
        <div className="py-10 text-center text-gray-500 text-sm" data-testid="transactions-empty">
          No transactions yet
        </div>
      )}
    </div>
  );
}
