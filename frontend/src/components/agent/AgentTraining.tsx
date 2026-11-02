'use client';

import { useEffect, useMemo, useState, type FormEvent } from 'react';
import { api, errorMessage, seg } from '@/lib/api';
import { orgPath } from '@/lib/agents';
import type {
  AgentBehavior,
  AgentDetail,
  AgentKnowledgeSelection,
  AgentKnowledgeValidation,
  KnowledgeDocument,
} from '@/lib/types';
import { useLoad } from '@/lib/useLoad';
import { Button } from '../Button';
import { EmptyState } from '../EmptyState';
import { FormError, FormSuccess, SelectField, TextAreaField, TextField } from '../Field';
import { Spinner } from '../Spinner';

const DEFAULT_BEHAVIOR: AgentBehavior = {
  role: 'ai_student_customer',
  persona: '',
  objective: '',
  instructions: '',
  languages: ['hi-IN', 'en-IN'],
  default_language: 'hi-IN',
  unknown_answer: "I don't have approved information about that.",
  escalation: 'Offer to connect the learner with an authorized DIDM representative.',
};

export function AgentTraining({
  orgId,
  agent,
  canManage,
  onChanged,
}: {
  orgId: string;
  agent: AgentDetail;
  canManage: boolean;
  onChanged: (notice?: string) => void;
}) {
  const version = agent.draft_version;
  const base = version ? `/agents/${seg(agent.id)}/versions/${seg(version.id)}` : '';
  const documents = useLoad(
    () => api.get<KnowledgeDocument[]>(orgPath(orgId, '/knowledge/documents')),
    `${orgId}|agent-training-documents`,
  );
  const attached = useLoad(
    () => version
      ? api.get<AgentKnowledgeSelection>(orgPath(orgId, `${base}/knowledge-items`))
      : Promise.resolve({ revision_ids: [] }),
    `${orgId}|${version?.id ?? 'none'}|agent-training-items`,
  );
  const [behavior, setBehavior] = useState<AgentBehavior>(() => ({
    ...DEFAULT_BEHAVIOR,
    ...(version?.behavior_snapshot ?? {}),
  }));
  const [selected, setSelected] = useState<string[]>([]);
  const [busy, setBusy] = useState<'save' | 'validate' | 'snapshot' | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [validation, setValidation] = useState<AgentKnowledgeValidation | null>(null);

  useEffect(() => setSelected(attached.data?.revision_ids ?? []), [attached.data]);
  const readyDocuments = useMemo(() => (documents.data ?? []).filter((x) => x.revision?.processing_state === 'ready'), [documents.data]);

  if (!version) {
    return <EmptyState title="Start a draft version before training this agent.">
      <p>Training changes are versioned so active calls keep using the published version until the new one is ready.</p>
    </EmptyState>;
  }
  if ((documents.loading && !documents.data) || (attached.loading && !attached.data)) return <Spinner label="Loading agent training" />;

  const set = (patch: Partial<AgentBehavior>) => {
    setBehavior((old) => ({ ...old, ...patch }));
    setValidation(null);
  };
  const toggle = (id: string) => {
    setSelected((old) => old.includes(id) ? old.filter((x) => x !== id) : [...old, id]);
    setValidation(null);
  };

  async function persistTraining() {
    await api.put(orgPath(orgId, `${base}/behavior`), behavior);
    await api.put(orgPath(orgId, `${base}/knowledge-items`), { revision_ids: selected });
  }

  async function save(e: FormEvent) {
    e.preventDefault();
    setError(null); setNotice(null); setBusy('save');
    try {
      await persistTraining();
      setNotice('Agent instructions and approved knowledge saved to this draft.');
      setValidation(null);
      onChanged();
    } catch (err) { setError(errorMessage(err)); } finally { setBusy(null); }
  }

  async function validate() {
    setError(null); setNotice(null); setBusy('validate');
    try {
      await persistTraining();
      const result = await api.post<AgentKnowledgeValidation>(orgPath(orgId, `${base}/knowledge-validate`));
      setValidation(result);
      if (result.status === 'passed') setNotice('Training content passed offline validation.');
    } catch (err) { setError(errorMessage(err)); } finally { setBusy(null); }
  }

  async function snapshot() {
    setError(null); setNotice(null); setBusy('snapshot');
    try {
      await api.post(orgPath(orgId, `${base}/knowledge-snapshot`));
      setNotice('Immutable training snapshot prepared. Live Sarvam sync is still required before calls change.');
      onChanged();
    } catch (err) { setError(errorMessage(err)); } finally { setBusy(null); }
  }

  return <section className="panel" aria-labelledby="agent-training-title">
    <h2 id="agent-training-title">Train draft version {version.internal_version}</h2>
    <div className="alert alert-warn">
      Practice calls train the human trainee, not the AI. This section defines the AI&apos;s behavior and approved knowledge. Live calls continue using Sarvam app version {version.provider_app_version ?? '—'} until this content is synchronized there and that app version is published.
    </div>
    <form className="form form-wide" onSubmit={save}>
      <FormError message={error || (documents.error ? errorMessage(documents.error) : null) || (attached.error ? errorMessage(attached.error) : null)} />
      <FormSuccess message={notice} />
      <SelectField label="Agent role" value={behavior.role} disabled={!canManage} onChange={(e) => set({ role: e.target.value as AgentBehavior['role'] })} options={[
        { value: 'ai_student_customer', label: 'AI student / customer (trainee practises counselling)' },
        { value: 'ai_admissions_counsellor', label: 'AI admissions counsellor' },
      ]} />
      <TextAreaField label="Persona" rows={4} maxLength={10000} disabled={!canManage} value={behavior.persona} onChange={(e) => set({ persona: e.target.value })} hint="Who the AI is, its name, background, mood and speaking style." />
      <TextAreaField label="Training objective" rows={3} maxLength={10000} disabled={!canManage} value={behavior.objective} onChange={(e) => set({ objective: e.target.value })} hint="What a successful conversation should accomplish." />
      <TextAreaField label="Conversation instructions" rows={10} maxLength={30000} disabled={!canManage} value={behavior.instructions} onChange={(e) => set({ instructions: e.target.value })} hint="Opening, questions to ask, boundaries and how to use {{agent_name}} and {{user_name}}." />
      <div className="form-grid">
        <TextField label="Languages" disabled={!canManage} value={behavior.languages.join(', ')} onChange={(e) => set({ languages: e.target.value.split(',').map((x) => x.trim()).filter(Boolean) })} hint="Comma-separated locale codes." />
        <TextField label="Default language" disabled={!canManage} value={behavior.default_language} onChange={(e) => set({ default_language: e.target.value.trim() })} />
      </div>
      <TextAreaField label="When the answer is unknown" rows={2} maxLength={1000} disabled={!canManage} value={behavior.unknown_answer} onChange={(e) => set({ unknown_answer: e.target.value })} />
      <TextAreaField label="Escalation rule" rows={2} maxLength={2000} disabled={!canManage} value={behavior.escalation} onChange={(e) => set({ escalation: e.target.value })} />
      <fieldset className="fieldset">
        <legend>Approved knowledge</legend>
        <p className="field-hint">Add FAQs and manual notes in the Knowledge library, then attach the exact approved revisions here.</p>
        {readyDocuments.length === 0 ? <EmptyState title="No ready knowledge items." /> : <ul className="card-list">
          {readyDocuments.map((doc) => <li key={doc.id} className="card"><label>
            <input type="checkbox" disabled={!canManage} checked={selected.includes(doc.revision!.id)} onChange={() => toggle(doc.revision!.id)} />{' '}
            <strong>{doc.title}</strong> <span className="badge">{doc.kind}</span> <span className="small muted">revision {doc.revision!.revision_no}</span>
          </label></li>)}
        </ul>}
      </fieldset>
      {canManage && <div className="form-actions">
        <Button type="submit" busy={busy === 'save'} disabled={busy !== null}>Save training draft</Button>
        <Button variant="secondary" busy={busy === 'validate'} disabled={busy !== null} onClick={() => void validate()}>Validate training</Button>
        <Button variant="secondary" busy={busy === 'snapshot'} disabled={busy !== null || validation?.status !== 'passed'} onClick={() => void snapshot()}>Prepare snapshot</Button>
      </div>}
      {validation?.status === 'failed' && <div className="alert alert-warn"><strong>Training is not ready:</strong><ul className="problem-list">{validation.findings.map((x) => <li key={x.code}>{x.message}</li>)}</ul></div>}
    </form>
  </section>;
}
