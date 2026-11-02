'use client';

import type { RawVariables } from '@/lib/agents';
import type { VarDef } from '@/lib/types';
import { CheckboxField, SelectField, TextField } from './Field';

function hintFor(v: VarDef): string | undefined {
  const parts: string[] = [];
  if (v.description) parts.push(v.description);
  if ((v.type === 'number' || v.type === 'integer') && (v.min !== undefined || v.max !== undefined)) {
    if (v.min !== undefined && v.max !== undefined) parts.push(`From ${v.min} to ${v.max}.`);
    else if (v.min !== undefined) parts.push(`At least ${v.min}.`);
    else parts.push(`At most ${v.max}.`);
  }
  if (v.default !== undefined && v.type !== 'boolean') parts.push(`Leave empty to use the default (${String(v.default)}).`);
  return parts.length ? parts.join(' ') : undefined;
}

/** Inputs for a scenario's agent variables, built from the agent version's variable schema. */
export function VariablesForm({
  schema,
  raw,
  errors,
  onChange,
  disabled,
}: {
  schema: VarDef[];
  raw: RawVariables;
  errors: Record<string, string>;
  onChange: (name: string, value: string | boolean) => void;
  disabled?: boolean;
}) {
  if (schema.length === 0) return <p className="muted small">This agent version defines no variables.</p>;
  return (
    <div className="var-grid">
      {schema.map((v) => {
        const label = (
          <>
            <span className="mono">{v.name}</span>
            {v.required && <span className="muted small"> (required)</span>}
          </>
        );
        const err = errors[v.name] ?? null;
        const hint = hintFor(v);
        if (v.type === 'boolean') {
          return (
            <CheckboxField
              key={v.name}
              label={label}
              hint={hint}
              error={err}
              checked={raw[v.name] === true}
              disabled={disabled}
              onChange={(e) => onChange(v.name, e.target.checked)}
            />
          );
        }
        if (v.type === 'enum') {
          const opts = [{ value: '', label: v.default !== undefined ? `Default (${String(v.default)})` : '— Not set —' }, ...(v.options ?? []).map((o) => ({ value: o, label: o }))];
          return (
            <SelectField
              key={v.name}
              label={label}
              hint={v.description}
              error={err}
              options={opts}
              value={typeof raw[v.name] === 'string' ? (raw[v.name] as string) : ''}
              disabled={disabled}
              onChange={(e) => onChange(v.name, e.target.value)}
            />
          );
        }
        const numeric = v.type === 'number' || v.type === 'integer';
        return (
          <TextField
            key={v.name}
            label={label}
            hint={hint}
            error={err}
            type={numeric ? 'number' : 'text'}
            inputMode={v.type === 'integer' ? 'numeric' : numeric ? 'decimal' : undefined}
            step={v.type === 'integer' ? 1 : numeric ? 'any' : undefined}
            min={numeric ? v.min : undefined}
            max={numeric ? v.max : undefined}
            maxLength={v.type === 'string' ? v.max_length ?? 2000 : undefined}
            value={typeof raw[v.name] === 'string' ? (raw[v.name] as string) : ''}
            disabled={disabled}
            onChange={(e) => onChange(v.name, e.target.value)}
          />
        );
      })}
    </div>
  );
}
