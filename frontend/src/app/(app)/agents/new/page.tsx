'use client';

import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { useState, type FormEvent } from 'react';
import { api, errorMessage } from '@/lib/api';
import { APP_ID_RE, CHANNEL_LABELS, CHANNELS, orgPath, parseOptionalInt } from '@/lib/agents';
import type { Agent, Channel, Membership } from '@/lib/types';
import { Button } from '@/components/Button';
import { CheckboxField, FormError, TextAreaField, TextField } from '@/components/Field';
import { OrgGate } from '@/components/OrgGate';
import { PageHeader } from '@/components/PageHeader';

type Errors = Partial<Record<'name' | 'provider_app_id' | 'channels' | 'provider_app_version', string>>;

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
        <strong>Registering does not create the agent at Sarvam.</strong> Build and test the agent in Sarvam&apos;s dashboard first, then
        paste its app id here. Nothing on this page contacts Sarvam.
      </div>
      <section className="panel">
        <form onSubmit={onSubmit} noValidate className="form form-wide">
          <FormError message={formError} />
          <TextField label="Name" required maxLength={200} value={name} error={errors.name} onChange={(e) => setName(e.target.value)} />
          <TextAreaField label="Description" maxLength={5000} value={description} onChange={(e) => setDescription(e.target.value)} hint="What the agent does and who it is for." />
          <div className="form-grid">
            <TextField label="Category" maxLength={80} value={category} onChange={(e) => setCategory(e.target.value)} hint="For example: Sales, Support, Collections." />
            <TextField
              label="Sarvam app id"
              required
              maxLength={200}
              className="input mono"
              autoComplete="off"
              spellCheck={false}
              value={appId}
              error={errors.provider_app_id}
              onChange={(e) => setAppId(e.target.value)}
              hint="Copy it from the agent's page in Sarvam. It cannot be changed after a version is published."
            />
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
