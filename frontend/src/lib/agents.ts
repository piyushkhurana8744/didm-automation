/**
 * Shared helpers for the voice agent pages: API paths, labels, and client-side checks that mirror the
 * backend's validation so people see problems inline. The server always re-checks everything.
 */
import { seg } from './api';
import { formatDate, plural } from './format';
import type { MyAgent, AssignmentSettings, AssignmentState, Channel, Difficulty, ScenarioStatus, VarDef, VarType } from './types';

/** `/organizations/{org}` + path. */
export function orgPath(orgId: string, path: string): string {
  return `/organizations/${seg(orgId)}${path}`;
}

/** Builds `?a=1&b=2`, leaving out empty values. */
export function query(params: Record<string, string | number | boolean | null | undefined>): string {
  const q = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v === null || v === undefined || v === '') continue;
    q.set(k, String(v));
  }
  const s = q.toString();
  return s ? `?${s}` : '';
}

export const CHANNELS: Channel[] = ['phone', 'browser'];
export const CHANNEL_LABELS: Record<Channel, string> = { phone: 'Phone call', browser: 'Browser voice' };

export const DIFFICULTIES: Difficulty[] = ['beginner', 'intermediate', 'advanced'];
export const DIFFICULTY_LABELS: Record<Difficulty, string> = {
  beginner: 'Beginner',
  intermediate: 'Intermediate',
  advanced: 'Advanced',
};

export const SCENARIO_STATUS_BADGE: Record<ScenarioStatus, string> = {
  draft: 'badge badge-info',
  active: 'badge badge-ok',
  archived: 'badge',
};

export const ASSIGNMENT_STATE_BADGE: Record<AssignmentState, string> = {
  active: 'badge badge-ok',
  scheduled: 'badge badge-info',
  expired: 'badge badge-warn',
  revoked: 'badge',
  replaced: 'badge',
};

export const VAR_TYPES: VarType[] = ['string', 'number', 'integer', 'boolean', 'enum'];
export const VAR_TYPE_LABELS: Record<VarType, string> = {
  string: 'Text',
  number: 'Number',
  integer: 'Whole number',
  boolean: 'Yes / no',
  enum: 'Choice',
};

export const VAR_NAME_RE = /^[a-z_][a-z0-9_]{0,63}$/;
export const APP_ID_RE = /^[A-Za-z0-9][A-Za-z0-9_.:-]{0,199}$/;
const SECRET_KEY_RE = /(api[_-]?key|secret|token|password|credential)/i;

export function channelList(channels: Channel[]): string {
  return channels.length ? channels.map((c) => CHANNEL_LABELS[c] ?? c).join(', ') : 'None';
}

export function settingsSummary(s: AssignmentSettings | null | undefined): string {
  if (!s) return 'No limits';
  const parts: string[] = [];
  if (s.allowed_scenario_ids?.length) parts.push(`${s.allowed_scenario_ids.length} scenario${s.allowed_scenario_ids.length === 1 ? '' : 's'}`);
  if (s.max_sessions) parts.push(`max ${s.max_sessions} session${s.max_sessions === 1 ? '' : 's'}`);
  if (s.max_minutes_per_session) parts.push(`${s.max_minutes_per_session} min per session`);
  return parts.length ? parts.join(' · ') : 'No limits';
}

/** Parses an optional whole number input. Returns undefined for empty, NaN for invalid. */
export function parseOptionalInt(value: string): number | undefined {
  const v = value.trim();
  if (!v) return undefined;
  return /^-?\d+$/.test(v) ? Number(v) : NaN;
}

/** Problems with a configuration JSON text, mirroring the backend (an object, no credential-like keys). */
export function parseConfiguration(text: string): { value: Record<string, unknown> | null; error: string | null } {
  const t = text.trim();
  if (!t) return { value: {}, error: null };
  let parsed: unknown;
  try {
    parsed = JSON.parse(t);
  } catch (e) {
    return { value: null, error: `Not valid JSON: ${e instanceof Error ? e.message : 'parse error'}.` };
  }
  if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
    return { value: null, error: 'The configuration must be a JSON object, like {"language": "hi-IN"}.' };
  }
  const bad: string[] = [];
  const walk = (obj: unknown, path: string) => {
    if (Array.isArray(obj)) obj.forEach((x) => walk(x, path));
    else if (obj && typeof obj === 'object') {
      for (const [k, v] of Object.entries(obj as Record<string, unknown>)) {
        if (SECRET_KEY_RE.test(k)) bad.push(`${path}${k}`);
        walk(v, `${path}${k}.`);
      }
    }
  };
  walk(parsed, '');
  if (bad.length) {
    return {
      value: null,
      error: `Do not store credentials in the configuration (${bad.join(', ')}). Provider keys stay in the server settings.`,
    };
  }
  return { value: parsed as Record<string, unknown>, error: null };
}

