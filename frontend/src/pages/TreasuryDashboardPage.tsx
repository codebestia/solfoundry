/**
 * TreasuryDashboardPage — admin-only, owner-wallet-gated treasury health dashboard.
 *
 * Gate logic:
 *  1. Wallet must be connected.
 *  2. Connected wallet must match VITE_OWNER_WALLET env var.
 *  3. Admin API key must be entered to authenticate API calls.
 *
 * All data is read-only — no treasury mutations are possible from this UI.
 */
import React, { useState, useCallback } from 'react';
import { useWallet } from '@solana/wallet-adapter-react';
import { useQueryClient } from '@tanstack/react-query';
import {
  useTreasuryOverview,
  useTreasuryTransactions,
  setTreasuryAdminToken,
  clearTreasuryAdminToken,
  exportTreasuryCSV,
} from '../hooks/useTreasuryDashboard';
import { BalanceCards } from '../components/treasury/BalanceCards';
import { FlowChart } from '../components/treasury/FlowChart';
import { TransactionsTable } from '../components/treasury/TransactionsTable';
import { SpendingBreakdown } from '../components/treasury/SpendingBreakdown';

const OWNER_WALLET = import.meta.env.VITE_OWNER_WALLET as string | undefined;

// ---------------------------------------------------------------------------
// Admin login form
// ---------------------------------------------------------------------------

function AdminLoginForm({ onLogin }: { onLogin: (key: string) => void }) {
  const [key, setKey] = useState('');

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (key.trim()) onLogin(key.trim());
  };

  return (
    <div className="flex flex-col items-center justify-center py-24 gap-6 max-w-sm mx-auto">
      <p className="text-3xl">🔐</p>
      <p className="text-lg font-semibold text-white">Treasury Dashboard</p>
      <p className="text-sm text-gray-400 text-center">
        Enter your admin API key to access the read-only treasury health dashboard.
      </p>
      <form onSubmit={handleSubmit} className="w-full flex flex-col gap-3">
        <input
          type="password"
          value={key}
          onChange={(e) => setKey(e.target.value)}
          placeholder="Admin API key"
          className="w-full rounded-lg bg-white/5 border border-white/10 px-3 py-2.5 text-white text-sm focus:outline-none focus:border-[#9945FF]"
          data-testid="admin-key-input"
        />
        <button
          type="submit"
          disabled={!key.trim()}
          className="rounded-lg py-2.5 text-sm font-semibold bg-[#9945FF] text-white hover:bg-[#9945FF]/90 disabled:opacity-50"
          data-testid="admin-login-btn"
        >
          Access dashboard
        </button>
      </form>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Dashboard body
// ---------------------------------------------------------------------------

function DashboardBody({ adminToken, onSignOut }: { adminToken: string; onSignOut: () => void }) {
  const overviewQuery = useTreasuryOverview();
  const txQuery = useTreasuryTransactions(50);
  const qc = useQueryClient();

  const handleRefresh = () => {
    qc.invalidateQueries({ queryKey: ['treasury-dashboard'] });
  };

  // Detect 401/403 → auto sign-out
  const authError =
    overviewQuery.error instanceof Error &&
    (overviewQuery.error.message.includes('401') ||
      overviewQuery.error.message.includes('403'));

  if (authError) {
    onSignOut();
    return null;
  }

  return (
    <div className="space-y-6" data-testid="treasury-dashboard">
      {/* Header */}
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div>
          <h1 className="text-xl font-bold text-white">Treasury Dashboard</h1>
          {overviewQuery.data && (
            <p className="text-xs text-gray-500 mt-0.5">
              Last updated: {new Date(overviewQuery.data.last_updated).toLocaleTimeString()}
              {' · '}Auto-refresh every 30s
            </p>
          )}
        </div>
        <div className="flex gap-2">
          <button
            onClick={handleRefresh}
            className="px-3 py-1.5 text-xs rounded-lg bg-white/10 text-gray-300 hover:bg-white/20"
            data-testid="refresh-btn"
          >
            ↻ Refresh
          </button>
          <button
            onClick={() => exportTreasuryCSV(adminToken)}
            className="px-3 py-1.5 text-xs rounded-lg bg-[#14F195]/15 text-[#14F195] hover:bg-[#14F195]/25"
            data-testid="export-csv-btn"
          >
            ↓ Export CSV
          </button>
          <button
            onClick={onSignOut}
            className="px-3 py-1.5 text-xs rounded-lg bg-white/5 text-gray-400 hover:bg-white/10"
            data-testid="sign-out-btn"
          >
            Sign out
          </button>
        </div>
      </div>

      {/* Balance cards */}
      {overviewQuery.data && <BalanceCards overview={overviewQuery.data} />}
      {overviewQuery.isLoading && (
        <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3">
          {Array.from({ length: 6 }).map((_, i) => (
            <div key={i} className="rounded-xl border border-white/5 bg-white/5 h-24 animate-pulse" />
          ))}
        </div>
      )}

      {/* Charts row */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <FlowChart className="lg:col-span-2" />
        <SpendingBreakdown />
      </div>

      {/* Transactions */}
      <TransactionsTable
        items={txQuery.data?.items ?? []}
        total={txQuery.data?.total ?? 0}
        loading={txQuery.isLoading}
      />

      {/* Read-only notice */}
      <p className="text-xs text-gray-600 text-center">
        Read-only dashboard — no treasury actions are available from this interface.
      </p>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function TreasuryDashboardPage() {
  const { publicKey } = useWallet();
  const wallet = publicKey?.toBase58() ?? null;
  const [adminToken, setAdminTokenState] = useState<string | null>(
    () => sessionStorage.getItem('treasury_admin_token'),
  );

  const handleLogin = useCallback((key: string) => {
    setTreasuryAdminToken(key);
    setAdminTokenState(key);
  }, []);

  const handleSignOut = useCallback(() => {
    clearTreasuryAdminToken();
    setAdminTokenState(null);
  }, []);

  // Gate 1: wallet required
  if (!wallet) {
    return (
      <main className="max-w-5xl mx-auto px-4 py-12">
        <div className="flex flex-col items-center gap-4 py-24">
          <p className="text-3xl">🔒</p>
          <p className="text-lg font-semibold text-white">Connect your wallet</p>
          <p className="text-sm text-gray-400">This dashboard requires wallet authentication.</p>
        </div>
      </main>
    );
  }

  // Gate 2: owner wallet check (skip if VITE_OWNER_WALLET not configured)
  if (OWNER_WALLET && wallet !== OWNER_WALLET) {
    return (
      <main className="max-w-5xl mx-auto px-4 py-12">
        <div className="flex flex-col items-center gap-4 py-24">
          <p className="text-3xl">⛔</p>
          <p className="text-lg font-semibold text-white">Access denied</p>
          <p className="text-sm text-gray-400">
            This dashboard is restricted to the treasury owner wallet.
          </p>
        </div>
      </main>
    );
  }

  // Gate 3: admin API key
  if (!adminToken) {
    return (
      <main className="max-w-5xl mx-auto px-4 py-12">
        <AdminLoginForm onLogin={handleLogin} />
      </main>
    );
  }

  return (
    <main className="max-w-6xl mx-auto px-4 sm:px-6 py-8 sm:py-12">
      <DashboardBody adminToken={adminToken} onSignOut={handleSignOut} />
    </main>
  );
}
