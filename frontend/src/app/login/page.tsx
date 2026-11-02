'use client';

import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { useEffect, useState, type FormEvent } from 'react';
import { api, errorMessage, isApiError } from '@/lib/api';
import { hasStashedInviteToken } from '@/lib/secrets';
import type { LoginResponse } from '@/lib/types';
import { AuthCard } from '@/components/AuthCard';
import { Button } from '@/components/Button';
import { FormError, TextField } from '@/components/Field';

export default function LoginPage() {
  const router = useRouter();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [forInvite, setForInvite] = useState(false);

  useEffect(() => setForInvite(hasStashedInviteToken()), []);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    if (!email.trim() || !password) {
      setError('Enter your email and password.');
      return;
    }
    setBusy(true);
    try {
      await api.post<LoginResponse>('/auth/login', { email: email.trim(), password }, { redirectOn401: false });
      setPassword('');
      router.replace(hasStashedInviteToken() ? '/invite/accept/' : '/');
    } catch (err) {
      setBusy(false);
      if (isApiError(err) && err.status === 429) setError('Too many attempts. Wait a few minutes and try again.');
      else setError(errorMessage(err));
    }
  }

  return (
    <AuthCard title="Log in" footer={<Link href="/forgot-password/">Forgot password?</Link>}>
      {forInvite && <p className="note">Log in to continue accepting your invitation.</p>}
      <form onSubmit={onSubmit} noValidate className="form">
        <FormError message={error} />
        <TextField label="Email" type="email" name="email" autoComplete="email" required value={email} onChange={(e) => setEmail(e.target.value)} />
        <TextField
          label="Password"
          type="password"
          name="password"
          autoComplete="current-password"
          required
          value={password}
          onChange={(e) => setPassword(e.target.value)}
        />
        <Button type="submit" busy={busy} className="btn-block">
          Log in
        </Button>
      </form>
    </AuthCard>
  );
}