/** One row of the variable schema editor; every input is kept as text until it is saved. */
export interface VarRow {
  key: string;
  name: string;
  type: VarType;
  required: boolean;
  description: string;
  options: string;
  max_length: string;
  min: string;
  max: string;
  default: string;
}

let rowSeq = 0;
export function newVarRow(partial: Partial<VarRow> = {}): VarRow {
  rowSeq += 1;
  return {
    key: `row-${rowSeq}`,
    name: '',
    type: 'string',
    required: false,
    description: '',
    options: '',
    max_length: '',
    min: '',
    max: '',
    default: '',
    ...partial,
  };
}

export function rowsFromSchema(schema: VarDef[]): VarRow[] {
  return (schema ?? []).map((v) =>
    newVarRow({
      name: v.name ?? '',
      type: v.type ?? 'string',
      required: !!v.required,
      description: v.description ?? '',
      options: (v.options ?? []).join(', '),
      max_length: v.max_length !== undefined ? String(v.max_length) : '',
      min: v.min !== undefined ? String(v.min) : '',
      max: v.max !== undefined ? String(v.max) : '',
      default: v.default !== undefined ? String(v.default) : '',
    }),
  );
}

export function splitOptions(text: string): string[] {
  return text
    .split(',')
    .map((o) => o.trim())
    .filter(Boolean);
}

/** Problem with one value against its variable definition (mirrors the backend), or null. */
export function valueProblem(v: VarDef, value: unknown): string | null {
  switch (v.type) {
    case 'string': {
      if (typeof value !== 'string') return 'must be text.';
      const max = v.max_length ?? 2000;
      if (value.length > max) return `must be at most ${max} characters.`;
      break;
    }
    case 'number':
      if (typeof value !== 'number' || !Number.isFinite(value)) return 'must be a number.';
      break;
    case 'integer':
      if (typeof value !== 'number' || !Number.isInteger(value)) return 'must be a whole number.';
      break;
    case 'boolean':
      if (typeof value !== 'boolean') return 'must be true or false.';
      break;
    case 'enum':
      if (!(v.options ?? []).includes(value as string)) return 'must be one of the listed options.';
      break;
  }
  if ((v.type === 'number' || v.type === 'integer') && typeof value === 'number') {
    if (v.min !== undefined && value < v.min) return `must be at least ${v.min}.`;
    if (v.max !== undefined && value > v.max) return `must be at most ${v.max}.`;
  }
  return null;
}

function parseNumberText(text: string, integer: boolean): number | undefined {
  const t = text.trim();
  if (!t) return undefined;
  if (integer ? !/^-?\d+$/.test(t) : !/^-?(\d+\.?\d*|\.\d+)([eE][-+]?\d+)?$/.test(t)) return NaN;
  return Number(t);
}

