'use client';

import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { useRef, useState, useEffect, type FormEvent, type ReactNode } from 'react';
import { api, errorCode, errorMessage, isApiError } from '@/lib/api';
import { CHANNEL_LABELS, DIFFICULTY_LABELS, orgPath } from '@/lib/agents';
import { newRequestId, shortPhone } from '@/lib/training';
import type { MyAgentDetail, StartedSession, TrainingAvailability } from '@/lib/types';
import { useLoad } from '@/lib/useLoad';
import { useSession } from '@/lib/session';
import { Button } from '../Button';
import { ErrorState } from '../ErrorState';
import { CheckboxField, SelectField, TextField } from '../Field';
import { SkeletonRows } from '../Spinner';

interface ChannelState {
  usable: boolean;
  note: ReactNode;
}

function phoneState(a: TrainingAvailability): ChannelState {
  if (!a.enabled) return { usable: false, note: 'Training is not switched on for your organization yet.' };
  if (!a.phone.available) return { usable: false, note: 'Phone practice is not available right now.' };
  if (!a.phone.phone_on_file) {
    return {
      usable: false,
      note: (
        <>
          Add your mobile number on your <Link href="/profile/">profile</Link>. An admin then verifies it before the agent can call you.
        </>
      ),
    };
  }
  if (!a.phone.phone_verified) {
    return {
      usable: false,
      note: (
        <>
          Your number ending {shortPhone(a.phone.phone_on_file)} is waiting for an admin to verify it. You can change it on your{' '}
          <Link href="/profile/">profile</Link>.
        </>
      ),
    };
  }
  return {
    usable: true,
    note: `The agent calls your number ending ${shortPhone(a.phone.phone_on_file)}. Sessions last up to ${a.max_session_minutes} minutes.`,
  };
}

function parseExtraParams(input: string): Record<string, string> {
  const trimmed = input.trim();
  if (!trimmed) return {};
  if (trimmed.startsWith('{') && trimmed.endsWith('}')) {
    try {
      const parsed = JSON.parse(trimmed);
      if (typeof parsed === 'object' && parsed !== null) {
        return Object.fromEntries(Object.entries(parsed).map(([k, v]) => [String(k), String(v)]));
      }
    } catch {
      // fallback
    }
  }
  const result: Record<string, string> = {};
  for (const line of trimmed.split('\n')) {
    const idx = line.indexOf('=');
    if (idx > 0) {
      const k = line.slice(0, idx).trim();
      const v = line.slice(idx + 1).trim();
      if (k) result[k] = v;
    }
  }
  return result;
}

