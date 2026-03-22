/** Types for the admin-only Treasury Dashboard. */

export interface TreasuryOverview {
  fndry_balance: number;
  sol_balance: number;
  total_paid_out_fndry: number;
  total_paid_out_sol: number;
  total_payouts: number;
  total_buybacks: number;
  burn_rate_daily: number;
  burn_rate_weekly: number;
  burn_rate_monthly: number;
  runway_days: number | null;
  last_updated: string;
}

export interface FlowPoint {
  date: string;
  inflow: number;
  outflow: number;
  net: number;
}

export interface FlowResponse {
  view: 'daily' | 'weekly' | 'monthly';
  points: FlowPoint[];
}

export type FlowView = 'daily' | 'weekly' | 'monthly';

export interface TreasuryTransaction {
  id: string;
  type: 'payout' | 'buyback';
  amount: number;
  token: string;
  recipient: string | null;
  tx_hash: string | null;
  solscan_url: string | null;
  status: string | null;
  created_at: string;
}

export interface TransactionsResponse {
  items: TreasuryTransaction[];
  total: number;
}

export interface TierSpend {
  tier: string;
  total_fndry: number;
  payout_count: number;
  pct_of_total: number;
}

export interface SpendingBreakdownResponse {
  tiers: TierSpend[];
  total_fndry: number;
  period_days: number;
}
