'use client';

import { useState, type FormEvent } from 'react';
import { api, errorCode, errorMessage } from '@/lib/api';
import { orgPath } from '@/lib/agents';
import { useSession } from '@/lib/session';
import { shortPhone } from '@/lib/training';
import type { TrainingAvailability } from '@/lib/types';
import { useLoad } from '@/lib/useLoad';
import { Button } from '@/components/Button';
import { FormError, FormSuccess, ReadOnlyField, TextField } from '@/components/Field';
import { PageHeader } from '@/components/PageHeader';

const MIN_PASSWORD = 10;

function NameForm() {
  const { me, refresh } = useSession();
  const [name, setName] = useState(me.user.name);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState<string | null>(null);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setSaved(null);
    if (!name.trim()) return setError('Enter your name.');
    setBusy(true);
    try {
      await api.patch('/auth/me', { name: name.trim() });
      await refresh();
      setSaved('Your name was saved.');
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="panel" aria-labelledby="profile-title">
      <h2 id="profile-title" className="panel-title">
        Your details
      </h2>
      <form onSubmit={onSubmit} noValidate className="form">
        <FormError message={error} />
        <FormSuccess message={saved} />
        <ReadOnlyField label="Email" value={<span className="break">{me.user.email}</span>} />
        <TextField label="Name" autoComplete="name" required maxLength={200} value={name} onChange={(e) => setName(e.target.value)} />
        <div>
          <Button type="submit" busy={busy} disabled={name.trim() === me.user.name}>
            Save name
          </Button>
        </div>
      </form>
    </section>
  );
}

/** Mirrors the backend: 10 digits, or with a leading 0 or 91 (spaces and dashes are ignored). */
function looksLikeIndianMobile(value: string): boolean {
  const d = value.replace(/\D/g, '');
  return d.length === 10 || (d.length === 11 && d.startsWith('0')) || (d.length === 12 && d.startsWith('91'));
}

