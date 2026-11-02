'use client';

import Link from 'next/link';
import { useEffect, useState, type FormEvent } from 'react';
import { api, errorMessage } from '@/lib/api';
import { clearHash, readHashToken } from '@/lib/secrets';
import { AuthCard } from '@/components/AuthCard';
import { Button } from '@/components/Button';
import { FormError, FormSuccess, TextField } from '@/components/Field';
import { Spinner } from '@/components/Spinner';

const MIN_PASSWORD = 10;

export default function ResetPasswordPage() {
  // undefined = not read yet (first render happens before we can see the hash)
  const [token, setToken] = useState<string | null | undefined>(undefined);
  const [password, setPassword] = useState('');
  const [confirm, setConfirm] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState(false);

  useEffect(() => {
    const read = () => setToken(readHashToken());
    read();
    window.addEventListener('hashchange', read);
    return () => window.removeEventListener('hashchange', read);
  }, []);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    if (password.length < MIN_PASSWORD) return setError(`Use at least ${MIN_PASSWORD} characters.`);
    if (password !== confirm) return setError('The two passwords do not match.');
    if (!token) return;
    setBusy(true);
    try {
      await api.post('/auth/password/reset', { token, new_password: password }, { redirectOn401: false });
      clearHash();
      setPassword('');
      setConfirm('');
      setDone(true);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <AuthCard title="Choose a new password" footer={<Link href="/login/">Back to log in</Link>}>
      {token === undefined ? (
        <Spinner label="Reading your link" />
      ) : token === null ? (
        <div className="alert alert-error" role="alert">
          This reset link is incomplete. Open the link from your email again, or <Link href="/forgot-password/">ask for a new one</Link>.
        </div>
      ) : done ? (
        <>
          <FormSuccess message="Your password has been changed. You have been logged out everywhere." />
          <p>
            <Link href="/login/" className="btn btn-primary">
              Log in
            </Link>
          </p>
        </>
      ) : (
        <form onSubmit={onSubmit} noValidate className="form">
          <FormError message={error} />
          <TextField
            label="New password"
            type="password"
            autoComplete="new-password"
            required
            minLength={MIN_PASSWORD}
            hint={`At least ${MIN_PASSWORD} characters.`}
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
          <TextField label="Confirm new password" type="password" autoComplete="new-password" required value={confirm} onChange={(e) => setConfirm(e.target.value)} />
          <Button type="submit" busy={busy} className="btn-block">
            Change password
          </Button>
        </form>
      )}
    </AuthCard>
  );
}
