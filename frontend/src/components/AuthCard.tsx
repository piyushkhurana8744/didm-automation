import type { ReactNode } from 'react';

/** Layout for the logged-out pages (login, password reset, invitation). */
export function AuthCard({ title, children, footer }: { title: string; children: ReactNode; footer?: ReactNode }) {
  return (
    <main id="main" className="auth-page">
      <div className="auth-card">
        <p className="brand brand-auth">DIDM Voice Training</p>
        <h1>{title}</h1>
        {children}
        {footer && <div className="auth-footer">{footer}</div>}
      </div>
    </main>
  );
}
