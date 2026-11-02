'use client';

import { useState, type FormEvent } from 'react';
import { api, errorMessage, seg } from '@/lib/api';
import { APP_ID_RE, CHANNEL_LABELS, CHANNELS, channelList, orgPath } from '@/lib/agents';
import { capitalize, formatDateTime } from '@/lib/format';
import type { Agent, AgentDetail, Channel } from '@/lib/types';
import { Button } from '../Button';
import { CheckboxField, FormError, FormSuccess, TextAreaField, TextField } from '../Field';

type Errors = Partial<Record<'name' | 'provider_app_id' | 'channels', string>>;

function EditAgentForm({ orgId, agent, onSaved }: { orgId: string; agent: AgentDetail; onSaved: (a: Agent) => void }) {
  const [name, setName] = useState(agent.name);
  const [description, setDescription] = useState(agent.description);
  const [category, setCategory] = useState(agent.category);
  const [appId, setAppId] = useState(agent.provider_app_id);
  const [channels, setChannels] = useState<Channel[]>(agent.channels);
  const [errors, setErrors] = useState<Errors>({});
  const [formError, setFormError] = useState<string | null>(null);
  const [saved, setSaved] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const dirty =
    name !== agent.name ||
    description !== agent.description ||
    category !== agent.category ||
    appId !== agent.provider_app_id ||
    channels.join(',') !== agent.channels.join(',');

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setFormError(null);
    setSaved(null);
    const next: Errors = {};
    if (!name.trim()) next.name = 'Enter a name.';
    if (!agent.provider_app_id_locked) {
      if (!appId.trim()) next.provider_app_id = 'Enter the Sarvam app id.';
      else if (!APP_ID_RE.test(appId.trim())) next.provider_app_id = 'Use letters, digits, dot, dash, colon or underscore.';
    }
    if (channels.length === 0) next.channels = 'Choose at least one channel.';
    setErrors(next);
    if (Object.keys(next).length) return;
    const body: Record<string, unknown> = { name: name.trim(), description: description.trim(), category: category.trim(), channels };
    if (!agent.provider_app_id_locked && appId.trim() !== agent.provider_app_id) body.provider_app_id = appId.trim();
    setBusy(true);
    try {
      const updated = await api.patch<Agent>(orgPath(orgId, `/agents/${seg(agent.id)}`), body);
      onSaved(updated);
      setSaved('Agent details saved.');
    } catch (err) {
      setFormError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={onSubmit} noValidate className="form form-wide">
      <FormError message={formError} />
      <FormSuccess message={saved} />
      <TextField label="Name" required maxLength={200} value={name} error={errors.name} onChange={(e) => setName(e.target.value)} />
      <TextAreaField label="Description" maxLength={5000} value={description} onChange={(e) => setDescription(e.target.value)} />
      <div className="form-grid">
        <TextField label="Category" maxLength={80} value={category} onChange={(e) => setCategory(e.target.value)} />
        <TextField
          label="Sarvam app id"
          className="input mono"
          maxLength={200}
          spellCheck={false}
          autoComplete="off"
          value={appId}
          disabled={agent.provider_app_id_locked}
          error={errors.provider_app_id}
          onChange={(e) => setAppId(e.target.value)}
          hint={
            agent.provider_app_id_locked
              ? 'Fixed: a version using this app was published. Register a new agent for a different Sarvam app.'
              : 'Can be changed until the first version is published.'
          }
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
        {errors.channels && <p className="field-error">{errors.channels}</p>}
      </fieldset>
      <div>
        <Button type="submit" busy={busy} disabled={!dirty}>
          Save details
        </Button>
      </div>
    </form>
  );
}

export function AgentOverview({
  orgId,
  agent,
  canManage,
  onSaved,
}: {
  orgId: string;
  agent: AgentDetail;
  canManage: boolean;
  onSaved: (a: Agent) => void;
}) {
  const pub = agent.published_version;
  return (
    <>
      <section className="panel" aria-labelledby="overview-facts">
        <h2 id="overview-facts" className="panel-title">
          Overview
        </h2>
        <dl className="facts facts-wide">
          <div>
            <dt>Status</dt>
            <dd>{capitalize(agent.status)}</dd>
          </div>
          <div>
            <dt>Provider</dt>
            <dd>{agent.provider === 'sarvam' ? 'Sarvam' : agent.provider}</dd>
          </div>
          <div>
            <dt>Sarvam app id</dt>
            <dd className="mono break">{agent.provider_app_id}</dd>
          </div>
          <div>
            <dt>Channels</dt>
            <dd>{channelList(agent.channels)}</dd>
          </div>
          <div>
            <dt>Current version</dt>
            <dd>
              {pub
                ? `Version ${pub.internal_version} (Sarvam app version ${pub.provider_app_version ?? '—'}), published ${formatDateTime(pub.published_at)}`
                : 'Nothing published yet'}
            </dd>
          </div>
          <div>
            <dt>Draft</dt>
            <dd>{agent.draft_version ? `Version ${agent.draft_version.internal_version} is being edited` : 'None'}</dd>
          </div>
          <div>
            <dt>Scenarios</dt>
            <dd>{agent.counts.scenarios}</dd>
          </div>
          <div>
            <dt>Open assignments</dt>
            <dd>{agent.counts.open_assignments}</dd>
          </div>
          <div>
            <dt>Registered</dt>
            <dd>{formatDateTime(agent.created_at)}</dd>
          </div>
          {agent.archived_at && (
            <div>
              <dt>Archived</dt>
              <dd>{formatDateTime(agent.archived_at)}</dd>
            </div>
          )}
        </dl>
        {agent.description && <p className="break" style={{ whiteSpace: 'pre-wrap' }}>{agent.description}</p>}
      </section>
      {canManage && (
        <section className="panel" aria-labelledby="overview-edit">
          <h2 id="overview-edit" className="panel-title">
            Edit details
          </h2>
          {agent.status === 'active' ? (
            <EditAgentForm key={agent.id} orgId={orgId} agent={agent} onSaved={onSaved} />
          ) : (
            <p className="muted">Restore the agent to change its details.</p>
          )}
        </section>
      )}
    </>
  );
}
