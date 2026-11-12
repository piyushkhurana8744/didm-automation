'use client';

import { useEffect, useState } from 'react';
import { api, errorMessage } from '@/lib/api';
import { orgPath } from '@/lib/agents';
import { useSession } from '@/lib/session';
import { PageHeader } from '@/components/PageHeader';

type Call = { id:number; name:string; phone:string; state:string; status?:string; outcome?:string; duration?:number; summary?:string; transcript?:string };
type Campaign = { mode:'test'|'live'; agents:{id:string;name:string;app_id:string;app_version:number}[]; batch: null | { id:number; requested:number;dialled:number;active:boolean;note?:string;agent_name?:string }; calls: Call[] };

export default function CallingCampaignPage() {
  const { activeMembership } = useSession();
  const orgId = activeMembership?.organization.id;
  const [data, setData] = useState<Campaign | null>(null);
  const [file, setFile] = useState<File | null>(null);
  const [count, setCount] = useState(10);
  const [agentId, setAgentId] = useState('');
  const [message, setMessage] = useState('');
  const [busy, setBusy] = useState(false);
  const base = orgId ? orgPath(orgId, '/calling-campaign') : '';

  async function load() { if (base) { const next=await api.get<Campaign>(base); setData(next); setAgentId(current=>current||next.agents[0]?.id||''); } }
  useEffect(() => { load().catch((e) => setMessage(errorMessage(e))); const timer=setInterval(()=>load().catch(()=>{}),10000); return ()=>clearInterval(timer); }, [base]);
  async function act(fn:()=>Promise<unknown>, ok:string) { setBusy(true); setMessage(''); try { await fn(); setMessage(ok); await load(); } catch(e) { setMessage(errorMessage(e)); } finally { setBusy(false); } }

  if (!orgId) return null;
  return <>
    <PageHeader title="Calling campaigns" description="Upload an Excel lead list. Calls run one-by-one and transcripts appear here automatically." />
    {data?.mode==='test'&&<div className="campaign-warning" role="alert"><strong>TEST MODE:</strong> Queue aur results simulate honge; real phone calls nahi jayengi. Server par DRY_RUN=false configure karein.</div>}
    <section className="campaign-panel">
      <div className="campaign-actions">
        <button className="button secondary" onClick={()=>act(()=>api.download(`${base}/sample.xlsx`,'didm-leads-sample.xlsx'),'Sample downloaded.')}>Download sample Excel</button>
        <label className="file-control">Lead Excel (.xlsx)<input type="file" accept=".xlsx" onChange={e=>setFile(e.target.files?.[0] ?? null)} /></label>
        <button className="button" disabled={!file||busy} onClick={()=>act(()=>api.upload(`${base}/upload`,file!), 'Excel uploaded. Queue is ready.')}>Upload queue</button>
      </div>
      <div className="campaign-actions">
        <label className="file-control">Calling agent<select value={agentId} onChange={e=>setAgentId(e.target.value)}><option value="">Select agent</option>{(data?.agents??[]).map(a=><option key={a.id} value={a.id}>{a.name} · Sarvam v{a.app_version}</option>)}</select></label>
        <label>Calls in batch <input className="small-input" type="number" min="1" max="5000" value={count} onChange={e=>setCount(Number(e.target.value))}/></label>
        <button className="button" disabled={busy||!agentId} onClick={()=>act(()=>api.post(`${base}/start`,{count,agent_id:agentId}),'Calling started.')}>Start calling</button>
        <button className="button secondary" disabled={busy} onClick={()=>act(()=>api.post(`${base}/stop`),'Calling stopped.')}>Stop</button>
        <button className="button secondary" disabled={busy} onClick={()=>act(()=>api.post(`${base}/resume`),'Calling enabled.')}>Resume</button>
      </div>
      {message && <p className="campaign-message" role="status">{message}</p>}
      {data?.agents.length===0&&<p className="campaign-message">No published phone agent found. Publish an agent with the Phone channel first.</p>}
      {data?.batch && <p>Batch #{data.batch.id} · {data.batch.agent_name||'Default agent'}: {data.batch.dialled}/{data.batch.requested} dialled — {data.batch.active?'running':data.batch.note||'finished'}</p>}
    </section>
    <h2>Latest calls</h2>
    <div className="table-wrap"><table><thead><tr><th>Name</th><th>Phone</th><th>Status</th><th>Outcome</th><th>Duration</th><th>Summary</th><th>Transcript</th></tr></thead><tbody>
      {(data?.calls??[]).map(c=><tr key={c.id}><td>{c.name}</td><td>{c.phone}</td><td>{c.status||c.state}</td><td>{c.outcome||'—'}</td><td>{c.duration?`${c.duration}s`:'—'}</td><td>{c.summary||'—'}</td><td>{c.transcript?<details><summary>View</summary><pre className="transcript">{c.transcript}</pre></details>:'Waiting'}</td></tr>)}
      {data?.calls.length===0&&<tr><td colSpan={7}>No calls yet. Upload an Excel file to begin.</td></tr>}
    </tbody></table></div>
  </>;
}
