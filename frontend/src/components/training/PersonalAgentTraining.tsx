'use client';

import { useState, type ChangeEvent, type DragEvent, type FormEvent } from 'react';
import { api, errorMessage, seg } from '@/lib/api';
import { orgPath } from '@/lib/agents';
import type { MyAgentTrainingProfile, Page, TrainingSession, VarDef } from '@/lib/types';
import { useLoad } from '@/lib/useLoad';
import { Button } from '../Button';
import { EmptyState } from '../EmptyState';
import { FormError, FormSuccess, SelectField, TextAreaField, TextField } from '../Field';
import { Spinner } from '../Spinner';

function bytesToBase64(buffer: ArrayBuffer): string {
  const bytes = new Uint8Array(buffer);
  let binary = '';
  for (let i = 0; i < bytes.length; i += 0x8000) binary += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
  return btoa(binary);
}

const RESERVED = new Set(['agent_name', 'user_name', 'trainee_name', 'trainee_training_context', 'user_training_context']);

export function PersonalAgentTraining({ orgId, agentId, variableSchema }: { orgId: string; agentId: string; variableSchema: VarDef[] }) {
  const base = `/my/agents/${seg(agentId)}/training-profile`;
  const profile = useLoad(() => api.get<MyAgentTrainingProfile>(orgPath(orgId, base)), `${orgId}|${agentId}|personal-training`);
  const sessions = useLoad(
    () => api.get<Page<TrainingSession>>(orgPath(orgId, '/my/training/sessions?limit=100')),
    `${orgId}|${agentId}|personal-training-sessions`,
  );
  const [instructions, setInstructions] = useState<string | null>(null);
  const [variableValues, setVariableValues] = useState<Record<string, string> | null>(null);
  const [title, setTitle] = useState('');
  const [text, setText] = useState('');
  const [sessionId, setSessionId] = useState('');
  const [dragging, setDragging] = useState(false);
  const [busy, setBusy] = useState<'save' | 'text' | 'pdf' | 'transcript' | 'delete' | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  if (profile.loading && !profile.data) return <Spinner label="Loading your agent training" />;
  if (profile.error && !profile.data) return <FormError message={errorMessage(profile.error)} />;
  const data = profile.data;
  if (!data) return null;
  const value = instructions ?? data.instructions;
  const editableVariables = variableSchema.filter((x) => !RESERVED.has(x.name));
  const values = variableValues ?? Object.fromEntries(editableVariables.map((x) => [x.name, String(data.variable_values[x.name] ?? '')]));
  const ownSessions = (sessions.data?.items ?? []).filter((x) => x.agent_id === agentId && x.status === 'completed');
  const resetMessages = () => { setError(null); setNotice(null); };

  async function saveInstructions(e: FormEvent) {
    e.preventDefault(); resetMessages(); setBusy('save');
    try {
      const typedValues: Record<string, unknown> = {};
      editableVariables.forEach((item) => {
        const raw = values[item.name];
        if (raw === '') return;
        if (item.type === 'integer') typedValues[item.name] = Number.parseInt(raw, 10);
        else if (item.type === 'number') typedValues[item.name] = Number(raw);
        else if (item.type === 'boolean') typedValues[item.name] = raw === 'true';
        else typedValues[item.name] = raw;
      });
      await api.put(orgPath(orgId, base), { instructions: value, variable_values: typedValues });
      setInstructions(null); setVariableValues(null); setNotice('Your personal agent instructions and variables were saved.'); profile.reload();
    } catch (err) { setError(errorMessage(err)); } finally { setBusy(null); }
  }

  async function addText(e: FormEvent) {
    e.preventDefault(); resetMessages(); setBusy('text');
    try {
      await api.post(orgPath(orgId, `${base}/text`), { title, text });
      setTitle(''); setText(''); setNotice('Training text added.'); profile.reload();
    } catch (err) { setError(errorMessage(err)); } finally { setBusy(null); }
  }

  async function addFile(file: File) {
    resetMessages();
    const extension = file.name.split('.').pop()?.toLowerCase();
    const isPdf = file.type === 'application/pdf' || extension === 'pdf';
    const isText = file.type.startsWith('text/') || extension === 'txt' || extension === 'md';
    if (!isPdf && !isText) return setError('Use a PDF, TXT or Markdown file. Images need OCR and are not supported yet.');
    if (file.size > 5_000_000) return setError('Choose a file no larger than 5 MB.');
    setBusy(isPdf ? 'pdf' : 'text');
    try {
      if (isPdf) {
        await api.post(orgPath(orgId, `${base}/pdf`), { filename: file.name, content_base64: bytesToBase64(await file.arrayBuffer()) });
        setNotice('PDF ready. Its extracted text will be sent to Sarvam on your next call.');
      } else {
        const content = (await file.text()).trim();
        if (!content) { setError('This text file is empty.'); return; }
        if (content.length > 30000) { setError('Text files can contain at most 30,000 characters.'); return; }
        await api.post(orgPath(orgId, `${base}/text`), { title: file.name, text: content });
        setNotice('Text file ready. It will be sent to Sarvam on your next call.');
      }
      profile.reload();
    } catch (err) { setError(errorMessage(err)); } finally { setBusy(null); }
  }

  async function uploadFile(e: ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0]; e.target.value = '';
    if (file) await addFile(file);
  }

  async function dropFile(e: DragEvent<HTMLLabelElement>) {
    e.preventDefault(); setDragging(false);
    const file = e.dataTransfer.files?.[0];
    if (file) await addFile(file);
  }

  async function importTranscript() {
    if (!sessionId) return;
    resetMessages(); setBusy('transcript');
    try {
      await api.post(orgPath(orgId, `${base}/transcript`), { session_id: sessionId });
      setSessionId(''); setNotice('Your call transcript was added.'); profile.reload();
    } catch (err) { setError(errorMessage(err)); } finally { setBusy(null); }
  }

  async function remove(sourceId: string) {
    resetMessages(); setBusy('delete');
    try {
      await api.delete(orgPath(orgId, `${base}/sources/${seg(sourceId)}`));
      setNotice('Training source removed.'); profile.reload();
    } catch (err) { setError(errorMessage(err)); } finally { setBusy(null); }
  }

  return <section className="panel" aria-labelledby="personal-agent-training">
    <h2 id="personal-agent-training" className="panel-title">Train your assigned agent</h2>
    <p className="muted">These instructions and sources apply only to your calls with this assigned agent. They do not change anyone else&apos;s agent.</p>
    <p className="field-hint">At call start, DIDM sends these instructions and extracted sources through the Sarvam training-context variable configured by your organization owner. The Sarvam agent prompt must reference that variable.</p>
    <FormError message={error} /><FormSuccess message={notice} />
    <form className="form form-wide" onSubmit={saveInstructions}>
      <TextAreaField label="Personal agent instructions" rows={6} maxLength={10000} value={value} onChange={(e) => setInstructions(e.target.value)} hint="Tell the agent how to behave with you, what to practise and which language or difficulty to use." />
      {editableVariables.length > 0 && <fieldset className="fieldset">
        <legend>My call variables</legend>
        <p className="field-hint">These values override scenario defaults only for your calls. Empty uses the scenario or agent default.</p>
        <div className="form-grid">
          {editableVariables.map((item) => item.type === 'enum' ? <SelectField
            key={item.name} label={item.name} value={values[item.name] ?? ''}
            options={[{ value: '', label: 'Use default' }, ...(item.options ?? []).map((x) => ({ value: x, label: x }))]}
            onChange={(e) => setVariableValues({ ...values, [item.name]: e.target.value })}
          /> : item.type === 'boolean' ? <SelectField
            key={item.name} label={item.name} value={values[item.name] ?? ''}
            options={[{ value: '', label: 'Use default' }, { value: 'true', label: 'Yes' }, { value: 'false', label: 'No' }]}
            onChange={(e) => setVariableValues({ ...values, [item.name]: e.target.value })}
          /> : <TextField
            key={item.name} label={item.name} value={values[item.name] ?? ''}
            type={item.type === 'number' || item.type === 'integer' ? 'number' : 'text'}
            step={item.type === 'integer' ? 1 : item.type === 'number' ? 'any' : undefined}
            maxLength={item.type === 'string' ? item.max_length : undefined}
            hint={item.description}
            onChange={(e) => setVariableValues({ ...values, [item.name]: e.target.value })}
          />)}
        </div>
      </fieldset>}
      {editableVariables.length === 0 && <p className="field-hint">This agent has no editable call variables yet. An owner can add them to a new agent-version draft.</p>}
      <Button type="submit" busy={busy === 'save'} disabled={busy !== null}>Save instructions</Button>
    </form>
    <hr />
    <section className="knowledge-add" aria-labelledby="add-training-knowledge">
      <div>
        <h3 id="add-training-knowledge">Add knowledge for your agent</h3>
        <p className="muted">Paste information or upload a file. We detect its type and prepare it for Sarvam automatically.</p>
      </div>
      <label
        className={`knowledge-dropzone${dragging ? ' knowledge-dropzone-active' : ''}`}
        onDragEnter={(e) => { e.preventDefault(); setDragging(true); }}
        onDragOver={(e) => e.preventDefault()}
        onDragLeave={() => setDragging(false)}
        onDrop={(e) => void dropFile(e)}
      >
        <span className="knowledge-dropzone-icon" aria-hidden="true">↑</span>
        <strong>{busy === 'pdf' ? 'Reading PDF…' : 'Drop a PDF, TXT or Markdown file here'}</strong>
        <span className="field-hint">or click to choose · maximum 5 MB</span>
        <input className="sr-only" type="file" accept="application/pdf,text/plain,text/markdown,.pdf,.txt,.md" disabled={busy !== null} onChange={(e) => void uploadFile(e)} />
      </label>
      <div className="knowledge-divider"><span>or paste text</span></div>
      <form className="form form-wide" onSubmit={addText}>
        <TextField label="Title" maxLength={200} placeholder="Example: Fees and admission rules" value={title} onChange={(e) => setTitle(e.target.value)} />
        <TextAreaField label="Information for the agent" rows={6} maxLength={30000} value={text} onChange={(e) => setText(e.target.value)} />
        <Button type="submit" busy={busy === 'text'} disabled={busy !== null || !title.trim() || !text.trim()}>Add to agent knowledge</Button>
      </form>
    </section>
    <div className="form form-wide">
      <SelectField label="Use one of your completed calls" value={sessionId} onChange={(e) => setSessionId(e.target.value)} options={[
        { value: '', label: ownSessions.length ? 'Choose a call transcript' : 'No completed calls available' },
        ...ownSessions.map((x) => ({ value: x.id, label: `${new Date(x.created_at).toLocaleDateString()} · ${x.scenario_name ?? 'Practice call'}` })),
      ]} />
      <Button variant="secondary" busy={busy === 'transcript'} disabled={busy !== null || !sessionId} onClick={() => void importTranscript()}>Add transcript</Button>
    </div>
    <h3>Ready for the next call <span className="badge badge-ok">{data.sources.length}</span></h3>
    {data.sources.length === 0 ? <EmptyState title="No personal training sources yet." /> : <ul className="card-list">
      {data.sources.map((source) => <li className="card" key={source.id}><div className="card-main">
        <h4 className="card-title">{source.title}</h4><p className="card-meta"><span className="badge">{source.kind}</span> · {source.text.length.toLocaleString()} characters</p>
      </div><Button size="sm" variant="danger" disabled={busy !== null} onClick={() => void remove(source.id)}>Remove</Button></li>)}
    </ul>}
  </section>;
}
