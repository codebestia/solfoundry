/**
 * AdminLayout — sidebar + header shell for all admin panels.
 * Handles auth gate: prompts for API key if none stored.
 */
import { useState, type ReactNode } from 'react';
import { useAdminWebSocket } from '../../hooks/useAdminWebSocket';
import { getAdminToken, setAdminToken, clearAdminToken } from '../../hooks/useAdminData';
import type { AdminSection } from '../../types/admin';

interface NavItem {
  id: AdminSection;
  label: string;
  icon: string;
}

const NAV_ITEMS: NavItem[] = [
  { id: 'overview',      label: 'Overview',       icon: '◈' },
  { id: 'bounties',      label: 'Bounties',        icon: '⬡' },
  { id: 'contributors',  label: 'Contributors',    icon: '⬡' },
  { id: 'reviews',       label: 'Review Pipeline', icon: '⬡' },
  { id: 'financial',     label: 'Financial',       icon: '⬡' },
  { id: 'health',        label: 'System Health',   icon: '⬡' },
  { id: 'audit-log',     label: 'Audit Log',       icon: '⬡' },
];

interface Props {
  active: AdminSection;
  onNavigate: (s: AdminSection) => void;
  children: ReactNode;
}

// ---------------------------------------------------------------------------
// Auth gate
// ---------------------------------------------------------------------------

function AdminLoginForm({ onSuccess }: { onSuccess: () => void }) {
  const [key, setKey] = useState('');
  const [error, setError] = useState('');

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!key.trim()) { setError('API key is required'); return; }
    setAdminToken(key.trim());
    onSuccess();
  };

  return (
    <div className="min-h-screen bg-[#0f0f1a] flex items-center justify-center p-6">
      <form
        onSubmit={handleSubmit}
        className="w-full max-w-sm rounded-2xl border border-white/10 bg-white/5 p-8 space-y-5"
        data-testid="admin-login-form"
      >
        <div className="text-center">
          <span className="text-3xl font-bold bg-gradient-to-r from-[#9945FF] to-[#14F195] bg-clip-text text-transparent">
            SolFoundry
          </span>
          <p className="mt-1 text-xs text-gray-500 uppercase tracking-widest">Admin Dashboard</p>
        </div>

        <div>
          <label className="block text-xs text-gray-400 mb-1.5" htmlFor="admin-key">
            Admin API Key
          </label>
          <input
            id="admin-key"
            type="password"
            value={key}
            onChange={e => { setKey(e.target.value); setError(''); }}
            placeholder="Enter admin API key…"
            className="w-full rounded-lg border border-white/10 bg-white/5 px-3 py-2 text-sm text-white placeholder-gray-600 focus:outline-none focus:border-[#9945FF]/50"
            autoComplete="current-password"
            data-testid="admin-key-input"
          />
          {error && <p className="mt-1 text-xs text-red-400">{error}</p>}
        </div>

        <button
          type="submit"
          className="w-full rounded-lg bg-gradient-to-r from-[#9945FF] to-[#14F195] py-2 text-sm font-semibold text-white hover:opacity-90 transition-opacity"
          data-testid="admin-login-btn"
        >
          Sign In
        </button>
      </form>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Layout shell
// ---------------------------------------------------------------------------

export function AdminLayout({ active, onNavigate, children }: Props) {
  const [authed, setAuthed] = useState(() => Boolean(getAdminToken()));
  const { status: wsStatus } = useAdminWebSocket();

  if (!authed) {
    return <AdminLoginForm onSuccess={() => setAuthed(true)} />;
  }

  const wsColor =
    wsStatus === 'connected'    ? 'bg-[#14F195]' :
    wsStatus === 'connecting'   ? 'bg-yellow-400' :
    wsStatus === 'error'        ? 'bg-red-500'    : 'bg-gray-600';

  const handleSignOut = () => {
    clearAdminToken();
    setAuthed(false);
  };

  return (
    <div className="flex min-h-screen bg-[#0a0a14] text-white font-mono" data-testid="admin-layout">

      {/* ── Sidebar ────────────────────────────────────────────────── */}
      <aside className="w-56 shrink-0 border-r border-white/5 flex flex-col">
        {/* Logo */}
        <div className="px-5 py-5 border-b border-white/5">
          <span className="text-sm font-bold bg-gradient-to-r from-[#9945FF] to-[#14F195] bg-clip-text text-transparent">
            SolFoundry
          </span>
          <span className="ml-2 text-[10px] text-gray-600 uppercase tracking-widest">Admin</span>
        </div>

        {/* Nav */}
        <nav className="flex-1 py-4 space-y-0.5 px-2" aria-label="Admin navigation">
          {NAV_ITEMS.map(item => (
            <button
              key={item.id}
              onClick={() => onNavigate(item.id)}
              className={
                'w-full text-left flex items-center gap-2.5 rounded-lg px-3 py-2 text-xs transition-colors ' +
                (active === item.id
                  ? 'bg-[#9945FF]/15 text-[#9945FF]'
                  : 'text-gray-500 hover:text-white hover:bg-white/5')
              }
              aria-current={active === item.id ? 'page' : undefined}
              data-testid={`admin-nav-${item.id}`}
            >
              {item.label}
            </button>
          ))}
        </nav>

        {/* Footer */}
        <div className="px-4 py-4 border-t border-white/5 space-y-2">
          {/* WS status */}
          <div className="flex items-center gap-2 text-[10px] text-gray-600">
            <span className={`w-1.5 h-1.5 rounded-full ${wsColor}`} />
            <span>
              {wsStatus === 'connected' ? 'Live' :
               wsStatus === 'connecting' ? 'Connecting…' : 'Offline'}
            </span>
          </div>
          <button
            onClick={handleSignOut}
            className="text-[10px] text-gray-600 hover:text-white transition-colors"
            data-testid="admin-signout"
          >
            Sign out
          </button>
        </div>
      </aside>

      {/* ── Main content ────────────────────────────────────────────── */}
      <main className="flex-1 overflow-auto">
        {children}
      </main>
    </div>
  );
}
