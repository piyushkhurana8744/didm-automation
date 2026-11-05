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
  const [sarvamNameVariable, setSarvamNameVariable] = useState('');
  const [originalSarvamNameVariable, setOriginalSarvamNameVariable] = useState('');
  const [sarvamContextVariable, setSarvamContextVariable] = useState('');
  const [originalSarvamContextVariable, setOriginalSarvamContextVariable] = useState('');
  const [busy, setBusy] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const [saved, setSaved] = useState<string | null>(null);

  useEffect(() => {
    if (org) setName(org.name);
  }, [org]);

  useEffect(() => {
    api.get<{ name: string }>(`/organizations/${seg(orgId)}/training/sarvam-name-variable`).then((value) => {
      setSarvamNameVariable(value.name);
      setOriginalSarvamNameVariable(value.name);
    }).catch(() => undefined);
  }, [orgId]);

  useEffect(() => {
    api.get<{ name: string }>(`/organizations/${seg(orgId)}/training/sarvam-context-variable`).then((value) => {
      setSarvamContextVariable(value.name);
      setOriginalSarvamContextVariable(value.name);
    }).catch(() => undefined);
  }, [orgId]);

  async function onSave(e: FormEvent) {
    e.preventDefault();
    setFormError(null);
    setSaved(null);
    if (!name.trim()) return setFormError('Enter a name.');
    const variable = sarvamNameVariable.trim();
    if (variable && !/^[a-z_][a-z0-9_]{0,63}$/.test(variable)) {
      return setFormError('Sarvam name variable must use lower-case letters, digits and underscores.');
    }
    const contextVariable = sarvamContextVariable.trim();
    if (contextVariable && !/^[a-z_][a-z0-9_]{0,63}$/.test(contextVariable)) {
      return setFormError('Sarvam context variable must use lower-case letters, digits and underscores.');
    }
    setBusy(true);
    try {
      const updated = await api.patch<Organization>(`/organizations/${seg(orgId)}`, { name: name.trim() });
      await api.put(`/organizations/${seg(orgId)}/training/sarvam-name-variable`, { name: variable });
      await api.put(`/organizations/${seg(orgId)}/training/sarvam-context-variable`, { name: contextVariable });
      setData((prev) => ({ ...(prev as OrganizationDetail), ...updated }));
      setSarvamNameVariable(variable);
      setOriginalSarvamNameVariable(variable);
      setSarvamContextVariable(contextVariable);
      setOriginalSarvamContextVariable(contextVariable);
      setSaved('Organization settings saved.');
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
            <TextField
              label="Sarvam name variable"
              maxLength={64}
              className="input mono"
              value={sarvamNameVariable}
              onChange={(e) => setSarvamNameVariable(e.target.value)}
              placeholder="lead_name"
              hint="Enter the exact Sarvam agent variable that should receive the signed-in person's display name, for example lead_name, student_name or user_name."
            />
            <TextField
              label="Sarvam training context variable"
              maxLength={64}
              className="input mono"
              value={sarvamContextVariable}
              onChange={(e) => setSarvamContextVariable(e.target.value)}
              placeholder="trainee_training_context"
              hint="Enter the exact variable referenced in the Sarvam agent prompt. Personal instructions, text, extracted PDF text and imported transcripts are sent here when each call starts."
            />
            <div>
              <Button type="submit" busy={busy} disabled={name.trim() === org.name && sarvamNameVariable.trim() === originalSarvamNameVariable && sarvamContextVariable.trim() === originalSarvamContextVariable}>
                Save settings
              </Button>
            </div>
          </form>
        ) : (
          <>
            <ReadOnlyField label="Name" value={org.name} />
            <ReadOnlyField label="Sarvam name variable" value={sarvamNameVariable || 'Not configured'} />
            <ReadOnlyField label="Sarvam training context variable" value={sarvamContextVariable || 'Not configured'} />
          </>
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
