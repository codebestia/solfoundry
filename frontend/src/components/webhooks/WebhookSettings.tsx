'use client';

import React, { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { apiClient } from '../../services/apiClient';

interface Webhook {
  id: string;
  url: string;
  active: boolean;
  created_at: string;
  last_delivery_at?: string;
  last_delivery_status?: string;
  failure_count: number;
}

interface WebhookStats {
  total_deliveries: number;
  success_rate: number;
  failure_rate: number;
  last_10_deliveries: {
    batch_id: string;
    status: 'success' | 'failed';
    response_code?: number;
    delivered_at: string;
    error?: string;
  }[];
}

export function WebhookSettings() {
  const queryClient = useQueryClient();
  const [newUrl, setNewUrl] = useState('');
  const [newSecret, setNewSecret] = useState('');
  const [isAdding, setIsAdding] = useState(false);

  const { data: webhooks, isLoading } = useQuery({
    queryKey: ['webhooks'],
    queryFn: () => apiClient<{ items: Webhook[] }>('/api/webhooks').then(res => res.items),
  });

  const registerMutation = useMutation({
    mutationFn: (data: { url: string; secret: string }) => 
      apiClient('/api/webhooks/register', { method: 'POST', body: JSON.stringify(data) }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['webhooks'] });
      setNewUrl('');
      setNewSecret('');
      setIsAdding(false);
    },
  });

  const unregisterMutation = useMutation({
    mutationFn: (id: string) => 
      apiClient(`/api/webhooks/${id}`, { method: 'DELETE' }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['webhooks'] });
    },
  });

  const testMutation = useMutation({
    mutationFn: (id: string) => 
      apiClient(`/api/webhooks/${id}/test`, { method: 'POST' }),
  });

  if (isLoading) return <div className="p-4 text-center">Loading webhooks...</div>;

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h3 className="text-lg font-bold text-gray-900 dark:text-white">Webhook Subscriptions</h3>
        <button 
          onClick={() => setIsAdding(!isAdding)}
          className="px-3 py-1.5 bg-solana-purple text-white rounded text-sm hover:opacity-90"
        >
          {isAdding ? 'Cancel' : 'Add Webhook'}
        </button>
      </div>

      {isAdding && (
        <div className="bg-white dark:bg-surface-100 p-4 rounded-lg border border-gray-200 dark:border-white/5 space-y-4">
          <div>
            <label className="block text-xs text-gray-400 mb-1">Target URL (HTTPS)</label>
            <input 
              type="url" 
              value={newUrl}
              onChange={(e) => setNewUrl(e.target.value)}
              placeholder="https://your-api.com/webhooks"
              className="w-full bg-gray-50 dark:bg-surface border border-gray-200 dark:border-white/10 rounded px-3 py-2 text-sm text-gray-900 dark:text-white"
            />
          </div>
          <div>
            <label className="block text-xs text-gray-400 mb-1">Secret (min 16 chars)</label>
            <input 
              type="password" 
              value={newSecret}
              onChange={(e) => setNewSecret(e.target.value)}
              placeholder="HMAC-SHA256 Signing Secret"
              className="w-full bg-gray-50 dark:bg-surface border border-gray-200 dark:border-white/10 rounded px-3 py-2 text-sm text-gray-900 dark:text-white"
            />
          </div>
          <button 
            onClick={() => registerMutation.mutate({ url: newUrl, secret: newSecret })}
            disabled={registerMutation.isPending || !newUrl || newSecret.length < 16}
            className="w-full py-2 bg-solana-green text-black font-bold rounded text-sm disabled:opacity-50"
          >
            {registerMutation.isPending ? 'Registering...' : 'Register Webhook'}
          </button>
        </div>
      )}

      <div className="space-y-4">
        {webhooks?.map((wh) => (
          <WebhookItem 
            key={wh.id} 
            webhook={wh} 
            onUnregister={() => unregisterMutation.mutate(wh.id)}
            onTest={() => testMutation.mutate(wh.id)}
          />
        ))}
        {webhooks?.length === 0 && !isAdding && (
          <div className="text-center py-10 text-gray-500 text-sm italic">
            No webhooks registered yet.
          </div>
        )}
      </div>
    </div>
  );
}

function WebhookItem({ webhook, onUnregister, onTest }: { webhook: Webhook; onUnregister: () => void; onTest: () => void }) {
  const [showStats, setShowStats] = useState(false);
  const { data: stats } = useQuery({
    queryKey: ['webhook-stats', webhook.id],
    queryFn: () => apiClient<WebhookStats>(`/api/webhooks/${webhook.id}/stats`),
    enabled: showStats,
  });

  return (
    <div className="bg-white dark:bg-surface-100 rounded-lg border border-gray-200 dark:border-white/5 overflow-hidden">
      <div className="p-4 flex items-center justify-between">
        <div className="flex-1 min-w-0">
          <p className="text-sm font-medium text-gray-900 dark:text-white truncate">{webhook.url}</p>
          <div className="flex items-center gap-3 mt-1">
            <span className={`text-[10px] px-1.5 py-0.5 rounded uppercase font-bold ${webhook.active ? 'bg-green-400/10 text-green-400' : 'bg-gray-400/10 text-gray-400'}`}>
              {webhook.active ? 'Active' : 'Inactive'}
            </span>
            <span className="text-[10px] text-gray-500">
              ID: {webhook.id.slice(0, 8)}...
            </span>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <button 
            onClick={() => setShowStats(!showStats)} 
            className="p-1.5 text-gray-400 hover:text-white"
            title="View Stats"
          >
            📊
          </button>
          <button 
            onClick={onTest} 
            className="p-1.5 text-gray-400 hover:text-white"
            title="Test Event"
          >
            🔔
          </button>
          <button 
            onClick={onUnregister} 
            className="p-1.5 text-red-400 hover:text-red-500"
            title="Delete"
          >
            🗑️
          </button>
        </div>
      </div>

      {showStats && stats && (
        <div className="bg-gray-50 dark:bg-black/20 p-4 border-t border-gray-200 dark:border-white/5 space-y-4">
          <div className="grid grid-cols-3 gap-2">
            <div className="text-center">
              <p className="text-[10px] text-gray-400">Deliveries</p>
              <p className="text-sm font-bold text-gray-900 dark:text-white">{stats.total_deliveries}</p>
            </div>
            <div className="text-center">
              <p className="text-[10px] text-gray-400">Success</p>
              <p className="text-sm font-bold text-green-400">{(stats.success_rate * 100).toFixed(1)}%</p>
            </div>
            <div className="text-center">
              <p className="text-[10px] text-gray-400">Failures</p>
              <p className="text-sm font-bold text-red-400">{(stats.failure_rate * 100).toFixed(1)}%</p>
            </div>
          </div>

          <div className="space-y-1">
            <p className="text-[10px] text-gray-400 font-bold mb-1 uppercase">Recent Deliveries (Batch ID / Code)</p>
            {stats.last_10_deliveries.map((d) => (
              <div key={d.batch_id} className="flex items-center justify-between text-[11px] py-1">
                <span className="text-gray-500 font-mono">{d.batch_id.slice(0, 8)}...</span>
                <div className="flex items-center gap-2">
                  <span className={d.status === 'success' ? 'text-green-400' : 'text-red-400'}>
                    {d.status.toUpperCase()} {d.response_code}
                  </span>
                  <span className="text-gray-600 italic">
                    {new Date(d.delivered_at).toLocaleTimeString()}
                  </span>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
