'use client';

import { useId, type InputHTMLAttributes, type ReactNode, type SelectHTMLAttributes, type TextareaHTMLAttributes } from 'react';

interface FieldShellProps {
  id: string;
  label: ReactNode;
  hint?: ReactNode;
  error?: string | null;
  children: ReactNode;
}

function FieldShell({ id, label, hint, error, children }: FieldShellProps) {
  return (
    <div className={error ? 'field field-invalid' : 'field'}>
      <label htmlFor={id}>{label}</label>
      {children}
      {hint && (
        <p className="field-hint" id={`${id}-hint`}>
          {hint}
        </p>
      )}
      {error && (
        <p className="field-error" id={`${id}-error`}>
          {error}
        </p>
      )}
    </div>
  );
}

function describedBy(id: string, hint: unknown, error: unknown): string | undefined {
  const ids = [hint ? `${id}-hint` : '', error ? `${id}-error` : ''].filter(Boolean);
  return ids.length ? ids.join(' ') : undefined;
}

export interface TextFieldProps extends Omit<InputHTMLAttributes<HTMLInputElement>, 'id'> {
  label: ReactNode;
  hint?: ReactNode;
  error?: string | null;
  id?: string;
}

export function TextField({ label, hint, error, id, ...input }: TextFieldProps) {
  const auto = useId();
  const fid = id ?? auto;
  return (
    <FieldShell id={fid} label={label} hint={hint} error={error}>
      <input
        id={fid}
        className="input"
        aria-invalid={error ? true : undefined}
        aria-describedby={describedBy(fid, hint, error)}
        {...input}
      />
    </FieldShell>
  );
}

export interface SelectOption {
  value: string;
  label: string;
}

export interface SelectFieldProps extends Omit<SelectHTMLAttributes<HTMLSelectElement>, 'id'> {
  label: ReactNode;
  options: SelectOption[];
  hint?: ReactNode;
  error?: string | null;
  id?: string;
  /** Visually hide the label (it is still read by screen readers). */
  hideLabel?: boolean;
}

export function SelectField({ label, options, hint, error, id, hideLabel, ...select }: SelectFieldProps) {
  const auto = useId();
  const fid = id ?? auto;
  return (
    <FieldShell id={fid} label={hideLabel ? <span className="visually-hidden">{label}</span> : label} hint={hint} error={error}>
      <select
        id={fid}
        className="input"
        aria-invalid={error ? true : undefined}
        aria-describedby={describedBy(fid, hint, error)}
        {...select}
      >
        {options.map((o) => (
          <option key={o.value} value={o.value}>
            {o.label}
          </option>
        ))}
      </select>
    </FieldShell>
  );
}

export interface TextAreaFieldProps extends Omit<TextareaHTMLAttributes<HTMLTextAreaElement>, 'id'> {
  label: ReactNode;
  hint?: ReactNode;
  error?: string | null;
  id?: string;
}

export function TextAreaField({ label, hint, error, id, className, rows = 4, ...textarea }: TextAreaFieldProps) {
  const auto = useId();
  const fid = id ?? auto;
  return (
    <FieldShell id={fid} label={label} hint={hint} error={error}>
      <textarea
        id={fid}
        rows={rows}
        className={['input', 'textarea', className ?? ''].join(' ').trim()}
        aria-invalid={error ? true : undefined}
        aria-describedby={describedBy(fid, hint, error)}
        {...textarea}
      />
    </FieldShell>
  );
}

export interface CheckboxFieldProps extends Omit<InputHTMLAttributes<HTMLInputElement>, 'id' | 'type'> {
  label: ReactNode;
  hint?: ReactNode;
  error?: string | null;
  id?: string;
}

/** A single checkbox with its label to the right. */
export function CheckboxField({ label, hint, error, id, ...input }: CheckboxFieldProps) {
  const auto = useId();
  const fid = id ?? auto;
  return (
    <div className={error ? 'field field-check field-invalid' : 'field field-check'}>
      <div className="check-row">
        <input id={fid} type="checkbox" className="check" aria-invalid={error ? true : undefined} aria-describedby={describedBy(fid, hint, error)} {...input} />
        <label htmlFor={fid}>{label}</label>
      </div>
      {hint && (
        <p className="field-hint" id={`${fid}-hint`}>
          {hint}
        </p>
      )}
      {error && (
        <p className="field-error" id={`${fid}-error`}>
          {error}
        </p>
      )}
    </div>
  );
}

export function ReadOnlyField({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div className="field">
      <span className="field-label">{label}</span>
      <span className="readonly-value">{value}</span>
    </div>
  );
}

export function FormError({ message }: { message: string | null }) {
  if (!message) return null;
  return (
    <div className="alert alert-error" role="alert">
      {message}
    </div>
  );
}

export function FormSuccess({ message }: { message: string | null }) {
  if (!message) return null;
  return (
    <div className="alert alert-success" role="status">
      {message}
    </div>
  );
}
