'use client';

import Link from 'next/link';
import { useEffect, useState } from 'react';
import { api, errorMessage } from '@/lib/api';
import { orgPath } from '@/lib/agents';
import { useSession } from '@/lib/session';
import { PageHeader } from '@/components/PageHeader';
import { Spinner } from '@/components/Spinner';
import { CampaignRecording } from '@/components/CampaignRecording';

type Turn = { role: string; text: string };
type Call = { id:number; name:string; phone:string; agent_name:string; attempt_id:string;
  started_at:string; duration:number|null; status:string; state:string; dry_run:boolean;
  campaign_id:string|null; failure_reason:string|null; has_interaction:boolean;
  variables:Record<string,unknown>; transcript:{original?:Turn[];english?:Turn[]} };
type History = { configured:boolean; total:number; items:Call[];
  agents:{id:string;name:string;active:boolean;last_synced_at:string|null;error:string|null;catching_up:boolean}[] };

function Transcript({call}:{call:Call}) {
  const [language,setLanguage]=useState('original');
  const original=call.transcript.original||[], english=call.transcript.english||[];
  const turns=language==='original'?(original.length?original:english):(english.length?english:original);
  if(!turns.length)return <span>{!call.has_interaction?'No conversation received':call.state==='calling'?'Available after the call ends':'Transcript pending from Sarvam · retries automatically'}</span>;
  function download(){
    const url=URL.createObjectURL(new Blob([turns.map(t=>`${t.role}: ${t.text}`).join('\n\n')],{type:'text/plain;charset=utf-8'}));
    const a=document.createElement('a');a.href=url;a.download=`call-${call.id}-transcript.txt`;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
  }
  return <details><summary>Read transcript ({turns.length} turns)</summary>
    <label>Language <select value={language} onChange={e=>setLanguage(e.target.value)}>
      <option value="original">Original conversation</option><option value="english">English translation</option>
    </select></label>
    <pre className="transcript">{turns.map(t=>`${t.role==='agent'||t.role==='assistant'?'Agent':'Caller'}: ${t.text}`).join('\n\n')}</pre>
    <button className="button secondary" onClick={download}>Download transcript</button>
  </details>;
}

