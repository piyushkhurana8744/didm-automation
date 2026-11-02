'use client';

import { useId, useRef, useState } from 'react';
import { Button } from './Button';

/** Shows a secret invitation link once, with a copy button. The link is never stored or logged. */
export function OneTimeLink({ url, email, emailed, onDismiss }: { url: string; email: string; emailed: boolean; onDismiss: () => void }) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [copied, setCopied] = useState<'idle' | 'copied' | 'failed'>('idle');
  const id = useId();

  async function copy() {
    try {
      await navigator.clipboard.writeText(url);
      setCopied('copied');
    } catch {
      inputRef.current?.select();
      setCopied('failed');
    }
  }

  return (
    <section className="panel panel-highlight" aria-labelledby={`${id}-title`}>
      <h3 id={`${id}-title`} className="panel-title">
        Invitation link for {email}
      </h3>
      <p>
        {emailed
          ? `An email with this link was sent to ${email}.`
          : `Email is not configured, so this link was not emailed. Send it to ${email} yourself.`}
      </p>
      <div className="copy-row">
        <label htmlFor={id} className="visually-hidden">
          Invitation link
        </label>
        <input id={id} ref={inputRef} className="input mono" readOnly value={url} onFocus={(e) => e.currentTarget.select()} />
        <Button variant="primary" onClick={copy}>
          Copy link
        </Button>
      </div>
      <p className="field-hint" role="status" aria-live="polite">
        {copied === 'copied' ? 'Link copied.' : copied === 'failed' ? 'Could not copy automatically. The link is selected; copy it with your keyboard.' : ''}
      </p>
      <p className="note">
        <strong>Share this link only with {email}. It will not be shown again.</strong>
      </p>
      <Button variant="secondary" onClick={onDismiss}>
        Done
      </Button>
    </section>
  );
}
