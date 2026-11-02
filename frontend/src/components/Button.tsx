import Link from 'next/link';
import type { ButtonHTMLAttributes, ReactNode, Ref } from 'react';

type Variant = 'primary' | 'secondary' | 'danger' | 'ghost';

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
  busy?: boolean;
  size?: 'sm' | 'md';
  ref?: Ref<HTMLButtonElement>;
}

export function Button({ variant = 'primary', busy = false, size = 'md', className, disabled, children, type, ...rest }: ButtonProps) {
  return (
    <button
      type={type ?? 'button'}
      className={['btn', `btn-${variant}`, size === 'sm' ? 'btn-sm' : '', className ?? ''].join(' ').trim()}
      disabled={disabled || busy}
      aria-busy={busy || undefined}
      {...rest}
    >
      {busy && <span className="spinner spinner-sm" aria-hidden="true" />}
      {children}
    </button>
  );
}

export function ButtonLink({ href, variant = 'secondary', children }: { href: string; variant?: Variant; children: ReactNode }) {
  return (
    <Link href={href} className={`btn btn-${variant}`}>
      {children}
    </Link>
  );
}
