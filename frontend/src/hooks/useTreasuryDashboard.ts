/**
 * React Query hooks for the admin Treasury Dashboard.
 * All requests include Bearer ADMIN_API_KEY from sessionStorage.
 * Auto-refresh every 30 seconds on all queries.
 */
import { useQuery } from '@tanstack/react-query';
import { apiClient } from '../services/apiClient';
import type {
  TreasuryOverview,
  FlowResponse,
  FlowView,
  TransactionsResponse,
  SpendingBreakdownResponse,
} from '../types/treasuryDashboard';

const REFRESH_MS = 30_000;

function getAdminToken(): string {
  return sessionStorage.getItem('treasury_admin_token') ?? '';
}

export function setTreasuryAdminToken(token: string) {
  sessionStorage.setItem('treasury_admin_token', token);
}

export function clearTreasuryAdminToken() {
  sessionStorage.removeItem('treasury_admin_token');
}

function adminFetch<T>(path: string): Promise<T> {
  return apiClient<T>(path, {
    headers: { Authorization: `Bearer ${getAdminToken()}` },
  });
}

export function useTreasuryOverview() {
  return useQuery<TreasuryOverview>({
    queryKey: ['treasury-dashboard', 'overview'],
    queryFn: () => adminFetch<TreasuryOverview>('/api/treasury-dashboard/overview'),
    staleTime: REFRESH_MS,
    refetchInterval: REFRESH_MS,
    retry: false,
  });
}

export function useTreasuryFlow(view: FlowView) {
  return useQuery<FlowResponse>({
    queryKey: ['treasury-dashboard', 'flow', view],
    queryFn: () => adminFetch<FlowResponse>(`/api/treasury-dashboard/flow?view=${view}`),
    staleTime: REFRESH_MS,
    refetchInterval: REFRESH_MS,
    retry: false,
  });
}

export function useTreasuryTransactions(limit = 50) {
  return useQuery<TransactionsResponse>({
    queryKey: ['treasury-dashboard', 'transactions', limit],
    queryFn: () =>
      adminFetch<TransactionsResponse>(`/api/treasury-dashboard/transactions?limit=${limit}`),
    staleTime: REFRESH_MS,
    refetchInterval: REFRESH_MS,
    retry: false,
  });
}

export function useTreasurySpending(periodDays = 30) {
  return useQuery<SpendingBreakdownResponse>({
    queryKey: ['treasury-dashboard', 'spending', periodDays],
    queryFn: () =>
      adminFetch<SpendingBreakdownResponse>(
        `/api/treasury-dashboard/spending/tier?period_days=${periodDays}`,
      ),
    staleTime: REFRESH_MS,
    refetchInterval: REFRESH_MS,
    retry: false,
  });
}

export function exportTreasuryCSV(token: string) {
  const url = `/api/treasury-dashboard/export.csv`;
  const a = document.createElement('a');
  a.href = url;
  a.download = `treasury_${new Date().toISOString().slice(0, 10)}.csv`;
  // Attach auth via a fetch + blob approach
  fetch(url, { headers: { Authorization: `Bearer ${token}` } })
    .then((res) => res.blob())
    .then((blob) => {
      const objectUrl = URL.createObjectURL(blob);
      a.href = objectUrl;
      a.click();
      URL.revokeObjectURL(objectUrl);
    });
}
