'use client';

import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { useEffect, useState, type FormEvent } from 'react';
import { api, errorMessage, isApiError } from '@/lib/api';
import { formatDateTime } from '@/lib/format';
import { roleLabel } from '@/lib/roles';
import { clearStashedInviteToken, readHashToken, setHashToken, stashInviteToken, takeStashedInviteToken } from '@/lib/secrets';
import type { AcceptResponse, InvitationLookup, Me } from '@/lib/types';
import { AuthCard } from '@/components/AuthCard';
import { Button } from '@/components/Button';
import { FormError, TextField } from '@/components/Field';
import { Spinner } from '@/components/Spinner';

const MIN_PASSWORD = 10;

type Phase =
  | { kind: 'loading' }
  | { kind: 'no-token' }
  | { kind: 'invalid'; message: string }
  | { kind: 'ready'; invite: InvitationLookup; me: Me | null };

export default function AcceptInvitationPage() {
  const router = useRouter();
  const [token, setToken] = useState<string | null>(null);
  const [phase, setPhase] = useState<Phase>({ kind: 'loading' });
  const [name, setName] = useState('');
  const [password, setPassword] = useState('');
  const [confirm, setConfirm] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    // A different link opened in this same tab only changes the hash: start over with it.
    const onHash = () => window.location.reload();
    window.addEventListener('hashchange', onHash);
    let t = readHashToken();
    if (t) {
      clearStashedInviteToken();
    } else {
      // Coming back from "Log in to accept": take the token out of sessionStorage and put it back in the hash
      t = takeStashedInviteToken();
      if (t) setHashToken(t);
    }
    if (!t) {
      setPhase({ kind: 'no-token' });
      return () => window.removeEventListener('hashchange', onHash);
    }
    setToken(t);
    (async () => {
      try {
        const invite = await api.post<InvitationLookup>('/invitations/lookup', { token: t }, { redirectOn401: false });
        let me: Me | null = null;
        try {
          me = await api.get<Me>('/auth/me', { redirectOn401: false });
        } catch (e) {
          if (!(isApiError(e) && e.status === 401)) throw e;
        }
        if (live) setPhase({ kind: 'ready', invite, me });
      } catch (e) {
        if (live) setPhase({ kind: 'invalid', message: errorMessage(e) });
      }
    })();
    return () => {
      live = false;
      window.removeEventListener('hashchange', onHash);
    };
  }, []);

  function goToLogin() {
    if (token) stashInviteToken(token);
    router.push('/login/');
  }

  async function logOutThen(next: 'login' | 'stay') {
    setBusy(true);
    setError(null);
    try {
      await api.post('/auth/logout', {}, { redirectOn401: false });
    } catch {
      /* already logged out is fine */
    }
    setBusy(false);
    if (next === 'login') goToLogin();
    else if (phase.kind === 'ready') setPhase({ ...phase, me: null });
  }

  async function accept(body: { name?: string; password?: string }) {
    if (!token) return;
    setBusy(true);
    setError(null);
    try {
      await api.post<AcceptResponse>('/invitations/accept', { token, ...body }, { redirectOn401: false });
      setPassword('');
      setConfirm('');
      router.replace('/dashboard/');
    } catch (e) {
      setBusy(false);
      if (isApiError(e) && e.status === 401) {
        setError(e.detail);
      } else {
        setError(errorMessage(e));
      }
    }
  }

  function onCreate(e: FormEvent) {
    e.preventDefault();
    setError(null);
    if (!name.trim()) return setError('Enter your name.');
    if (password.length < MIN_PASSWORD) return setError(`Use at least ${MIN_PASSWORD} characters for your password.`);
    if (password !== confirm) return setError('The two passwords do not match.');
    void accept({ name: name.trim(), password });
  }

  if (phase.kind === 'loading') {
    return (
      <AuthCard title="Invitation">
        <Spinner label="Checking your invitation" />
      </AuthCard>
    );
  }

  if (phase.kind === 'no-token' || phase.kind === 'invalid') {
    return (
      <AuthCard title="Invitation" footer={<Link href="/login/">Go to log in</Link>}>
        <div className="alert alert-error" role="alert">
          {phase.kind === 'no-token'
            ? 'This invitation link is incomplete. Open the link you were sent again.'
            : phase.message}
        </div>
        <p>If the link has expired, ask the person who invited you to send a new one.</p>
      </AuthCard>
    );
  }

  const { invite, me } = phase;
  const loggedInAs = me?.user.email ?? null;
  const sameAccount = !!loggedInAs && loggedInAs.toLowerCase() === invite.email.toLowerCase();

  return (
    <AuthCard title={`Join ${invite.organization.name}`}>
      <dl className="facts">
        <div>
          <dt>Organization</dt>
          <dd>{invite.organization.name}</dd>
        </div>
        <div>
          <dt>Invited email</dt>
          <dd className="break">{invite.email}</dd>
        </div>
        <div>
          <dt>Role</dt>
          <dd>{roleLabel(invite.role)}</dd>
        </div>
        <div>
          <dt>Link expires</dt>
          <dd>{formatDateTime(invite.expires_at)}</dd>
        </div>
      </dl>

      <FormError message={error} />

      {invite.has_account ? (
        sameAccount ? (
          <Button busy={busy} className="btn-block" onClick={() => void accept({})}>
            Accept invitation
          </Button>
        ) : loggedInAs ? (
          <>
            <p>
              You are logged in as <strong className="break">{loggedInAs}</strong>. This invitation is for{' '}
              <strong className="break">{invite.email}</strong>.
            </p>
            <Button busy={busy} className="btn-block" onClick={() => void logOutThen('login')}>
              Log out and log in as {invite.email}
            </Button>
          </>
        ) : (
          <>
            <p>
              <strong className="break">{invite.email}</strong> already has an account. Log in with it to accept.
            </p>
            <Button className="btn-block" onClick={goToLogin}>
              Log in to accept
            </Button>
          </>
        )
      ) : loggedInAs ? (
        <>
          <p>
            You are logged in as <strong className="break">{loggedInAs}</strong>. To create an account for{' '}
            <strong className="break">{invite.email}</strong>, log out first.
          </p>
          <Button busy={busy} variant="secondary" className="btn-block" onClick={() => void logOutThen('stay')}>
            Log out
          </Button>
        </>
      ) : (
        <form onSubmit={onCreate} noValidate className="form">
          <p>Create your account to join.</p>
          <TextField label="Your name" autoComplete="name" required value={name} onChange={(e) => setName(e.target.value)} maxLength={200} />
          <TextField
            label="Password"
            type="password"
            autoComplete="new-password"
            required
            minLength={MIN_PASSWORD}
            hint={`At least ${MIN_PASSWORD} characters.`}
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
          <TextField label="Confirm password" type="password" autoComplete="new-password" required value={confirm} onChange={(e) => setConfirm(e.target.value)} />
          <Button type="submit" busy={busy} className="btn-block">
            Create account and join
          </Button>
        </form>
      )}
    </AuthCard>
  );
}