/** Turns editor rows into a schema, with problems per row key (empty when the schema is valid). */
export function schemaFromRows(rows: VarRow[]): { schema: VarDef[]; problems: Record<string, string[]> } {
  const problems: Record<string, string[]> = {};
  const seen = new Set<string>();
  const schema: VarDef[] = [];
  const add = (key: string, p: string) => {
    (problems[key] ??= []).push(p);
  };
  if (rows.length > 50) add(rows[50].key, 'At most 50 variables.');
  for (const r of rows) {
    const name = r.name.trim();
    if (!VAR_NAME_RE.test(name)) add(r.key, 'Name: lower-case letters, digits and underscores, starting with a letter or underscore.');
    else if (seen.has(name)) add(r.key, `"${name}" is defined twice.`);
    seen.add(name);
    const v: VarDef = { name, type: r.type };
    if (r.required) v.required = true;
    if (r.description.trim()) {
      if (r.description.trim().length > 500) add(r.key, 'Description: up to 500 characters.');
      v.description = r.description.trim();
    }
    if (r.type === 'enum') {
      const opts = splitOptions(r.options);
      if (opts.length < 1 || opts.length > 50) add(r.key, 'A choice needs 1 to 50 options, separated by commas.');
      else if (new Set(opts).size !== opts.length) add(r.key, 'Options must be different from each other.');
      else if (opts.some((o) => o.length > 200)) add(r.key, 'Each option can be up to 200 characters.');
      v.options = opts;
    }
    if (r.type === 'string' && r.max_length.trim()) {
      const n = parseOptionalInt(r.max_length);
      if (n === undefined || Number.isNaN(n) || n < 1 || n > 5000) add(r.key, 'Max length: a whole number from 1 to 5000.');
      else v.max_length = n;
    }
    if (r.type === 'number' || r.type === 'integer') {
      for (const bound of ['min', 'max'] as const) {
        const n = parseNumberText(r[bound], false);
        if (n === undefined) continue;
        if (Number.isNaN(n)) add(r.key, `${bound === 'min' ? 'Minimum' : 'Maximum'} must be a number.`);
        else v[bound] = n;
      }
      if (v.min !== undefined && v.max !== undefined && v.min > v.max) add(r.key, 'The minimum is above the maximum.');
    }
    const d = r.default.trim();
    if (d) {
      let value: unknown = d;
      if (r.type === 'number' || r.type === 'integer') value = parseNumberText(d, r.type === 'integer');
      else if (r.type === 'boolean') value = d === 'true' ? true : d === 'false' ? false : d;
      const err = typeof value === 'number' && Number.isNaN(value) ? `must be ${r.type === 'integer' ? 'a whole number' : 'a number'}.` : valueProblem(v, value);
      if (err) add(r.key, `Default ${err}`);
      else v.default = value as VarDef['default'];
    }
    schema.push(v);
  }
  return { schema, problems };
}

/** Raw form values for scenario variables: text for inputs and selects, booleans for checkboxes. */
export type RawVariables = Record<string, string | boolean>;

export function rawFromValues(schema: VarDef[], values: Record<string, unknown>): RawVariables {
  const raw: RawVariables = {};
  for (const v of schema) {
    const current = v.name in values ? values[v.name] : undefined;
    if (v.type === 'boolean') {
      raw[v.name] = typeof current === 'boolean' ? current : v.default === true;
    } else {
      raw[v.name] = current === undefined || current === null ? '' : String(current);
    }
  }
  return raw;
}

/**
 * Converts raw inputs into typed values. Empty inputs are left out (the agent's default applies).
 * With requireAll, required variables without a default must be filled (the backend demands it for
 * active scenarios).
 */
export function valuesFromRaw(
  schema: VarDef[],
  raw: RawVariables,
  requireAll: boolean,
): { values: Record<string, unknown>; errors: Record<string, string> } {
  const values: Record<string, unknown> = {};
  const errors: Record<string, string> = {};
  for (const v of schema) {
    const r = raw[v.name];
    if (v.type === 'boolean') {
      values[v.name] = r === true;
      continue;
    }
    const text = typeof r === 'string' ? r : '';
    if (!text.trim()) {
      if (requireAll && v.required && v.default === undefined) errors[v.name] = 'This is required for an active scenario.';
      continue;
    }
    let value: unknown = v.type === 'string' ? text : text.trim();
    if (v.type === 'number' || v.type === 'integer') {
      value = parseNumberText(text, v.type === 'integer');
      if (Number.isNaN(value as number)) {
        errors[v.name] = v.type === 'integer' ? 'Enter a whole number.' : 'Enter a number.';
        continue;
      }
    }
    const err = valueProblem(v, value);
    if (err) errors[v.name] = `This ${err}`;
    else values[v.name] = value;
  }
  return { values, errors };
}

/** "Through your team · until 3 Nov 2026 · up to 5 sessions" for a trainee's agent. */
export function accessLine(a: MyAgent): string {
  const parts = [a.access.source === 'team' ? 'Through your team' : 'Assigned to you'];
  parts.push(a.access.expires_at ? `until ${formatDate(a.access.expires_at)}` : 'no end date');
  if (a.access.max_sessions) parts.push(`up to ${plural(a.access.max_sessions, 'session')}`);
  if (a.access.max_minutes_per_session) parts.push(`${a.access.max_minutes_per_session} min per session`);
  return parts.join(' · ');
}
