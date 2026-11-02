'use client';

import Link from 'next/link';
import { useEffect, useState, type FormEvent } from 'react';
import { api, errorMessage, seg } from '@/lib/api';
import { capitalize, formatDate } from '@/lib/format';
import { useSession } from '@/lib/session';
import type { Membership, Organization, OrganizationDetail } from '@/lib/types';
import { useLoad } from '@/lib/useLoad';
import { Button } from '@/components/Button';
import { ErrorState } from '@/components/ErrorState';
import { FormError, FormSuccess, ReadOnlyField, TextField } from '@/components/Field';
import { OrgGate } from '@/components/OrgGate';
import { PageHeader } from '@/components/PageHeader';
import { Spinner } from '@/components/Spinner';

function Settings({ membership }: { membership: Membership }) {
  const { refresh } = useSession();
  const orgId = membership.organization.id;
  const canEdit = membership.permissions.includes('org.update');
  const { data: org, error, loading, reload, setData } = useLoad(() => api.get<OrganizationDetail>(`/organizations/${seg(orgId)}`), orgId);
  const [name, setName] = useState('');
  const [busy, setBusy] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const [saved, setSaved] = useState<string | null>(null);

  useEffect(() => {
    if (org) setName(org.name);
  }, [org]);

  async function onSave(e: FormEvent) {
    e.preventDefault();
    setFormError(null);
    setSaved(null);
    if (!name.trim()) return setFormError('Enter a name.');
    setBusy(true);
    try {
      const updated = await api.patch<Organization>(`/organizations/${seg(orgId)}`, { name: name.trim() });
      setData((prev) => ({ ...(prev as OrganizationDetail), ...updated }));
      setSaved('Organization name saved.');
      await refresh();
    } catch (err) {
      setFormError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  if (loading && !org) return <Spinner label="Loading settings" />;
  if (error) return <ErrorState error={error} onRetry={reload} />;
  if (!org) return null;

  return (
    <>
      <PageHeader
        title="Settings"
        description={`Details of ${org.name}.`}
        actions={
          membership.permissions.includes('audit.view') ? (
            <Link href="/settings/audit/" className="btn btn-secondary">
              Audit log
            </Link>
          ) : undefined
        }
      />
      <section className="panel" aria-labelledby="org-details">
        <h2 id="org-details" className="panel-title">
          Organization
        </h2>
        {canEdit ? (
          <form onSubmit={onSave} noValidate className="form">
            <FormError message={formError} />
            <FormSuccess message={saved} />
            <TextField label="Name" required maxLength={200} value={name} onChange={(e) => setName(e.target.value)} />
            <div>
              <Button type="submit" busy={busy} disabled={name.trim() === org.name}>
                Save name
              </Button>
            </div>
          </form>
        ) : (
          <ReadOnlyField label="Name" value={org.name} />
        )}
        <div className="readonly-grid">
          <ReadOnlyField label="Slug" value={<span className="mono">{org.slug}</span>} />
          <ReadOnlyField label="Status" value={capitalize(org.status)} />
          <ReadOnlyField label="Created" value={formatDate(org.created_at)} />
        </div>
        <p className="field-hint">The slug and status can only be changed by a platform administrator.</p>
      </section>
    </>
  );
}

export default function SettingsPage() {
  return <OrgGate permission="org.view">{(m) => <Settings membership={m} />}</OrgGate>;
}