/** Lets the person verify their own number with a code by message, when the platform can send one. */
function PhoneCode({ orgId, onVerified }: { orgId: string; onVerified: () => void }) {
  const [sent, setSent] = useState(false);
  const [code, setCode] = useState('');
  const [busy, setBusy] = useState<'send' | 'verify' | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [info, setInfo] = useState<string | null>(null);
  const [unavailable, setUnavailable] = useState(false);

  async function send() {
    setBusy('send');
    setError(null);
    setInfo(null);
    try {
      const res = await api.post<{ sent: boolean; expires_in_seconds: number }>(orgPath(orgId, '/me/phone/verification-code'));
      setSent(true);
      setCode('');
      setInfo(`We sent a code to your number. It works for ${Math.round(res.expires_in_seconds / 60)} minutes.`);
    } catch (err) {
      if (errorCode(err) === 'otp_unavailable') {
        setUnavailable(true);
        setInfo(errorMessage(err));
      } else {
        setError(errorMessage(err));
      }
    } finally {
      setBusy(null);
    }
  }

  async function verify(e: FormEvent) {
    e.preventDefault();
    const c = code.trim();
    if (!/^\d{4,10}$/.test(c)) return setError('Enter the code from the message.');
    setBusy('verify');
    setError(null);
    try {
      await api.post(orgPath(orgId, '/me/phone/verify'), { code: c });
      setSent(false);
      setInfo(null);
      onVerified();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="inline-form">
      <FormError message={error} />
      {info && (
        <div className={unavailable ? 'alert alert-info' : 'alert alert-success'} role="status">
          {info}
        </div>
      )}
      {sent ? (
        <form onSubmit={verify} noValidate className="form-inline">
          <TextField
            label="Code"
            inputMode="numeric"
            autoComplete="one-time-code"
            maxLength={10}
            value={code}
            onChange={(e) => setCode(e.target.value)}
          />
          <div className="row">
            <Button type="submit" busy={busy === 'verify'} disabled={busy !== null}>
              Verify number
            </Button>
            <Button variant="ghost" busy={busy === 'send'} disabled={busy !== null} onClick={() => void send()}>
              Send a new code
            </Button>
          </div>
        </form>
      ) : (
        !unavailable && (
          <div>
            <Button variant="secondary" busy={busy === 'send'} disabled={busy !== null} onClick={() => void send()}>
              Send me a code
            </Button>
          </div>
        )
      )}
    </div>
  );
}

function PhoneForm() {
  const { activeMembership } = useSession();
  const orgId = activeMembership && activeMembership.permissions.includes('training.self') ? activeMembership.organization.id : null;
  // The saved number is only readable (masked) through an organization's training availability.
  const availability = useLoad(orgId ? () => api.get<TrainingAvailability>(orgPath(orgId, '/training/availability')) : null, orgId);
  const [savedMasked, setSavedMasked] = useState<string | null | undefined>(undefined);
  const [phone, setPhone] = useState('');
  const [busy, setBusy] = useState<'save' | 'clear' | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState<string | null>(null);

  const current = savedMasked !== undefined ? savedMasked : availability.data?.phone.phone_on_file ?? null;
  const known = savedMasked !== undefined || !!availability.data;
  const verified = savedMasked === undefined && !!availability.data?.phone.phone_verified;

  async function save(value: string, kind: 'save' | 'clear') {
    setError(null);
    setSaved(null);
    setBusy(kind);
    try {
      const res = await api.put<{ phone: string | null }>('/auth/me/phone', { phone: value });
      setSavedMasked(res.phone);
      setPhone('');
      setSaved(
        res.phone
          ? `Saved. Ask an admin in your organization to verify the number ending ${shortPhone(res.phone)} before you practise by phone.`
          : 'Your phone number was removed.',
      );
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(null);
    }
  }

  function onSubmit(e: FormEvent) {
    e.preventDefault();
    const v = phone.trim();
    if (!v) return setError('Enter your mobile number.');
    if (!looksLikeIndianMobile(v)) return setError('Enter a 10-digit Indian mobile number.');
    void save(v, 'save');
  }

  return (
    <section className="panel" aria-labelledby="phone-title">
      <h2 id="phone-title" className="panel-title">
        Phone number for practice calls
      </h2>
      <p className="muted">
        Voice agents call this number when you start a phone practice session. After you save or change it, an admin in your organization must
        verify it before calls can be placed.
      </p>
      <form onSubmit={onSubmit} noValidate className="form">
        <FormError message={error} />
        <FormSuccess message={saved} />
        <ReadOnlyField
          label="Saved number"
          value={
            !known ? (
              availability.loading ? (
                'Checking…'
              ) : (
                <span className="muted">Choose an organization to see your saved number.</span>
              )
            ) : current ? (
              <>
                <span className="mono">{shortPhone(current)}</span>{' '}
                {savedMasked === undefined && (
                  <span className={verified ? 'badge badge-ok' : 'badge badge-warn'}>{verified ? 'Verified' : 'Waiting for an admin to verify'}</span>
                )}
              </>
            ) : (
              <span className="muted">None saved</span>
            )
          }
        />
        <TextField
          label={current ? 'New mobile number' : 'Mobile number'}
          type="tel"
          inputMode="tel"
          autoComplete="tel-national"
          maxLength={20}
          hint="A 10-digit Indian mobile number, like 98765 43210."
          value={phone}
          onChange={(e) => setPhone(e.target.value)}
        />
        <div className="row">
          <Button type="submit" busy={busy === 'save'} disabled={busy !== null}>
            Save number
          </Button>
          {current && (
            <Button variant="secondary" busy={busy === 'clear'} disabled={busy !== null} onClick={() => void save('', 'clear')}>
              Remove number
            </Button>
          )}
        </div>
      </form>
      {orgId && current && !verified && (
        <>
          <h3>Verify it yourself</h3>
          <p className="small muted">If your organization can send codes by message, you can verify the number without waiting for an admin.</p>
          <PhoneCode
            key={current}
            orgId={orgId}
            onVerified={() => {
              setSavedMasked(undefined);
              setError(null);
              setSaved('Your number is verified. You can now practise by phone.');
              availability.reload();
            }}
          />
        </>
      )}
    </section>
  );
}

function PasswordForm() {
  const [current, setCurrent] = useState('');
  const [next, setNext] = useState('');
  const [confirm, setConfirm] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState<string | null>(null);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setSaved(null);
    if (!current) return setError('Enter your current password.');
    if (next.length < MIN_PASSWORD) return setError(`Use at least ${MIN_PASSWORD} characters for the new password.`);
    if (next !== confirm) return setError('The two new passwords do not match.');
    setBusy(true);
    try {
      await api.post('/auth/password/change', { current_password: current, new_password: next });
      setCurrent('');
      setNext('');
      setConfirm('');
      setSaved('Password changed. Your other sessions were logged out.');
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="panel" aria-labelledby="password-title">
      <h2 id="password-title" className="panel-title">
        Change password
      </h2>
      <form onSubmit={onSubmit} noValidate className="form">
        <FormError message={error} />
        <FormSuccess message={saved} />
        <TextField label="Current password" type="password" autoComplete="current-password" required value={current} onChange={(e) => setCurrent(e.target.value)} />
        <TextField
          label="New password"
          type="password"
          autoComplete="new-password"
          required
          minLength={MIN_PASSWORD}
          hint={`At least ${MIN_PASSWORD} characters.`}
          value={next}
          onChange={(e) => setNext(e.target.value)}
        />
        <TextField label="Confirm new password" type="password" autoComplete="new-password" required value={confirm} onChange={(e) => setConfirm(e.target.value)} />
        <div>
          <Button type="submit" busy={busy}>
            Change password
          </Button>
        </div>
      </form>
    </section>
  );
}

export default function ProfilePage() {
  return (
    <>
      <PageHeader title="Profile" />
      <NameForm />
      <PhoneForm />
      <PasswordForm />
    </>
  );
}
