'use client';

import Link from 'next/link';
import { useState, type FormEvent } from 'react';
import { api, errorMessage } from '@/lib/api';
import { AuthCard } from '@/components/AuthCard';
import { Button } from '@/components/Button';
import { FormError, FormSuccess, TextField } from '@/components/Field';

export default function ForgotPasswordPage() {
  const [email, setEmail] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState<string | null>(null);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    if (!email.trim()) {
      setError('Enter your email.');
      return;
    }
    setBusy(true);
    try {
      const res = await api.post<{ ok: boolean; message?: string }>('/auth/password/forgot', { email: email.trim() }, { redirectOn401: false });
      setDone(res?.message ?? 'If that email has an account, a reset link is on its way.');
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <AuthCard title="Forgot password" footer={<Link href="/login/">Back to log in</Link>}>
      {done ? (
        <FormSuccess message={done} />
      ) : (
        <form onSubmit={onSubmit} noValidate className="form">
          <p>Enter your account email and we will send you a link to choose a new password.</p>
          <FormError message={error} />
          <TextField label="Email" type="email" autoComplete="email" required value={email} onChange={(e) => setEmail(e.target.value)} />
          <Button type="submit" busy={busy} className="btn-block">
            Send reset link
          </Button>
        </form>
      )}
    </AuthCard>
  );
}
