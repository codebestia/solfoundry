/**
 * Tests for the Treasury Dashboard UI components.
 * Mocks: wallet adapter, useTreasuryDashboard hooks.
 */
import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

// ---------------------------------------------------------------------------
// Mock data
// ---------------------------------------------------------------------------

const mockOverview = {
  fndry_balance: 1_000_000,
  sol_balance: 42.5,
  total_paid_out_fndry: 250_000,
  total_paid_out_sol: 10,
  total_payouts: 120,
  total_buybacks: 5,
  burn_rate_daily: 833.33,
  burn_rate_weekly: 5833.31,
  burn_rate_monthly: 25_000,
  runway_days: 1200,
  last_updated: '2026-03-22T10:00:00Z',
};

const mockFlow = {
  view: 'daily' as const,
  points: [
    { date: '2026-03-20', inflow: 0, outflow: 800, net: -800 },
    { date: '2026-03-21', inflow: 5000, outflow: 900, net: 4100 },
  ],
};

const mockTransactions = {
  total: 2,
  items: [
    {
      id: 'tx1', type: 'payout' as const, amount: 1000, token: 'FNDRY',
      recipient: 'alice', tx_hash: 'sig_abc123', solscan_url: 'https://solscan.io/tx/sig_abc123',
      status: 'confirmed', created_at: '2026-03-21T12:00:00Z',
    },
    {
      id: 'tx2', type: 'buyback' as const, amount: 5000, token: 'FNDRY',
      recipient: null, tx_hash: null, solscan_url: null,
      status: 'confirmed', created_at: '2026-03-20T10:00:00Z',
    },
  ],
};

const mockSpending = {
  tiers: [
    { tier: '3', total_fndry: 30000, payout_count: 10, pct_of_total: 60 },
    { tier: '2', total_fndry: 15000, payout_count: 8, pct_of_total: 30 },
    { tier: '1', total_fndry: 5000, payout_count: 5, pct_of_total: 10 },
  ],
  total_fndry: 50000,
  period_days: 30,
};

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

vi.mock('@solana/wallet-adapter-react', () => ({
  useWallet: vi.fn(() => ({ publicKey: { toBase58: () => 'OWNER_WALLET_AAA' } })),
}));

vi.mock('../hooks/useTreasuryDashboard', () => ({
  useTreasuryOverview: vi.fn(() => ({ data: mockOverview, isLoading: false, error: null })),
  useTreasuryFlow: vi.fn(() => ({ data: mockFlow, isLoading: false })),
  useTreasuryTransactions: vi.fn(() => ({ data: mockTransactions, isLoading: false })),
  useTreasurySpending: vi.fn(() => ({ data: mockSpending, isLoading: false })),
  setTreasuryAdminToken: vi.fn(),
  clearTreasuryAdminToken: vi.fn(),
  exportTreasuryCSV: vi.fn(),
}));

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function makeClient() {
  return new QueryClient({ defaultOptions: { queries: { retry: false } } });
}

function wrap(ui: React.ReactElement) {
  return render(<QueryClientProvider client={makeClient()}>{ui}</QueryClientProvider>);
}

// ---------------------------------------------------------------------------
// BalanceCards
// ---------------------------------------------------------------------------

describe('BalanceCards', () => {
  const { BalanceCards } = await import('../components/treasury/BalanceCards');

  it('renders FNDRY balance', () => {
    wrap(<BalanceCards overview={mockOverview} />);
    expect(screen.getByText('1,000,000')).toBeTruthy();
  });

  it('renders SOL balance', () => {
    wrap(<BalanceCards overview={mockOverview} />);
    expect(screen.getByText('42.500')).toBeTruthy();
  });

  it('renders runway in green when > 365d', () => {
    wrap(<BalanceCards overview={mockOverview} />);
    expect(screen.getByText('1,200 days')).toBeTruthy();
  });

  it('renders "No burn" when runway is null', () => {
    wrap(<BalanceCards overview={{ ...mockOverview, runway_days: null }} />);
    expect(screen.getByText('No burn')).toBeTruthy();
  });

  it('renders burn rate', () => {
    wrap(<BalanceCards overview={mockOverview} />);
    expect(screen.getByText('833')).toBeTruthy();
  });
});

// ---------------------------------------------------------------------------
// TransactionsTable
// ---------------------------------------------------------------------------

