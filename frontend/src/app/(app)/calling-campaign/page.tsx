'use client';
import { useEffect, useRef, useState } from 'react';
import { api, errorMessage } from '@/lib/api';
import { orgPath } from '@/lib/agents';
import { useSession } from '@/lib/session';
import { PageHeader } from '@/components/PageHeader';

type Lead = {row:number;name:string;phone:string;state:string;status:string;eligible:boolean;detail:string};
type Call = {id:number;name:string;phone:string;state:string;status?:string;dry_run:boolean;filename:string;summary?:string;transcript?:string;duration?:number};
type Campaign = {mode:string;stopped:boolean;queue:null|{id:string;filename:string;total:number;ready:number;counts:Record<string,number>;next:Lead|null;leads:Lead[]};agents:{id:string;name:string}[];batch:null|{active:boolean;dialled:number;requested:number;note?:string;agent_name?:string};calls:Call[]};
const labels:Record<string,string>={waiting:'Not called',calling:'Awaiting result',completed:'Call ended',failed:'Failed / no result',test:'Test only',unavailable:'Needs review'};
export default function CallingCampaignPage(){
 const {activeMembership}=useSession();
 const orgId=activeMembership?.organization.id;
 const base=orgId?orgPath(orgId,'/calling-campaign'):'';
 const [data,setData]=useState<Campaign|null>(null),[file,setFile]=useState<File|null>(null),[agent,setAgent]=useState(''),[message,setMessage]=useState(''),[busy,setBusy]=useState(false),[filter,setFilter]=useState('all'),[page,setPage]=useState(0);
 const [uploadError,setUploadError]=useState('');
 const input=useRef<HTMLInputElement>(null);
 async function load(){if(!base)return;const next=await api.get<Campaign>(base);setData(next);setAgent(a=>a||next.agents[0]?.id||'');}
 useEffect(()=>{let disposed=false;let timer:ReturnType<typeof setTimeout>;async function poll(){try{await load();}catch(e){if(!disposed)setMessage(errorMessage(e));}finally{if(!disposed)timer=setTimeout(poll,5000);}}poll();return()=>{disposed=true;clearTimeout(timer);};},[base]);
 async function act(fn:()=>Promise<string>){setBusy(true);setMessage('');try{setMessage(await fn());await load();}catch(e){setMessage(errorMessage(e));}finally{setBusy(false);}}
 const q=data?.queue;
 const current=data?.calls.find(c=>c.state==='calling');
 const locked=!!current||!!data?.batch?.active;
 const leads=(q?.leads??[]).filter(l=>filter==='all'||l.state===filter);
 if(!orgId)return null;
 return <div className="campaign-ui">
 <PageHeader title="Calling campaigns" description="Choose your Excel or CSV file, check the queue, then start calls one at a time."/>
 <section className={`campaign-live ${current?'is-active':''}`} aria-live="polite">
 <span className="campaign-badge">{data?.mode==='test'?'TEST MODE · no real calls':'LIVE MODE'}</span>
 <h2>{current?(current.dry_run?'Test simulation · no real phone call':'Call requested / result pending'):data?.batch?.active?'Queue running': 'No call in progress'}</h2>
 {current?<p className="campaign-person">{current.name} <span>{current.phone}</span></p>:<p>{q?.next?`Next ready: ${q.next.name} · ${q.next.phone}`:'No leads are ready to call.'}</p>}
 <p>{current?'A provider result is needed to confirm connection and finish this call.':data?.stopped?'Queue is stopped. Start resumes calling for the file shown below.':'Calls only begin after you start the uploaded queue.'}</p>
 {locked&&<button className="button secondary" disabled={busy} onClick={()=>act(async()=>{await api.post(`${base}/stop`);return 'Queue stopped. Any live call must finish before changing files.';})}>Stop next calls</button>}
 </section>
 {message&&<div className="campaign-feedback" role="status">{message}</div>}
 <section className="campaign-panel">
 <div className="campaign-section-title"><div><span className="campaign-step">1 · FILE</span><h2>{q?.filename||'Upload your Excel or CSV file'}</h2><p>{q?`${q.total} leads in this uploaded file`:'No file uploaded yet'}</p></div>{q&&<button className="button secondary" disabled={busy||locked} onClick={()=>act(async()=>{await api.delete(`${base}/upload`);setFile(null);if(input.current)input.current.value='';return 'File removed. Call history is retained.';})}>Remove file</button>}</div>
 <div className="campaign-actions"><label className="file-control">Choose Excel / CSV (.xlsx, .csv)<input ref={input} type="file" accept=".xlsx,.csv" disabled={busy||locked} onChange={e=>{setFile(e.target.files?.[0]??null);setUploadError('');}}/></label><button className="button" disabled={!file||busy||locked} onClick={()=>act(async()=>{setUploadError(''); let r:{accepted:number;rejected:number}; try{r=await api.upload<{accepted:number;rejected:number}>(`${base}/upload`,file!);}catch(e){setUploadError(errorMessage(e));throw e;}setFile(null);setPage(0);setFilter('all');if(input.current)input.current.value='';return `File uploaded: ${r.accepted} valid leads, ${r.rejected} rejected rows. Review the queue below.`;})}>{q?'Replace file':'Upload file'}</button><button className="button secondary" disabled={busy} onClick={()=>act(async()=>{await api.download(`${base}/sample.xlsx`,'didm-leads-sample.xlsx');return 'Sample downloaded.';})}>Download template</button></div>
 {uploadError&&<div className="campaign-warning" role="alert"><strong>File was not replaced:</strong> {uploadError}<p>The previous file is still active. Fix the error and upload again.</p></div>}
 {file&&<div className="campaign-warning"><strong>{file.name} is selected but NOT uploaded.</strong> Click Replace/Upload file first. Calling is disabled until then.</div>}
 {locked&&<p>Stop the queue and wait for the current result before replacing or removing the file.</p>}
 </section>
 {q&&<>
 <div className="campaign-stats">{Object.entries(labels).map(([key,label])=><button key={key} className={`campaign-stat ${filter===key?'selected':''}`} onClick={()=>{setFilter(key);setPage(0);}}><strong>{q.counts[key]??0}</strong><span>{label}</span></button>)}</div>
 <section className="campaign-panel"><span className="campaign-step">2 · START QUEUE</span><div className="campaign-actions"><label className="file-control">Calling agent<select value={agent} onChange={e=>setAgent(e.target.value)} disabled={busy||locked}><option value="">Choose agent</option>{data?.agents.map(a=><option key={a.id} value={a.id}>{a.name}</option>)}</select></label><button className="button" disabled={busy||locked||!!file||!agent||!q.ready} onClick={()=>act(async()=>{const r=await api.post<{dialled_now:number;dry_run:boolean}>(`${base}/start`,{agent_id:agent,upload_id:q.id,count:q.ready});return r.dialled_now? r.dry_run?'Test simulation started. No real phone call was placed.':'First call requested. Watch the live status above.':'No call was placed. Review the queue status.';})}>{data?.mode==='test'?`Simulate ${q.ready} ready leads`:`Start ${q.ready} ready leads`}</button></div><p>File: <strong>{q.filename}</strong> · One call at a time · {q.ready} ready now</p>{!q.ready&&<div className="campaign-warning">Nothing is ready to call. Check the lead statuses below, or replace the file with a new list. Previous test calls are not real calls.</div>}{data?.batch&&<p>Latest batch: {data.batch.agent_name} · {data.batch.dialled} attempts requested / {data.batch.requested} planned · {data.batch.active?'Running':data.batch.note==='no more leads to call'?'No eligible leads — queue ended':data.batch.note||'Finished'}</p>}</section>
 <section className="campaign-panel"><div className="campaign-section-title"><h2>Leads in current file</h2><label>Show <select value={filter} onChange={e=>{setFilter(e.target.value);setPage(0);}}><option value="all">All leads ({q.total})</option>{Object.entries(labels).map(([key,label])=><option key={key} value={key}>{label}</option>)}</select></label></div><div className="table-wrap"><table><thead><tr><th>Lead</th><th>Phone</th><th>Call status</th><th>Details</th></tr></thead><tbody>{leads.slice(page*50,page*50+50).map(l=><tr key={l.row}><td>{l.name}</td><td className="campaign-phone">{l.phone}</td><td><span className={`campaign-status status-${l.state}`}>{l.status}</span></td><td>{l.detail||'—'}</td></tr>)}{!leads.length&&<tr><td colSpan={4}>No leads in this status.</td></tr>}</tbody></table></div>{leads.length>50&&<div className="campaign-actions"><button className="button secondary" disabled={!page} onClick={()=>setPage(p=>p-1)}>Previous</button><span>Page {page+1} of {Math.ceil(leads.length/50)}</span><button className="button secondary" disabled={(page+1)*50>=leads.length} onClick={()=>setPage(p=>p+1)}>Next</button></div>}</section>
 </>}
 <details className="campaign-panel"><summary>Previous calls & transcripts ({data?.calls.length??0} latest)</summary><p>Test records are labelled explicitly. A requested call is not confirmed connected until a result arrives.</p><div className="table-wrap"><table><thead><tr><th>Lead / file</th><th>Phone</th><th>Result</th><th>Summary</th><th>Transcript</th></tr></thead><tbody>{data?.calls.map(c=><tr key={c.id}><td><strong>{c.name}</strong><br/><small>{c.filename}</small></td><td className="campaign-phone">{c.phone}</td><td>{c.dry_run?'Test only · no real call':c.state==='calling'?'Requested · awaiting result':c.state==='done'?c.status||'Ended':c.state==='start_failed'?'Could not start':c.state==='stuck'?'Result missing':c.state}</td><td>{c.summary||'—'}</td><td>{c.transcript?<details><summary>Read transcript</summary><pre className="transcript">{c.transcript}</pre></details>:c.dry_run?'Not available for test call':c.state==='calling'?'Awaiting call result':'Not received'}</td></tr>)}</tbody></table></div></details>
 </div>;
}
