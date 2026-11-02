import { VAR_TYPE_LABELS } from '@/lib/agents';
import { formatDateTime } from '@/lib/format';
import type { AgentVersion, VarDef } from '@/lib/types';
import { DataTable, type Column } from '../DataTable';
import { EmptyState } from '../EmptyState';

function rules(v: VarDef): string {
  const parts: string[] = [];
  if (v.type === 'enum' && v.options?.length) parts.push(`Options: ${v.options.join(', ')}`);
  if (v.max_length !== undefined) parts.push(`Up to ${v.max_length} characters`);
  if (v.min !== undefined) parts.push(`Min ${v.min}`);
  if (v.max !== undefined) parts.push(`Max ${v.max}`);
  if (v.default !== undefined) parts.push(`Default ${String(v.default)}`);
  return parts.join(' · ') || '—';
}

export function VariableSchemaTable({ schema }: { schema: VarDef[] }) {
  const columns: Column<VarDef>[] = [
    { key: 'name', header: 'Name', render: (v) => <span className="mono">{v.name}</span> },
    { key: 'type', header: 'Type', render: (v) => VAR_TYPE_LABELS[v.type] ?? v.type },
    { key: 'required', header: 'Required', render: (v) => (v.required ? 'Yes' : 'No') },
    { key: 'rules', header: 'Rules', render: (v) => <span className="small">{rules(v)}</span> },
    { key: 'description', header: 'Description', render: (v) => <span className="small">{v.description || '—'}</span> },
  ];
  return (
    <DataTable
      caption="Variable schema"
      columns={columns}
      rows={schema}
      rowKey={(v) => v.name}
      empty={<EmptyState title="No variables are defined." />}
    />
  );
}

/** A version shown read-only. Published versions never change. */
export function VersionView({ version }: { version: AgentVersion }) {
  const config = version.configuration_snapshot ?? {};
  return (
    <div>
      <dl className="facts facts-wide">
        <div>
          <dt>Status</dt>
          <dd>{version.status === 'published' ? `Published ${formatDateTime(version.published_at)}` : 'Draft'}</dd>
        </div>
        <div>
          <dt>Sarvam app version</dt>
          <dd>{version.provider_app_version ?? <span className="muted">Not set</span>}</dd>
        </div>
        <div>
          <dt>Knowledge base</dt>
          <dd className="break">{version.knowledge_base_reference || <span className="muted">—</span>}</dd>
        </div>
        <div>
          <dt>Rubric</dt>
          <dd className="break">{version.rubric_reference || <span className="muted">—</span>}</dd>
        </div>
        <div>
          <dt>Created</dt>
          <dd>{formatDateTime(version.created_at)}</dd>
        </div>
      </dl>
      <h4>Configuration</h4>
      {Object.keys(config).length === 0 ? <p className="muted small">Empty.</p> : <pre className="code-block">{JSON.stringify(config, null, 2)}</pre>}
      <h4>Variables</h4>
      <VariableSchemaTable schema={version.variable_schema ?? []} />
      {version.notes && (
        <>
          <h4>Notes</h4>
          <p className="break" style={{ whiteSpace: 'pre-wrap' }}>
            {version.notes}
          </p>
        </>
      )}
    </div>
  );
}
