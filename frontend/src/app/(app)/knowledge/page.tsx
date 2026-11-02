'use client';

import { useState, type FormEvent } from 'react';
import { api, errorMessage } from '@/lib/api';
import { orgPath } from '@/lib/agents';
import type { KnowledgeCapabilities, KnowledgeDocument, KnowledgeLibrary, Membership } from '@/lib/types';
import { useLoad } from '@/lib/useLoad';
import { Button } from '@/components/Button';
import { EmptyState } from '@/components/EmptyState';
import { ErrorState } from '@/components/ErrorState';
import { FormError, SelectField, TextAreaField, TextField } from '@/components/Field';
import { OrgGate } from '@/components/OrgGate';
import { PageHeader } from '@/components/PageHeader';
import { SkeletonRows } from '@/components/Spinner';

function KnowledgePage({ membership }: { membership: Membership }) {
  const orgId = membership.organization.id;
  const canManage = membership.permissions.includes('knowledge.manage');
  const libraries = useLoad(() => api.get<KnowledgeLibrary[]>(orgPath(orgId, '/knowledge/libraries')), orgId);
  const documents = useLoad(() => api.get<KnowledgeDocument[]>(orgPath(orgId, '/knowledge/documents')), orgId);
  const capabilities = useLoad(() => api.get<KnowledgeCapabilities>(orgPath(orgId, '/knowledge/capabilities')), orgId);
  const [libraryName, setLibraryName] = useState('');
  const [libraryDescription, setLibraryDescription] = useState('');
  const [libraryId, setLibraryId] = useState('');
  const [kind, setKind] = useState<'manual' | 'faq'>('faq');
  const [title, setTitle] = useState('');
  const [content, setContent] = useState('');
  const [busy, setBusy] = useState<'library' | 'knowledge' | null>(null);
  const [formError, setFormError] = useState<string | null>(null);

  async function createLibrary(e: FormEvent) {
    e.preventDefault();
    if (!libraryName.trim()) return setFormError('Enter a library name.');
    setBusy('library'); setFormError(null);
    try {
      const created = await api.post<KnowledgeLibrary>(orgPath(orgId, '/knowledge/libraries'), {
        name: libraryName.trim(), description: libraryDescription.trim(),
      });
      setLibraryName(''); setLibraryDescription(''); setLibraryId(created.id);
      libraries.reload();
    } catch (e) { setFormError(errorMessage(e)); } finally { setBusy(null); }
  }

  async function createKnowledge(e: FormEvent) {
    e.preventDefault();
    if (!libraryId || !title.trim() || !content.trim()) return setFormError('Choose a library and complete every knowledge field.');
    setBusy('knowledge'); setFormError(null);
    try {
      await api.post(orgPath(orgId, '/knowledge/manual'), {
        library_id: libraryId, title: title.trim(), content: content.trim(), kind, locale: 'en-IN',
      });
      setTitle(''); setContent(''); documents.reload();
    } catch (e) { setFormError(errorMessage(e)); } finally { setBusy(null); }
  }

  const loading = (libraries.loading && !libraries.data) || (documents.loading && !documents.data);
  if (loading) return <SkeletonRows label="Loading knowledge library" />;
  if (libraries.error || documents.error) return <ErrorState error={libraries.error || documents.error} onRetry={() => { libraries.reload(); documents.reload(); }} />;

  return <>
    <PageHeader title="Knowledge library" description="Approved, versioned information for DIDM AI agents." />
    <section className="panel panel-highlight" aria-labelledby="knowledge-safety">
      <h2 id="knowledge-safety" className="panel-title">Local knowledge workspace</h2>
      <p>Manual knowledge, FAQs, retrieval and validation stay inside DIDM. Sarvam synchronization is unavailable and existing Sarvam agents are untouched.</p>
      {capabilities.data && !capabilities.data.file_upload && <p className="field-hint"><strong>Document upload is locked:</strong> {capabilities.data.file_upload_reason}</p>}
    </section>
    {canManage && <section className="panel" aria-labelledby="new-library">
      <h2 id="new-library" className="panel-title">Create a library</h2>
      <form onSubmit={createLibrary} className="form form-wide">
        <FormError message={formError} />
        <TextField label="Library name" maxLength={200} value={libraryName} onChange={(e) => setLibraryName(e.target.value)} />
        <TextAreaField label="Description" maxLength={5000} value={libraryDescription} onChange={(e) => setLibraryDescription(e.target.value)} />
        <Button type="submit" busy={busy === 'library'}>Create library</Button>
      </form>
    </section>}
    {canManage && <section className="panel" aria-labelledby="new-knowledge">
      <h2 id="new-knowledge" className="panel-title">Add approved knowledge</h2>
      {(libraries.data ?? []).length === 0 ? <EmptyState title="Create a library first." /> : <form onSubmit={createKnowledge} className="form form-wide">
        <SelectField label="Library" value={libraryId} onChange={(e) => setLibraryId(e.target.value)} options={[{ value: '', label: 'Choose a library' }, ...(libraries.data ?? []).map((x) => ({ value: x.id, label: x.name }))]} />
        <SelectField label="Knowledge type" value={kind} onChange={(e) => setKind(e.target.value as 'manual' | 'faq')} options={[{ value: 'faq', label: 'FAQ / approved answer' }, { value: 'manual', label: 'Manual reference note' }]} />
        <TextField label={kind === 'faq' ? 'Question or topic' : 'Title'} maxLength={300} value={title} onChange={(e) => setTitle(e.target.value)} />
        <TextAreaField label="Approved information" rows={8} maxLength={200000} value={content} onChange={(e) => setContent(e.target.value)} hint="Only approved facts belong here. Content is versioned and cannot rewrite a prepared snapshot." />
        <Button type="submit" busy={busy === 'knowledge'}>Save knowledge</Button>
      </form>}
    </section>}
    <section aria-labelledby="knowledge-items">
      <h2 id="knowledge-items">Knowledge items</h2>
      {(documents.data ?? []).length === 0 ? <EmptyState title="No approved knowledge yet." /> : <ul className="card-list">
        {(documents.data ?? []).map((doc) => <li key={doc.id} className="card"><div className="card-main">
          <h3 className="card-title">{doc.title}</h3>
          <p className="card-meta"><span className="badge">{doc.kind === 'faq' ? 'FAQ' : 'Manual'}</span> Revision {doc.revision?.revision_no ?? '—'} · {doc.revision?.processing_state ?? 'unknown'}</p>
          <p className="small muted">Locale {doc.revision?.source_locale ?? '—'} · Content hash {doc.revision?.sha256?.slice(0, 12) ?? '—'}…</p>
        </div></li>)}
      </ul>}
    </section>
  </>;
}

export default function Page() {
  return <OrgGate permission="knowledge.view">{(m) => <KnowledgePage membership={m} />}</OrgGate>;
}
