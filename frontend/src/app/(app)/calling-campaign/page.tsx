'use client';
import { useEffect, useRef, useState } from 'react';
import Link from 'next/link';
import { api, errorMessage } from '@/lib/api';
import { orgPath } from '@/lib/agents';
import { useSession } from '@/lib/session';
import { PageHeader } from '@/components/PageHeader';
import { Spinner, SkeletonRows } from '@/components/Spinner';
import { CampaignRecording } from '@/components/CampaignRecording';

type Lead = {row:number;name:string;phone:string;state:string;status:string;eligible:boolean;detail:string};
type Call = {current_upload:boolean;request_accepted:boolean;started_at:string;batch_id:number;id:number;name:string;phone:string;state:string;status?:string;dry_run:boolean;filename:string;summary?:string;transcript?:string;duration?:number};
type Campaign = {mode:string;stopped:boolean;queue:null|{id:string;filename:string;total:number;ready:number;counts:Record<string,number>;next:Lead|null;leads:Lead[]};agents:{id:string;name:string}[];batch:null|{active:boolean;dialled:number;requested:number;note?:string;agent_name?:string;parallel_calls?:number};calls:Call[]};
const labels:Record<string,string>={waiting:'Not called',calling:'Awaiting result',completed:'Call ended',failed:'Failed / no result',test:'Test only',unavailable:'Needs review'};
export default function CallingCampaignPage(){
 const {activeMembership}=useSession();
 const orgId=activeMembership?.organization.id;
 const base=orgId?orgPath(orgId,'/calling-campaign'):'';
 const [data,setData]=useState<Campaign|null>(null),[file,setFile]=useState<File|null>(null),[agent,setAgent]=useState(''),[message,setMessage]=useState(''),[busy,setBusy]=useState(false),[filter,setFilter]=useState('all'),[page,setPage]=useState(0);
 const [uploadError,setUploadError]=useState('');
 const [mode,setMode]=useState('');
 const [parallel,setParallel]=useState(1),[batchSize,setBatchSize]=useState('10');
 const [action,setAction]=useState('');
 const [loading,setLoading]=useState(true),[refreshing,setRefreshing]=useState(false),[loadError,setLoadError]=useState(''),[updated,setUpdated]=useState('');
 const input=useRef<HTMLInputElement>(null);
 const generation=useRef(0),requestId=useRef(0),latest=useRef<Campaign|null>(null);
 async function load(signal?:AbortSignal){
  if(!base)return;
  const g=generation.current,id=++requestId.current;
  setRefreshing(true);
  try{
   const next=await api.get<Campaign>(base,{signal});
   if(g!==generation.current||id!==requestId.current)return;
   latest.current=next;setData(next);setLoadError('');setUpdated(new Date().toLocaleTimeString());
   setAgent(a=>next.agents.some(item=>item.id===a)?a:next.agents[0]?.id||'');
  }catch(e){if(g===generation.current&&id===requestId.current&&!signal?.aborted)setLoadError(errorMessage(e));}
  finally{if(g===generation.current&&id===requestId.current){setLoading(false);setRefreshing(false);}}
 }
 useEffect(()=>{
  generation.current++;setData(null);latest.current=null;setLoading(true);setLoadError('');setMode('');setParallel(1);setBatchSize('10');setAgent('');setFile(null);setMessage('');setUploadError('');setUpdated('');
  let disposed=false;let timer:ReturnType<typeof setTimeout>;const controller=new AbortController();
  async function poll(){await load(controller.signal);if(!disposed)timer=setTimeout(poll,latest.current?.calls.some(c=>c.state==='calling')?2000:5000);}
  poll();return()=>{disposed=true;generation.current++;controller.abort();clearTimeout(timer);};
 },[base]);
 async function act(label:string,fn:()=>Promise<string>){
  const g=generation.current;setBusy(true);setAction(label);setMessage('');
  try{const result=await fn();if(g===generation.current){setMessage(result);await load();}}
  catch(e){if(g===generation.current)setMessage(errorMessage(e));}
  finally{setBusy(false);setAction('');}
 }
 function actionLabel(label:string,text:string){return action===label?<><Spinner inline label={label}/>{label}</>:text;}
 const q=data?.queue;
 const selectedMode=mode||data?.mode||'test';
 const activeCalls=data?.calls.filter(c=>c.state==='calling')??[];
 const current=activeCalls[0];
 const count=Math.min(Number(batchSize),q?.ready??0);
 const validCount=Number.isInteger(count)&&count>0;
 const locked=!!current||!!data?.batch?.active;
 const leads=(q?.leads??[]).filter(l=>filter==='all'||l.state===filter);
 if(!orgId)return null;
 if(!data)return <div className="campaign-ui"><PageHeader title="Calling campaigns" description="Upload leads, make calls and review results."/>
 {loading?<><Spinner label="Loading queue, agents and call history…"/><SkeletonRows rows={4}/></>:<div className="campaign-warning" role="alert">{loadError||'Campaign status could not be loaded.'}<button className="button" disabled={refreshing} onClick={()=>load()}>{refreshing?<Spinner label="Retrying…"/>:'Try again'}</button></div>}</div>;
 return <div className="campaign-ui">
 <PageHeader title="Calling campaigns" description="Choose your Excel or CSV file, check the queue, choose a batch size and how many calls to run together."/>
 <p>For all calls from your linked Sarvam agents, including calls started directly in Sarvam, open <Link href="/outbound-calls/">Outbound calls · transcripts &amp; recordings</Link>.</p>
 <div className="campaign-sync" role="status">{refreshing?<><Spinner inline/>Updating results…</>:updated?`Last updated ${updated}`:''}<button className="button secondary" disabled={refreshing||busy} onClick={()=>load()}>Refresh results</button></div>
 {loadError&&<div className="campaign-warning" role="alert">{loadError} Showing the last received data; retrying automatically.</div>}
 {busy&&<div className="campaign-feedback" role="status"><Spinner label={action}/></div>}
 <section className={`campaign-live ${current?'is-active':''}`} aria-live="polite">
 <span className="campaign-badge">{!data?'STATUS UNAVAILABLE':current?(current.dry_run?'TEST MODE · no real calls':'LIVE CALL'):selectedMode==='test'?'TEST MODE · no real calls':'LIVE MODE · real phone calls'}</span>
 <h2>{!data?'Campaign status could not be loaded':current?(current.dry_run?'Test simulation · no real phone call':`${activeCalls.length} calls requested / results pending`):data?.batch?.active?'Queue running': 'No call in progress'}</h2>
 {current?<div>{activeCalls.map(c=><p key={c.id} className="campaign-person">{c.name} <span>{c.phone}</span></p>)}</div>:<p>{!data?'Queue and call mode will appear once the server responds.':q?.next?`Next ready: ${q.next.name} · ${q.next.phone}`:'No leads are ready to call.'}</p>}
 <p>{current?'Waiting for Sarvam to confirm the call result. Results refresh automatically; you can leave this page open.':data?.stopped?'Queue is stopped. Start resumes calling for the file shown below.':'Calls only begin after you start the uploaded queue.'}</p>
 {current&&<Spinner label="Awaiting call result…"/>}
 {locked&&<button className="button secondary" disabled={busy} onClick={()=>act('Stopping queue…',async()=>{await api.post(`${base}/stop`);return 'Queue stopped. All active calls must finish before changing files.';})}>{actionLabel('Stopping queue…','Stop next calls')}</button>}
 </section>
 {message&&<div className="campaign-feedback" role="status">{message}</div>}
 <section className="campaign-panel">
 <div className="campaign-section-title"><div><span className="campaign-step">1 · FILE</span><h2>{!data?'Queue status unavailable':q?.filename||'Upload your Excel or CSV file'}</h2><p>{!data?'Waiting for the server to load the current file.':q?`${q.total} leads in this uploaded file`:'No file uploaded yet'}</p></div>{q&&<button className="button secondary" disabled={busy||locked} onClick={()=>act('Removing file…',async()=>{await api.delete(`${base}/upload`);setFile(null);if(input.current)input.current.value='';return 'File removed. Call history is retained.';})}>{actionLabel('Removing file…','Remove file')}</button>}</div>
 <div className="campaign-actions"><label className="file-control">Choose Excel / CSV (.xlsx, .csv)<input ref={input} type="file" accept=".xlsx,.csv" disabled={busy||locked} onChange={e=>{setFile(e.target.files?.[0]??null);setUploadError('');}}/></label><button className="button" disabled={!data||!file||busy||locked} onClick={()=>act('Uploading and validating leads…',async()=>{setUploadError(''); let r:{accepted:number;rejected:number}; try{r=await api.upload<{accepted:number;rejected:number}>(`${base}/upload`,file!);}catch(e){setUploadError(errorMessage(e));throw e;}setFile(null);setPage(0);setFilter('all');if(input.current)input.current.value='';return `File uploaded: ${r.accepted} valid leads, ${r.rejected} rejected rows. Review the queue below.`;})}>{actionLabel('Uploading and validating leads…',q?'Replace file':'Upload file')}</button><button className="button secondary" disabled={busy} onClick={()=>act('Downloading template…',async()=>{await api.download(`${base}/sample.xlsx`,'didm-leads-sample.xlsx');return 'Sample downloaded.';})}>{actionLabel('Downloading template…','Download template')}</button></div>
 {uploadError&&<div className="campaign-warning" role="alert"><strong>Upload failed:</strong> {uploadError}<p>{q?'The previous file is still active. Fix the error and upload again.':'The file was not uploaded. Fix the error and try again.'}</p></div>}
 {file&&<div className="campaign-warning"><strong>{file.name} is selected but NOT uploaded.</strong> Click Replace/Upload file first. Calling is disabled until then.</div>}
 {locked&&<p>Stop the queue and wait for all active results before replacing or removing the file.</p>}
 </section>
 {q&&<>
 <div className="campaign-stats">{Object.entries(labels).map(([key,label])=><button key={key} className={`campaign-stat ${filter===key?'selected':''}`} onClick={()=>{setFilter(key);setPage(0);}}><strong>{q.counts[key]??0}</strong><span>{label}</span></button>)}</div>
 <section className="campaign-panel"><span className="campaign-step">2 · START QUEUE</span><div className="campaign-actions"><label className="file-control">Call mode<select value={selectedMode} onChange={e=>setMode(e.target.value)} disabled={busy||locked}><option value="test">Test · no real phone calls</option><option value="live">Live · call these leads</option></select></label><label className="file-control">Leads in this batch<input type="number" min={1} max={q.ready||1} value={batchSize} disabled={busy||locked} onChange={e=>setBatchSize(e.target.value)}/></label><label className="file-control">Calls at the same time<select value={parallel} disabled={busy||locked} onChange={e=>setParallel(Number(e.target.value))}>{[1,2,3,5,10].map(n=><option key={n} value={n}>{n===1?'1 · one at a time':`${n} simultaneous calls`}</option>)}</select></label><label className="file-control">Calling agent<select value={agent} onChange={e=>setAgent(e.target.value)} disabled={busy||locked}><option value="">Choose agent</option>{data?.agents.map(a=><option key={a.id} value={a.id}>{a.name}</option>)}</select></label><button className="button" disabled={busy||locked||!!file||!agent||!q.ready||!validCount} onClick={()=>act('Starting calls…',async()=>{const r=await api.post<{dialled_now:number;dry_run:boolean}>(`${base}/start`,{agent_id:agent,upload_id:q.id,count,parallel_calls:Math.min(parallel,count),mode:selectedMode});return r.dialled_now? r.dry_run?'Test simulation completed. Leads remain ready for live calls.':`${r.dialled_now} attempts processed. Watch the active calls and results above.`:'No call was placed. Review the queue status.';})}>{actionLabel('Starting calls…',selectedMode==='test'?`Simulate ${validCount?count:0} leads`:`Call ${validCount?count:0} leads`)}</button></div><p>File: <strong>{q.filename}</strong> · Up to {Math.min(parallel,validCount?count:parallel)} calls at the same time · {q.ready} ready now</p>{!q.ready&&<div className="campaign-warning">Nothing is ready to call. Check the lead statuses below, or replace the file with a new list. Previous test calls are not real calls.</div>}{data?.batch&&<p>Latest batch: {data.batch.agent_name} · {data.batch.parallel_calls||1} simultaneous calls · {data.batch.dialled} attempts requested / {data.batch.requested} planned · {data.batch.active?'Running':data.batch.note==='no more leads to call'?'No eligible leads — queue ended':data.batch.note||'Finished'}</p>}</section>
 <section className="campaign-panel"><div className="campaign-section-title"><h2>Leads in current file</h2><label>Show <select value={filter} onChange={e=>{setFilter(e.target.value);setPage(0);}}><option value="all">All leads ({q.total})</option>{Object.entries(labels).map(([key,label])=><option key={key} value={key}>{label}</option>)}</select></label></div><div className="table-wrap"><table><thead><tr><th>Lead</th><th>Phone</th><th>Call status</th><th>Details</th></tr></thead><tbody>{leads.slice(page*50,page*50+50).map(l=><tr key={l.row}><td>{l.name}</td><td className="campaign-phone">{l.phone}</td><td><span className={`campaign-status status-${l.state}`}>{l.status}</span></td><td>{l.detail||'—'}</td></tr>)}{!leads.length&&<tr><td colSpan={4}>No leads in this status.</td></tr>}</tbody></table></div>{leads.length>50&&<div className="campaign-actions"><button className="button secondary" disabled={!page} onClick={()=>setPage(p=>p-1)}>Previous</button><span>Page {page+1} of {Math.ceil(leads.length/50)}</span><button className="button secondary" disabled={(page+1)*50>=leads.length} onClick={()=>setPage(p=>p+1)}>Next</button></div>}</section>
 </>}
 <details className="campaign-panel" open><summary>Previous calls, transcripts & recordings ({data?.calls.length??0} latest)</summary><p>Test records are labelled explicitly. A requested call is not confirmed connected until a result arrives.</p><div className="table-wrap"><table><thead><tr><th>Lead / file</th><th>Phone</th><th>Result</th><th>Summary</th><th>Transcript</th><th>Recording</th></tr></thead><tbody>{data?.calls.map(c=><tr key={c.id}><td><strong>{c.name}</strong><br/><small>{c.filename}<br/>{c.current_upload?'Current upload':'Earlier upload'} · Batch #{c.batch_id}<br/>{new Date(c.started_at).toLocaleString()}</small></td><td className="campaign-phone">{c.phone}</td><td>{c.dry_run?'Test only · no real call':c.state==='calling'?(c.request_accepted?'Request accepted · ringing not confirmed':'Sending request · ringing not confirmed'):c.state==='done'?(c.status==='busy'?'Provider reported busy · not connected':c.status||'Ended'):c.state==='start_failed'?'Could not start':c.state==='stuck'?'Result missing':c.state}</td><td>{c.summary||'—'}</td><td>{c.transcript?<details><summary>Read transcript</summary><pre className="transcript">{c.transcript}</pre></details>:c.dry_run?'Not available for test call':c.state==='calling'?<Spinner label="Awaiting call result…"/>:c.status==='connected'?<span>Transcript pending from Sarvam · updates automatically</span>:'Not received'}</td><td><CampaignRecording key={`${base}:${c.id}`} base={base} call={c}/></td></tr>)}</tbody></table></div></details>
 </div>;
}