/** Scenario picker, honest channel states and the "Start phone practice" button for one assigned agent. */
export function StartPractice({ orgId, agent }: { orgId: string; agent: MyAgentDetail }) {
  const router = useRouter();
  const { me } = useSession();
  const availability = useLoad(() => api.get<TrainingAvailability>(orgPath(orgId, '/training/availability')), orgId);
  const [scenarioId, setScenarioId] = useState(agent.scenarios[0]?.id ?? '');
  const [leadName, setLeadName] = useState(me?.user?.name || '');
  const [extraParams, setExtraParams] = useState('');
  const [saveSuccess, setSaveSuccess] = useState(false);

  useEffect(() => {
    try {
      const savedLead = localStorage.getItem(`didm_lead_name_${agent.id}`) || localStorage.getItem('didm_lead_name');
      const savedExtra = localStorage.getItem(`didm_extra_params_${agent.id}`);
      if (savedLead) setLeadName(savedLead);
      else if (me?.user?.name) setLeadName(me.user.name);
      if (savedExtra) setExtraParams(savedExtra);
    } catch {
      if (me?.user?.name) setLeadName(me.user.name);
    }
  }, [agent.id, me?.user?.name]);

  function saveDefaults() {
    try {
      if (leadName.trim()) {
        localStorage.setItem(`didm_lead_name_${agent.id}`, leadName.trim());
        localStorage.setItem('didm_lead_name', leadName.trim());
      }
      if (extraParams.trim()) {
        localStorage.setItem(`didm_extra_params_${agent.id}`, extraParams.trim());
      } else {
        localStorage.removeItem(`didm_extra_params_${agent.id}`);
      }
      setSaveSuccess(true);
      setTimeout(() => setSaveSuccess(false), 3000);
    } catch {
      // ignore
    }
  }

  function resetToProfile() {
    const profileName = me?.user?.name || '';
    setLeadName(profileName);
    setExtraParams('');
    try {
      localStorage.removeItem(`didm_lead_name_${agent.id}`);
      localStorage.removeItem(`didm_extra_params_${agent.id}`);
    } catch {
      // ignore
    }
  }

  // Recording needs the trainee's say-so every time: the box starts unticked.
  const [recordConsent, setRecordConsent] = useState(false);
  // The practice call notice must be accepted before every call; the box starts unticked too.
  const [noticeAccepted, setNoticeAccepted] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<{ message: string; code: string | null } | null>(null);
  // One id per start attempt: kept across a retry after a dropped connection so the server replays
  // the same session instead of placing a second call.
  const requestId = useRef<string | null>(null);

  if (availability.loading && !availability.data) return <SkeletonRows rows={2} label="Checking which practice options are available" />;
  if (availability.error && !availability.data) return <ErrorState error={availability.error} onRetry={availability.reload} />;
  const a = availability.data;
  if (!a) return null;

  const offersPhone = agent.channels.includes('phone');
  const offersBrowser = agent.channels.includes('browser');
  const phone = offersPhone ? phoneState(a) : null;
  const notice = a.practice_notice?.version ? a.practice_notice : null;
  const canStart = !!phone?.usable && (agent.scenarios.length === 0 || !!scenarioId) && (!notice || noticeAccepted);
  const recording = a.recording?.available && a.recording.consent_version ? a.recording : null;

  async function onStart(e: FormEvent) {
    e.preventDefault();
    if (busy || !canStart) return;
    saveDefaults();
    setError(null);
    setBusy(true);
    requestId.current ??= newRequestId();
    try {
      const parsedExtra = parseExtraParams(extraParams);
      const started = await api.post<StartedSession>(orgPath(orgId, '/training/sessions'), {
        agent_id: agent.id,
        channel: 'phone',
        scenario_id: scenarioId || null,
        lead_name: leadName.trim() || undefined,
        custom_variables: Object.keys(parsedExtra).length > 0 ? parsedExtra : undefined,
        client_request_id: requestId.current,
        ...(notice ? { practice_notice_version: notice.version } : {}),
        ...(recording && recordConsent ? { recording_consent_version: recording.consent_version } : {}),
      });
      requestId.current = null;
      router.push(`/my-training/session/?id=${encodeURIComponent(started.id)}`);
    } catch (err) {
      // A network failure may have reached the server: keep the id so a retry is not a second call.
      if (!(isApiError(err) && err.status === 0)) requestId.current = null;
      const code = errorCode(err);
      if (code === 'notice_not_accepted') {
        // The notice may have changed since the page loaded: show the current one and ask again.
        setNoticeAccepted(false);
        setError({
          message: 'The practice call notice has changed or was not accepted. Read the notice below, tick the box and start again.',
          code,
        });
        availability.reload();
      } else {
        setError({ message: errorMessage(err), code });
        if (code === 'phone_not_verified') availability.reload();
      }
      setBusy(false);
    }
  }

  return (
    <>
      <ul className="channel-tiles" aria-label="Practice channels">
        {offersPhone && phone && (
          <li className={phone.usable ? 'channel-tile channel-tile-live' : 'channel-tile'} aria-disabled={phone.usable ? undefined : 'true'}>
            <span className="channel-tile-name">{CHANNEL_LABELS.phone}</span>
            <span className={phone.usable ? 'badge badge-ok' : 'badge'}>{phone.usable ? 'Available' : 'Unavailable'}</span>
            <span className="small">{phone.note}</span>
          </li>
        )}
        {offersBrowser && (
          <li className="channel-tile" aria-disabled="true">
            <span className="channel-tile-name">{CHANNEL_LABELS.browser}</span>
            <span className="badge">Unavailable</span>
            <span className="small muted">{a.browser.reason ?? 'Browser practice is not available in this app yet.'}</span>
          </li>
        )}
        {!offersPhone && !offersBrowser && <li className="muted">This agent has no practice channels set up.</li>}
      </ul>
      {!offersPhone && (offersBrowser || agent.channels.length > 0) && (
        <p className="small muted">This agent does not offer phone practice.</p>
      )}

      {offersPhone && (
        <form className="start-form" onSubmit={onStart} noValidate>
          <TextField
            label="Lead Name (Call Greeting Name)"
            value={leadName}
            onChange={(e) => setLeadName(e.target.value)}
            placeholder="e.g. Piyush / Rahul Sharma"
            hint="Agent will call you and address you by this name (passed as lead_name parameter)."
          />
          {agent.scenarios.length > 0 && (
            <SelectField
              label="Scenario"
              options={agent.scenarios.map((s) => ({ value: s.id, label: `${s.name} (${DIFFICULTY_LABELS[s.difficulty] ?? s.difficulty})` }))}
              value={scenarioId}
              onChange={(e) => setScenarioId(e.target.value)}
              hint="The situation the agent will play out with you."
            />
          )}
          <details className="consent" style={{ cursor: 'pointer', padding: '0.5rem 0.75rem' }}>
            <summary className="small muted">Additional custom parameters (optional)</summary>
            <div style={{ marginTop: '0.75rem' }}>
              <TextField
                label="Extra parameters (key=value, or JSON)"
                value={extraParams}
                onChange={(e) => setExtraParams(e.target.value)}
                placeholder="city=Delhi"
                hint="Pass any extra custom variables to Sarvam agent (e.g. city=Delhi, course=Digital Marketing)."
              />
            </div>
          </details>
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', marginTop: '0.25rem', marginBottom: '1rem' }}>
            <button
              type="button"
              className="button button-secondary button-small"
              onClick={saveDefaults}
            >
              Save as default
            </button>
            <button
              type="button"
              className="button button-text button-small"
              onClick={resetToProfile}
              style={{ color: '#888', background: 'none', border: 'none', cursor: 'pointer', fontSize: '0.85rem' }}
            >
              Reset to profile
            </button>
            {saveSuccess && (
              <span className="badge badge-ok" style={{ fontSize: '0.8rem' }}>
                Saved ✓
              </span>
            )}
          </div>
          {notice && (
            <div className="consent">
              <p className="small consent-text pre-line">{notice.text}</p>
              <CheckboxField
                label="I have read this notice and want to start the practice call"
                checked={noticeAccepted}
                required
                onChange={(e) => setNoticeAccepted(e.target.checked)}
                hint="Required before every practice call."
              />
            </div>
          )}
          {recording && (
            <div className="consent">
              <p className="small consent-text">{recording.consent_text}</p>
              <CheckboxField
                label="I agree to this session being recorded"
                checked={recordConsent}
                onChange={(e) => setRecordConsent(e.target.checked)}
                hint={`Optional. Recordings are kept for ${recording.retention_days} days. If you leave this unticked, the session is not recorded.`}
              />
            </div>
          )}
          {error && (
            <div className="alert alert-error" role="alert">
              {error.message}
              {error.code === 'phone_not_verified' && (
                <>
                  {' '}
                  <Link href="/profile/">Go to your profile</Link>
                </>
              )}
            </div>
          )}
          <div>
            <Button type="submit" busy={busy} disabled={!canStart}>
              Start phone practice
            </Button>
          </div>
          {!phone?.usable && <p className="small muted">Phone practice can start once the issue above is sorted out.</p>}
          {phone?.usable && notice && !noticeAccepted && <p className="small muted">Tick the box under the practice call notice to start.</p>}
        </form>
      )}
    </>
  );
}
