/**
 * AdminPage — Route entry point for /admin.
 * Renders the AdminLayout shell with panel switching via URL search params.
 */
import { useSearchParams } from 'react-router-dom';
import { AdminLayout } from '../components/admin/AdminLayout';
import { OverviewPanel } from '../components/admin/OverviewPanel';
import { BountyManagement } from '../components/admin/BountyManagement';
import { ContributorManagement } from '../components/admin/ContributorManagement';
import { ReviewPipeline } from '../components/admin/ReviewPipeline';
import { FinancialPanel } from '../components/admin/FinancialPanel';
import { SystemHealth } from '../components/admin/SystemHealth';
import { AuditLogPanel } from '../components/admin/AuditLogPanel';
import type { AdminSection } from '../types/admin';

const DEFAULT_SECTION: AdminSection = 'overview';

export default function AdminPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const section = (searchParams.get('section') ?? DEFAULT_SECTION) as AdminSection;

  const navigate = (s: AdminSection) => {
    setSearchParams({ section: s }, { replace: true });
  };

  const panel = () => {
    switch (section) {
      case 'bounties':     return <BountyManagement />;
      case 'contributors': return <ContributorManagement />;
      case 'reviews':      return <ReviewPipeline />;
      case 'financial':    return <FinancialPanel />;
      case 'health':       return <SystemHealth />;
      case 'audit-log':    return <AuditLogPanel />;
      default:             return <OverviewPanel />;
    }
  };

  return (
    <AdminLayout active={section} onNavigate={navigate}>
      {panel()}
    </AdminLayout>
  );
}
