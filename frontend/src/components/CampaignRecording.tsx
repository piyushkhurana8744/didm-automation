'use client';

import { useEffect, useRef, useState } from 'react';
import { Spinner } from './Spinner';
import { api, errorMessage } from '@/lib/api';

export function CampaignRecording({ base, call, callerLabel = 'Student' }: {
  base: string;
  callerLabel?: string;
  call: { id: number; name: string; dry_run: boolean; state: string };
}) {
  const [channel, setChannel] = useState('both');
  const [loadedChannel, setLoadedChannel] = useState('both');
  const [url, setUrl] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const objectUrl = useRef('');
  const mounted = useRef(true);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      if (objectUrl.current) URL.revokeObjectURL(objectUrl.current);
    };
  }, []);

  if (call.dry_run) return <span>Test call · no recording</span>;
  if (call.state === 'calling') return <span>Available after the call ends</span>;
  if (call.state === 'start_failed') return <span>Call did not start</span>;

  async function load() {
    setBusy(true);
    setError('');
    try {
      const audio = await api.blob(`${base}/calls/${call.id}/recording?channel=${channel}`);
      if (!mounted.current) return;
      if (objectUrl.current) URL.revokeObjectURL(objectUrl.current);
      objectUrl.current = URL.createObjectURL(audio);
      setUrl(objectUrl.current);
      setLoadedChannel(channel);
    } catch (e) {
      if (mounted.current) setError(errorMessage(e));
    } finally {
      if (mounted.current) setBusy(false);
    }
  }

  return <div>
    <label>Listen to <select value={channel} disabled={busy} onChange={e=>{setChannel(e.target.value);setError('');}}>
      <option value="both">Both voices</option><option value="student">{callerLabel} only</option>
      <option value="agent">Agent only</option><option value="original">Original stereo</option>
    </select></label>
    {url && loadedChannel===channel ? <>
      <audio controls preload="metadata" onError={()=>setError('Recording could not be played. Try downloading it.')} src={url} aria-label={`Call recording for ${call.name}`} />
      <a href={url} download={`call-${call.id}-${loadedChannel}.wav`}>Download recording</a>
    </> : <button className="button secondary" disabled={busy} onClick={load}>
      {busy ? <Spinner label="Fetching recording…"/> : error ? 'Retry recording' : 'Load / download audio'}
    </button>}
    <small>Both voices plays the two channels together. {callerLabel} only isolates the caller channel; it cannot recover speech missing from the source.</small>
    {error && <p role="status">{error}</p>}
  </div>;
}
