'use client';

import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { useEffect, useState, type FormEvent } from 'react';
import { api, errorMessage } from '@/lib/api';
import { APP_ID_RE, CHANNEL_LABELS, CHANNELS, orgPath, parseOptionalInt } from '@/lib/agents';
import type { Agent, Channel, Membership } from '@/lib/types';
import { Button } from '@/components/Button';
import { CheckboxField, FormError, TextAreaField, TextField } from '@/components/Field';
import { OrgGate } from '@/components/OrgGate';
import { PageHeader } from '@/components/PageHeader';

type Errors = Partial<Record<'name' | 'provider_app_id' | 'channels' | 'provider_app_version', string>>;
type SarvamStatus = { configured: boolean; connected: boolean; expires_at?: number | null; detail?: string };
type SarvamAgent = { name: string; description: string; provider_app_version: number | null; variable_schema: Record<string, unknown>[] };

function RegisterAgent({ membership }: { membership: Membership }) {
  const orgId = membership.organization.id;
  const router = useRouter();
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [category, setCategory] = useState('');
  const [appId, setAppId] = useState('');
  const [appVersion, setAppVersion] = useState('');
  const [channels, setChannels] = useState<Channel[]>(['phone']);
  const [errors, setErrors] = useState<Errors>({});
  const [formError, setFormError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [sarvam, setSarvam] = useState<SarvamStatus | null>(null);
  const [connecting, setConnecting] = useState(false);
  const [fetching, setFetching] = useState(false);
  const [fetchedSchema, setFetchedSchema] = useState<Record<string, unknown>[]>([]);
  const [fetchNotice, setFetchNotice] = useState<string | null>(null);

  useEffect(() => {
    api.get<SarvamStatus>(orgPath(orgId, '/integrations/sarvam/status')).then(setSarvam).catch(() => setSarvam(null));
    const result = new URLSearchParams(window.location.search).get('sarvam');
    if (result === 'connected') setFetchNotice('Sarvam connected. Paste the agent ID and fetch its details.');
    if (result === 'error') setFormError('Sarvam login was not completed. Please try connecting again.');
  }, [orgId]);

  async function connectSarvam() {
    setConnecting(true);
    setFormError(null);
    try {
      const out = await api.post<{ authorization_url: string }>(orgPath(orgId, '/integrations/sarvam/connect'));
      window.location.assign(out.authorization_url);
    } catch (err) {
      setFormError(errorMessage(err));
      setConnecting(false);
    }
  }

  async function fetchFromSarvam() {
    if (!appId.trim() || !APP_ID_RE.test(appId.trim())) {
      setErrors((prev) => ({ ...prev, provider_app_id: "Enter a valid Sarvam agent ID first." }));
      return;
    }
    setFetching(true);
    setFormError(null);
    setFetchNotice(null);
    try {
      const found = await api.get<SarvamAgent>(orgPath(orgId, `/integrations/sarvam/agents/${encodeURIComponent(appId.trim())}`));
      setName(found.name);
      if (found.description) setDescription(found.description);
      if (found.provider_app_version) setAppVersion(String(found.provider_app_version));
      setFetchedSchema(found.variable_schema ?? []);
      setErrors((prev) => ({ ...prev, name: undefined, provider_app_id: undefined }));
      setFetchNotice(`Fetched “${found.name}” and ${found.variable_schema?.length ?? 0} agent variable(s) from Sarvam.`);
    } catch (err) {
      setFormError(errorMessage(err));
    } finally {
      setFetching(false);
    }
  }

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setFormError(null);
    const next: Errors = {};
    if (!name.trim()) next.name = 'Enter a name.';
    if (!appId.trim()) next.provider_app_id = "Paste the agent's app id from Sarvam.";
    else if (!APP_ID_RE.test(appId.trim())) next.provider_app_id = 'Use letters, digits, dot, dash, colon or underscore (starting with a letter or digit).';
    if (channels.length === 0) next.channels = 'Choose at least one channel.';
    const version = parseOptionalInt(appVersion);
    if (version !== undefined && (Number.isNaN(version) || version < 1)) next.provider_app_version = 'Enter a whole number, 1 or more, or leave it empty.';
    setErrors(next);
    if (Object.keys(next).length) return;
    setBusy(true);
    try {
      const agent = await api.post<Agent>(orgPath(orgId, '/agents'), {
        name: name.trim(),
        description: description.trim(),
        category: category.trim(),
        provider_app_id: appId.trim(),
        channels,
        variable_schema: fetchedSchema,
        ...(version !== undefined ? { provider_app_version: version } : {}),
      });
      router.push(`/agents/detail/?id=${encodeURIComponent(agent.id)}&tab=configuration`);
    } catch (err) {
      setFormError(errorMessage(err));
      setBusy(false);
    }
  }

  return (
    <>
      <p className="small">
        <Link href="/agents/">← Agents</Link>
      </p>
      <PageHeader title="Register agent" description="Link a voice agent that already exists in Sarvam to this organization." />
      <div className="alert alert-info" role="note">
        <strong>Registering does not create or change the agent at Sarvam.</strong> Connect Sarvam for read-only auto-fetch, then paste the agent ID.
        <div className="form-actions">
          <Button type="button" variant="secondary" size="sm" busy={connecting} onClick={connectSarvam} disabled={sarvam?.configured === false}>
            {sarvam?.connected ? 'Reconnect Sarvam' : 'Connect Sarvam'}
          </Button>
          {sarvam?.connected && <span className="small">Connected</span>}
          {sarvam?.configured === false && <span className="small">Server setup required: SARVAM_MCP_ENCRYPTION_KEY</span>}
        </div>
      </div>
      <section className="panel">
        <form onSubmit={onSubmit} noValidate className="form form-wide">
          <FormError message={formError} />
          {fetchNotice && <p className="alert alert-success" role="status">{fetchNotice}</p>}
          <TextField label="Name" required maxLength={200} value={name} error={errors.name} onChange={(e) => setName(e.target.value)} />
          <TextAreaField label="Description" maxLength={5000} value={description} onChange={(e) => setDescription(e.target.value)} hint="What the agent does and who it is for." />
          <div className="form-grid">
            <TextField label="Category" maxLength={80} value={category} onChange={(e) => setCategory(e.target.value)} hint="For example: Sales, Support, Collections." />
            <TextField
              label="Sarvam agent ID"
              required
              maxLength={200}
              className="input mono"
              autoComplete="off"
              spellCheck={false}
              value={appId}
              error={errors.provider_app_id}
              onChange={(e) => setAppId(e.target.value)}
              hint="Use Copy agent ID from the agent menu in Sarvam. It cannot be changed after a version is published."
            />
            <div className="field">
              <span className="field-hint">Fetches the real name, latest committed version and declared variables.</span>
              <Button type="button" variant="secondary" size="sm" busy={fetching} disabled={!sarvam?.connected} onClick={fetchFromSarvam}>
                Fetch from Sarvam
              </Button>
            </div>
            <TextField
              label="Sarvam app version (optional)"
              type="number"
              inputMode="numeric"
              min={1}
              step={1}
              value={appVersion}
              error={errors.provider_app_version}
              onChange={(e) => setAppVersion(e.target.value)}
              hint="The app version the first draft should use. You can set it later."
            />
          </div>
          <fieldset className={errors.channels ? 'fieldset field-invalid' : 'fieldset'}>
            <legend>Training channels</legend>
            {CHANNELS.map((c) => (
              <CheckboxField
                key={c}
                label={CHANNEL_LABELS[c]}
                checked={channels.includes(c)}
                onChange={(e) => setChannels((prev) => (e.target.checked ? CHANNELS.filter((x) => x === c || prev.includes(x)) : prev.filter((x) => x !== c)))}
              />
            ))}
            <p className="field-hint">How trainees will practise with this agent. Practice sessions arrive in a later release.</p>
            {errors.channels && <p className="field-error">{errors.channels}</p>}
          </fieldset>
          <div className="form-actions">
            <Button type="submit" busy={busy}>
              Register agent
            </Button>
            <Link href="/agents/" className="btn btn-ghost">
              Cancel
            </Link>
          </div>
        </form>
      </section>
    </>
  );
}

export default function RegisterAgentPage() {
  return <OrgGate permission="agents.manage">{(m) => <RegisterAgent membership={m} />}</OrgGate>;
}
