'use client';

import { useId, useState, type ReactNode } from 'react';

export interface CheckOption {
  value: string;
  label: string;
  /** Extra text after the label (role, email…). Also searched. */
  meta?: string;
  disabled?: boolean;
}

/**
 * A multi-select as a fieldset of checkboxes, with a filter box when the list is long.
 */
export function CheckList({
  legend,
  options,
  selected,
  onChange,
  hint,
  error,
  empty,
  searchThreshold = 8,
}: {
  legend: ReactNode;
  options: CheckOption[];
  selected: string[];
  onChange: (next: string[]) => void;
  hint?: ReactNode;
  error?: string | null;
  empty?: ReactNode;
  searchThreshold?: number;
}) {
  const id = useId();
  const [filter, setFilter] = useState('');
  const f = filter.trim().toLowerCase();
  const shown = f ? options.filter((o) => `${o.label} ${o.meta ?? ''}`.toLowerCase().includes(f)) : options;
  const chosen = new Set(selected);

  function toggle(value: string, on: boolean) {
    const next = new Set(chosen);
    if (on) next.add(value);
    else next.delete(value);
    onChange(options.map((o) => o.value).filter((v) => next.has(v)));
  }

  return (
    <fieldset className={error ? 'checklist field-invalid' : 'checklist'} aria-describedby={[hint ? `${id}-hint` : '', error ? `${id}-error` : ''].filter(Boolean).join(' ') || undefined}>
      <legend>
        {legend}
        {selected.length > 0 && <span className="badge badge-info checklist-count">{selected.length} selected</span>}
      </legend>
      {hint && (
        <p className="field-hint" id={`${id}-hint`}>
          {hint}
        </p>
      )}
      {options.length === 0 ? (
        <div className="muted small">{empty ?? 'Nothing to choose from.'}</div>
      ) : (
        <>
          {options.length >= searchThreshold && (
            <div className="checklist-tools">
              <label htmlFor={`${id}-filter`} className="visually-hidden">
                Filter
              </label>
              <input id={`${id}-filter`} className="input" type="search" placeholder="Filter…" value={filter} onChange={(e) => setFilter(e.target.value)} />
              <button type="button" className="link-button" onClick={() => onChange(Array.from(new Set([...selected, ...shown.filter((o) => !o.disabled).map((o) => o.value)])))}>
                Select shown
              </button>
              {selected.length > 0 && (
                <button type="button" className="link-button" onClick={() => onChange([])}>
                  Clear
                </button>
              )}
            </div>
          )}
          <ul className="checklist-items">
            {shown.map((o) => (
              <li key={o.value}>
                <label className={o.disabled ? 'check-row check-disabled' : 'check-row'}>
                  <input type="checkbox" className="check" checked={chosen.has(o.value)} disabled={o.disabled} onChange={(e) => toggle(o.value, e.target.checked)} />
                  <span className="break">
                    {o.label}
                    {o.meta && <span className="muted small"> · {o.meta}</span>}
                  </span>
                </label>
              </li>
            ))}
            {shown.length === 0 && <li className="muted small">Nothing matches “{filter}”.</li>}
          </ul>
        </>
      )}
      {error && (
        <p className="field-error" id={`${id}-error`}>
          {error}
        </p>
      )}
    </fieldset>
  );
}
