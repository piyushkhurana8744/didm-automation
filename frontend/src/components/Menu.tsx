'use client';

import { useEffect, useId, useRef, useState, type ReactNode } from 'react';

/**
 * A disclosure dropdown: a button that shows and hides a list of links/buttons.
 * Keyboard: Enter/Space toggles, Tab moves through items, Escape closes and returns focus to the button.
 */
export function Menu({
  label,
  buttonContent,
  align = 'end',
  children,
}: {
  /** Accessible name of the button. */
  label: string;
  buttonContent: ReactNode;
  align?: 'start' | 'end';
  children: (close: () => void) => ReactNode;
}) {
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);
  const buttonRef = useRef<HTMLButtonElement>(null);
  const id = useId();

  useEffect(() => {
    if (!open) return;
    function onPointer(e: MouseEvent) {
      if (rootRef.current && !rootRef.current.contains(e.target as Node)) setOpen(false);
    }
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape') {
        setOpen(false);
        buttonRef.current?.focus();
      }
    }
    function onFocus(e: FocusEvent) {
      if (rootRef.current && e.target instanceof Node && !rootRef.current.contains(e.target)) setOpen(false);
    }
    document.addEventListener('mousedown', onPointer);
    document.addEventListener('keydown', onKey);
    document.addEventListener('focusin', onFocus);
    return () => {
      document.removeEventListener('mousedown', onPointer);
      document.removeEventListener('keydown', onKey);
      document.removeEventListener('focusin', onFocus);
    };
  }, [open]);

  return (
    <div className="menu" ref={rootRef}>
      <button
        ref={buttonRef}
        type="button"
        className="menu-button"
        aria-label={label}
        aria-expanded={open}
        aria-controls={id}
        onClick={() => setOpen((o) => !o)}
      >
        {buttonContent}
        <span className="chevron" aria-hidden="true">
          ▾
        </span>
      </button>
      <div id={id} className={`menu-popup menu-${align}`} hidden={!open}>
        {children(() => setOpen(false))}
      </div>
    </div>
  );
}