export default function OutboundCallsPage(){
  const {activeMembership}=useSession();
  const orgId=activeMembership?.organization.id;
  const base=orgId?orgPath(orgId,'/outbound-calls'):'';
  const [data,setData]=useState<History|null>(null),[error,setError]=useState(''),[busy,setBusy]=useState(false);
  const [agent,setAgent]=useState(''),[status,setStatus]=useState(''),[search,setSearch]=useState(''),[q,setQ]=useState(''),[page,setPage]=useState(0);
  const [message,setMessage]=useState('');
  useEffect(()=>{setData(null);setAgent('');setStatus('');setQ('');setSearch('');setPage(0);setMessage('');setError('');},[base]);
  useEffect(()=>{
    if(!base)return;
    let disposed=false;let timer:ReturnType<typeof setTimeout>;const controller=new AbortController();
    async function load(){
      try{
        const params=new URLSearchParams({agent_id:agent,status,q,offset:String(page*25),limit:'25'});
        const result=await api.get<History>(`${base}?${params}`,{signal:controller.signal});
        if(!disposed){setData(result);setError('');}
      }catch(e){if(!disposed)setError(errorMessage(e));}
      if(!disposed)timer=setTimeout(load,10000);
    }
    setData(null);load();return()=>{disposed=true;controller.abort();clearTimeout(timer);};
  },[base,agent,status,q,page]);
  async function sync(){
    const syncBase=base;setBusy(true);setMessage('');
    try{await api.post(`${syncBase}/sync`);setMessage('Sync requested. Results refresh automatically; Sarvam data can take a minute to appear.');}
    catch(e){setMessage(errorMessage(e));}finally{setBusy(false);}
  }
  if(!orgId)return null;
  return <div className="campaign-ui" key={base}>
    <PageHeader title="Outbound calls" description="Call history from your linked Sarvam phone agents, including calls started directly in Sarvam."/>
    <div className="campaign-actions"><button className="button" disabled={busy||!data?.configured} onClick={sync}>{busy?<Spinner label="Syncing Sarvam calls…"/>:'Sync Sarvam calls'}</button><Link className="button secondary" href="/calling-campaign/">Start a calling campaign</Link></div>
    <p>New results sync every minute. The first sync imports the previous 30 days. Transcripts are saved here; audio is fetched from Sarvam when you press play or download.</p>
    {message&&<div className="campaign-feedback" role="status">{message}</div>}
    {error&&<div className="campaign-warning" role="alert">{error}</div>}
    {data&&!data.configured&&<div className="campaign-warning">Sarvam connection is not configured on the backend. Set SARVAM_API_KEY, SARVAM_ORG_ID and SARVAM_WORKSPACE_ID to enable call sync.</div>}
    {data?.agents.length===0&&<div className="campaign-warning">No phone agents are linked to this organization. <Link href="/agents/">Register your Sarvam agent</Link> with its app ID and enable the phone channel.</div>}
    {data?.agents.filter(a=>a.error||a.catching_up).map(a=><p className="campaign-warning" key={a.id}>{a.name}: {a.error?`Sync delayed (${a.error}). Check the Sarvam connection; automatic retries are enabled.`:'Importing older calls… more results will appear automatically.'}</p>)}
    <section className="campaign-panel">
      <form className="campaign-actions" onSubmit={e=>{e.preventDefault();setQ(search.trim());setPage(0);}}>
        <label className="file-control">Agent<select value={agent} onChange={e=>{setAgent(e.target.value);setPage(0);}}><option value="">All agents</option>{data?.agents.map(a=><option key={a.id} value={a.id}>{a.name}{a.active?'':' (archived)'}</option>)}</select></label>
        <label className="file-control">Result<select value={status} onChange={e=>{setStatus(e.target.value);setPage(0);}}><option value="">All results</option>{['connected','no_answer','busy','failed','unknown'].map(s=><option key={s} value={s}>{s.replaceAll('_',' ')}</option>)}</select></label>
        <label className="file-control">Phone or attempt ID<input value={search} onChange={e=>setSearch(e.target.value)} placeholder="Search calls" maxLength={200}/></label>
        <button className="button secondary" type="submit">Search</button>
      </form>
      {!data&&!error&&<Spinner label="Loading outbound calls…"/>}
      {data&&<><p>{data.total} calls match your filters · History updates automatically</p>
      <div className="table-wrap"><table><thead><tr><th>Phone / agent</th><th>Time / duration</th><th>Result</th><th>Collected details</th><th>Transcript</th><th>Recording</th></tr></thead>
      <tbody>{data.items.map(c=><tr key={`${base}:${c.id}`}><td><strong>{c.phone||'Number unavailable'}</strong><br/>{c.agent_name}<details><summary>Call IDs</summary><small>Attempt: {c.attempt_id}<br/>Campaign: {c.campaign_id||'Direct outbound'}</small></details></td>
        <td>{new Date(c.started_at).toLocaleString()}<br/>{c.duration===null?'Duration pending':`${c.duration} seconds`}</td>
        <td>{c.status.replaceAll('_',' ')}{c.state==='calling'&&<p>Completion pending</p>}{c.failure_reason&&<p>{c.failure_reason}</p>}</td>
        <td>{Object.keys(c.variables||{}).length?<details><summary>View details</summary><pre className="transcript">{JSON.stringify(c.variables,null,2)}</pre></details>:'—'}</td>
        <td><Transcript call={c}/></td><td>{c.has_interaction?<CampaignRecording base={base} call={c} callerLabel="Caller"/>:'No conversation recording'}</td>
      </tr>)}{!data.items.length&&<tr><td colSpan={6}>{q||agent||status?'No calls match these filters.':'No outbound calls imported yet. Link your phone agent and click Sync Sarvam calls.'}</td></tr>}</tbody></table></div>
      <div className="campaign-actions"><button className="button secondary" disabled={page===0} onClick={()=>setPage(p=>p-1)}>Previous</button><span>Page {page+1} of {Math.max(1,Math.ceil(data.total/25))}</span><button className="button secondary" disabled={(page+1)*25>=data.total} onClick={()=>setPage(p=>p+1)}>Next</button></div>
      {data.agents.filter(a=>a.last_synced_at).map(a=><small key={a.id} style={{display:'block'}}>{a.name} · Last full sync {new Date(a.last_synced_at!).toLocaleString()}</small>)}
      </>}
    </section>
  </div>;
}