describe('TransactionsTable', () => {
  const { TransactionsTable } = await import('../components/treasury/TransactionsTable');

  it('renders payout row', () => {
    wrap(<TransactionsTable items={mockTransactions.items} total={2} />);
    expect(screen.getByText('Payout')).toBeTruthy();
    expect(screen.getByText('alice')).toBeTruthy();
  });

  it('renders buyback row', () => {
    wrap(<TransactionsTable items={mockTransactions.items} total={2} />);
    expect(screen.getByText('Buyback')).toBeTruthy();
  });

  it('renders solscan link for payout', () => {
    wrap(<TransactionsTable items={mockTransactions.items} total={2} />);
    const link = screen.getByTestId('tx-link-tx1');
    expect(link.getAttribute('href')).toBe('https://solscan.io/tx/sig_abc123');
  });

  it('shows total count', () => {
    wrap(<TransactionsTable items={mockTransactions.items} total={2} />);
    expect(screen.getByText('2 total')).toBeTruthy();
  });

  it('shows empty state when no items', () => {
    wrap(<TransactionsTable items={[]} total={0} />);
    expect(screen.getByTestId('transactions-empty')).toBeTruthy();
  });

  it('renders skeleton rows when loading', () => {
    wrap(<TransactionsTable items={[]} total={0} loading={true} />);
    // No rows rendered, skeleton shown
    expect(screen.queryByText('Payout')).toBeNull();
  });
});

// ---------------------------------------------------------------------------
// SpendingBreakdown
// ---------------------------------------------------------------------------

describe('SpendingBreakdown', () => {
  const { SpendingBreakdown } = await import('../components/treasury/SpendingBreakdown');

  it('renders tier bars', () => {
    wrap(<SpendingBreakdown />);
    expect(screen.getByText('T3 · Senior')).toBeTruthy();
    expect(screen.getByText('60%')).toBeTruthy();
  });

  it('shows total FNDRY', () => {
    wrap(<SpendingBreakdown />);
    expect(screen.getByText(/50,000/)).toBeTruthy();
  });

  it('renders period selector buttons', () => {
    wrap(<SpendingBreakdown />);
    expect(screen.getByTestId('period-7')).toBeTruthy();
    expect(screen.getByTestId('period-30')).toBeTruthy();
    expect(screen.getByTestId('period-90')).toBeTruthy();
  });

  it('shows empty state when no tier data', async () => {
    const { useTreasurySpending } = await import('../hooks/useTreasuryDashboard');
    vi.mocked(useTreasurySpending).mockReturnValueOnce({
      data: { tiers: [], total_fndry: 0, period_days: 30 },
      isLoading: false,
    } as any);
    wrap(<SpendingBreakdown />);
    expect(screen.getByTestId('spending-empty')).toBeTruthy();
  });
});

// ---------------------------------------------------------------------------
// FlowChart
// ---------------------------------------------------------------------------

describe('FlowChart', () => {
  const { FlowChart } = await import('../components/treasury/FlowChart');

  it('renders chart with bars', () => {
    wrap(<FlowChart />);
    expect(screen.getByTestId('flow-chart-svg')).toBeTruthy();
  });

  it('renders view tabs', () => {
    wrap(<FlowChart />);
    expect(screen.getByTestId('flow-tab-daily')).toBeTruthy();
    expect(screen.getByTestId('flow-tab-weekly')).toBeTruthy();
    expect(screen.getByTestId('flow-tab-monthly')).toBeTruthy();
  });

  it('switches to weekly view on click', async () => {
    wrap(<FlowChart />);
    fireEvent.click(screen.getByTestId('flow-tab-weekly'));
    await waitFor(() => {
      const { useTreasuryFlow } = require('../hooks/useTreasuryDashboard');
      expect(useTreasuryFlow).toHaveBeenCalledWith('weekly');
    });
  });
});

// ---------------------------------------------------------------------------
// TreasuryDashboardPage — gate logic
// ---------------------------------------------------------------------------

describe('TreasuryDashboardPage gates', () => {
  it('shows connect-wallet prompt when no wallet', async () => {
    const { useWallet } = await import('@solana/wallet-adapter-react');
    vi.mocked(useWallet).mockReturnValueOnce({ publicKey: null } as any);
    const { default: TreasuryDashboardPage } = await import('../pages/TreasuryDashboardPage');
    wrap(<TreasuryDashboardPage />);
    expect(screen.getByText('Connect your wallet')).toBeTruthy();
  });

  it('shows admin login form after wallet connected', async () => {
    // Clear sessionStorage so no existing token
    sessionStorage.removeItem('treasury_admin_token');
    const { default: TreasuryDashboardPage } = await import('../pages/TreasuryDashboardPage');
    wrap(<TreasuryDashboardPage />);
    expect(screen.getByTestId('admin-key-input')).toBeTruthy();
  });

  it('admin login button calls setTreasuryAdminToken', async () => {
    sessionStorage.removeItem('treasury_admin_token');
    const { setTreasuryAdminToken } = await import('../hooks/useTreasuryDashboard');
    const { default: TreasuryDashboardPage } = await import('../pages/TreasuryDashboardPage');
    wrap(<TreasuryDashboardPage />);
    fireEvent.change(screen.getByTestId('admin-key-input'), {
      target: { value: 'my-api-key' },
    });
    fireEvent.click(screen.getByTestId('admin-login-btn'));
    expect(vi.mocked(setTreasuryAdminToken)).toHaveBeenCalledWith('my-api-key');
  });
});
