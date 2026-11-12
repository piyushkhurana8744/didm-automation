'use client';

import { useEffect, useState } from 'react';
import { api, errorMessage } from '@/lib/api';
import { orgPath } from '@/lib/agents';
import { useSession } from '@/lib/session';
import { PageHeader } from '@/components/PageHeader';

type Call = { id:number; name:string; phone:string; state:string; status?:string; outcome?:string; duration?:number; summary?:string; transcript?:string };
type Campaign = { batch: null | { id:number; requested:number; dialled:number; active:boolean; note?:string }; calls: Call[] };

export default function CallingCampaignPage() {
  const { activeMembership } = useSession();
  const orgId = activeMembership?.organization.id;
  const [data, setData] = useState<Campaign | null>(null);
  const [file, setFile] = useState<File | null>(null);
  const [count, setCount] = useState(10);
  const [message, setMessage] = useState('');
  const [busy, setBusy] = useState(false);
  const base = orgId ? orgPath(orgId, '/calling-campaign') : '';

  async function load() { if (base) setData(await api.get<Campaign>(base)); }
  useEffect(() => { load().catch((e) => setMessage(errorMessage(e))); const timer=setInterval(()=>load().catch(()=>{}),10000); return ()=>clearInterval(timer); }, [base]);
  async function act(fn:()=>Promise<unknown>, ok:string) { setBusy(true); setMessage(''); try { await fn(); setMessage(ok); await load(); } catch(e) { setMessage(errorMessage(e)); } finally { setBusy(false); } }

  if (!orgId) return null;
  return <>
    <PageHeader title="Calling campaigns" description="Upload an Excel lead list. Calls run one-by-one and transcripts appear here automatically." />
    <section className="campaign-panel">
      <div className="campaign-actions">
        <button className="button secondary" onClick={()=>act(()=>api.download(`${base}/sample.xlsx`,'didm-leads-sample.xlsx'),'Sample downloaded.')}>Download sample Excel</button>
        <label className="file-control">Lead Excel (.xlsx)<input type="file" accept=".xlsx" onChange={e=>setFile(e.target.files?.[0] ?? null)} /></label>
        <button className="button" disabled={!file||busy} onClick={()=>act(()=>api.upload(`${base}/upload`,file!), 'Excel uploaded. Queue is ready.')}>Upload queue</button>
      </div>
      <div className="campaign-actions">
        <label>Calls in batch <input className="small-input" type="number" min="1" max="5000" value={count} onChange={e=>setCount(Number(e.target.value))}/></label>
        <button className="button" disabled={busy} onClick={()=>act(()=>api.post(`${base}/start`,{count}),'Calling started.')}>Start calling</button>
        <button className="button secondary" disabled={busy} onClick={()=>act(()=>api.post(`${base}/stop`),'Calling stopped.')}>Stop</button>
        <button className="button secondary" disabled={busy} onClick={()=>act(()=>api.post(`${base}/resume`),'Calling enabled.')}>Resume</button>
      </div>
      {message && <p className="campaign-message" role="status">{message}</p>}
      {data?.batch && <p>Batch #{data.batch.id}: {data.batch.dialled}/{data.batch.requested} dialled — {data.batch.active?'running':data.batch.note||'finished'}</p>}
    </section>
    <h2>Latest calls</h2>
    <div className="table-wrap"><table><thead><tr><th>Name</th><th>Phone</th><th>Status</th><th>Outcome</th><th>Duration</th><th>Summary</th><th>Transcript</th></tr></thead><tbody>
      {(data?.calls??[]).map(c=><tr key={c.id}><td>{c.name}</td><td>{c.phone}</td><td>{c.status||c.state}</td><td>{c.outcome||'—'}</td><td>{c.duration?`${c.duration}s`:'—'}</td><td>{c.summary||'—'}</td><td>{c.transcript?<details><summary>View</summary><pre className="transcript">{c.transcript}</pre></details>:'Waiting'}</td></tr>)}
      {data?.calls.length===0&&<tr><td colSpan={7}>No calls yet. Upload an Excel file to begin.</td></tr>}
    </tbody></table></div>
  </>;
}
