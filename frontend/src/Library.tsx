import {useEffect,useRef,useState,type FormEvent} from 'react';
import {request} from './api';
import {number,type Analysis,type AnalysisList} from './types';

const STEPS=[
  {key:'video',label:'Check video',stages:['queued','video']},
  {key:'collect',label:'Collect comments',stages:['collect']},
  {key:'filter',label:'Find viewpoints',stages:['context','filter']},
  {key:'group',label:'Discover perspectives',stages:['group']},
  {key:'agents',label:'Build agents',stages:['agents']},
  {key:'presentation',label:'Prepare your workspace',stages:['presentation','ready']},
];
const busy=(a:Analysis)=>a.status==='queued'||a.status==='running';

function Progress({analysis,onOpen,onRetry,pending}:{analysis:Analysis;onOpen:(id:string)=>void;onRetry:(id:string)=>void;pending:boolean}){
  const failed=analysis.status==='failed'||analysis.status==='interrupted';
  const current=STEPS.findIndex(s=>s.stages.includes(analysis.stage));
  return <section className={`analysis-progress ${failed?'has-error':''}`} aria-label="Video analysis progress">
    <div className="progress-heading"><div><p className="eyebrow">{analysis.status==='ready'?'READY TO EXPLORE':failed?'SAVED FOR RETRY':'YOUR VIDEO'}</p><h2>{analysis.title}</h2></div>{busy(analysis)&&<span className="spinner" aria-hidden="true"/>}</div>
    <p className="progress-detail" role={failed?'alert':'status'}>{analysis.error||analysis.detail}</p>
    <ol className="analysis-steps" aria-label="Analysis steps">{STEPS.map((s,i)=>{const done=analysis.status==='ready'||i<current;return <li key={s.key} className={done?'done':i===current?'current':''} aria-current={i===current?'step':undefined}><span aria-hidden="true">{done?'✓':i+1}</span>{s.label}</li>;})}</ol>
    <div className="progress-facts"><span><strong>{number(analysis.collected_count)}</strong> comments collected{analysis.max_comments?` · up to ${number(analysis.max_comments)}`:''}</span>{analysis.retained_count!==undefined&&<span><strong>{number(analysis.retained_count)}</strong> with viewpoints</span>}{analysis.agent_count>0&&<span><strong>{analysis.agent_count}</strong> perspective agents</span>}</div>
    {busy(analysis)&&<p className="progress-footnote">You can explore the example while this runs. Your progress is saved. Return to this page to check it.</p>}
    {analysis.status==='ready'&&<button className="primary" onClick={()=>onOpen(analysis.analysis_id)}>Explore this video</button>}
    {failed&&<button className="secondary" disabled={pending} onClick={()=>onRetry(analysis.analysis_id)}>{pending?'Resuming…':'Resume analysis'}</button>}
  </section>;
}

export default function Library({onOpen}:{onOpen:(id:string)=>void}){
  const [data,setData]=useState<AnalysisList|null>(null),[error,setError]=useState(''),[loadAttempt,setLoadAttempt]=useState(0);
  const [url,setUrl]=useState(''),[limit,setLimit]=useState(500),[replies,setReplies]=useState(true),[fresh,setFresh]=useState(false);
  const [pending,setPending]=useState(false),[monitored,setMonitored]=useState<string|null>(null);
  const submitting=useRef(false);
  useEffect(()=>{const controller=new AbortController();request<AnalysisList>('/analyses',undefined,'GET',controller.signal).then(value=>{
    setData(value);setError('');const saved=localStorage.getItem('review:analysis-job');
    setMonitored(value.analyses.find(a=>a.analysis_id===saved)?.analysis_id||value.analyses.find(busy)?.analysis_id||null);
  }).catch(e=>{if(e.name!=='AbortError')setError(e.message);});return()=>controller.abort();},[loadAttempt]);
  const running=data?.analyses.some(busy);
  useEffect(()=>{if(!running)return;let alive=true;let controller:AbortController|null=null;let fetching=false;
    const timer=window.setInterval(()=>{if(fetching)return;fetching=true;controller=new AbortController();request<AnalysisList>('/analyses',undefined,'GET',controller.signal).then(value=>{if(alive){setData(value);setError('');}}).catch(e=>{if(alive&&e.name!=='AbortError')setError('Progress could not refresh. Your analysis continues on the server.');}).finally(()=>{fetching=false;});},1500);
    return()=>{alive=false;clearInterval(timer);controller?.abort();};
  },[running]);
  function track(analysis:Analysis){setData(old=>old?{...old,analyses:[...old.analyses.filter(a=>a.analysis_id!==analysis.analysis_id),analysis]}:old);setMonitored(analysis.analysis_id);localStorage.setItem('review:analysis-job',analysis.analysis_id);}
  async function start(event:FormEvent){event.preventDefault();if(submitting.current)return;submitting.current=true;setPending(true);setError('');try{track(await request<Analysis>('/analyses',{url:url.trim(),max_comments:limit,with_replies:replies,refresh:fresh}));}catch(e){setError((e as Error).message);}finally{submitting.current=false;setPending(false);}}
  async function retry(id:string){if(submitting.current)return;submitting.current=true;setPending(true);setError('');try{track(await request<Analysis>(`/analyses/${id}/retry`,{}));}catch(e){setError((e as Error).message);}finally{submitting.current=false;setPending(false);}}
  const example=data?.analyses.find(a=>a.is_example),analysis=data?.analyses.find(a=>a.analysis_id===monitored&&!a.is_example);
  const history=data?.analyses.filter(a=>!a.is_example&&a.analysis_id!==monitored).sort((a,b)=>b.created_at.localeCompare(a.created_at))||[];
  return <div className="video-library">
    <header className="library-header"><a href="#" aria-label="Re.View home" className="library-brand"><img src="/assets/perspectiveglyph.svg" width="32" height="32" alt=""/>Re.View</a><span>Explore. Converse. Reflect.</span></header>
    <main className="library-main"><section className="library-intro"><p className="eyebrow">A DIFFERENT WAY TO READ THE COMMENTS</p><h1>One video.<br/><span>More perspectives.</span></h1><p>Discover the viewpoints in a YouTube comment section.<br/>Talk with agents grounded in what people actually said.</p><div className="library-avatar-strip" aria-hidden="true">{['character4.svg','character2.svg','character3.svg','character.svg','character1.svg'].map(src=><img key={src} src={`/assets/${src}`} width="38" height="38"/>)}<span>Different views. Original evidence.</span></div></section>
    <div className="library-entry-grid"><section className="new-video-panel" aria-labelledby="new-video-heading"><div className="entry-kicker"><span className="link-symbol" aria-hidden="true">↗</span>START WITH YOUR OWN VIDEO</div><h2 id="new-video-heading">What are you curious about?</h2><p>Paste a video link. We’ll collect the comments and build agents around the perspectives we find.</p>
      <form onSubmit={event=>void start(event)}><label htmlFor="video-url">YouTube video link</label><div className="video-url-field"><input id="video-url" name="url" type="text" inputMode="url" autoComplete="url" required maxLength={2000} placeholder="https://www.youtube.com/watch?v=…" value={url} onChange={e=>setUrl(e.target.value)} disabled={data?.can_analyze===false}/></div>
      <details className="analysis-options"><summary>Analysis options <span>Up to {number(limit)} total comments{replies?' · replies included':''}</span></summary><div className="analysis-options-body"><label htmlFor="comment-limit">Total comment limit</label><select id="comment-limit" value={limit} onChange={e=>setLimit(Number(e.target.value))}>{[200,500,1000,2000].map(n=><option key={n} value={n}>{number(n)} comments</option>)}</select><label className="option-check"><input type="checkbox" checked={replies} onChange={e=>setReplies(e.target.checked)}/>Include replies within this total</label><label className="option-check"><input type="checkbox" checked={fresh} onChange={e=>setFresh(e.target.checked)}/>Collect a fresh snapshot instead of reusing an existing analysis</label></div></details>
      <button className="primary analyze-button" type="submit" disabled={pending||!url.trim()||!data?.can_analyze}>{pending?'Starting analysis…':'Analyze video'}</button>
      <p className="analysis-help">{data?.can_analyze===false?'New video analysis is available in the local app. Explore the prepared example here.':'Public comments only. Newest comments are collected first, within your limit. Analysis may take several minutes. Prepared results are reused when available.'}</p></form>
    </section><section className="example-panel" aria-labelledby="example-heading"><h2 id="example-heading">Take a look around</h2><p>{example?.has_walkthrough?'Follow a completed journey: an initial view, recorded conversations, and a finished reflection.':'Try a prepared example and see how the perspectives come together.'}</p>{example?<><div className="example-thumbnail"><img src={example.thumbnail_url} alt="Example video thumbnail"/><span className="example-label">PREPARED EXAMPLE</span></div><h3>{example.title}</h3><div className="example-stats"><span>{number(example.collected_count)} comments</span><span>{example.agent_count} perspectives</span></div><button className="secondary" onClick={()=>onOpen(example.has_walkthrough?'walkthrough':example.analysis_id)}>Explore example</button><p className="example-note">{example.has_walkthrough?'All steps are ready to explore.':'Analysis is ready. No collection wait.'}</p></>:<p role="status">Loading the example…</p>}</section></div>
    {error&&<div className="library-error" role="alert"><p>{error}</p>{!data&&<button className="secondary" onClick={()=>setLoadAttempt(v=>v+1)}>Try again</button>}</div>}
    {analysis&&<Progress analysis={analysis} onOpen={onOpen} onRetry={id=>void retry(id)} pending={pending}/>}
    {history.length>0&&<section className="analysis-history" aria-label="Previous analyses"><div className="history-heading"><h2>Your video library</h2><p>Each analysis keeps its own conversations and evidence.</p></div><div className="history-grid">{history.map(a=><article className="history-card" key={a.analysis_id}><img src={a.thumbnail_url} alt=""/><div><span className={`history-status ${a.status}`}>{a.status==='ready'?'Ready to explore':a.status==='failed'?'Needs a retry':a.status==='interrupted'?'Saved for resume':a.status==='queued'?'Queued':'Analyzing'}</span><h3>{a.title}</h3><p>{number(a.collected_count)} comments{a.agent_count>0?` · ${a.agent_count} perspectives`:''}</p><button className="inline-link" onClick={()=>{if(a.status==='ready')onOpen(a.analysis_id);else{setMonitored(a.analysis_id);localStorage.setItem('review:analysis-job',a.analysis_id);}}}>{a.status==='ready'?'Open analysis':'View progress'}</button></div></article>)}</div></section>}
    <footer className="library-footer"><img src="/assets/perspectiveglyph.svg" width="20" height="20" alt=""/><p>Perspectives come from comments. Every agent’s evidence stays connected to the original.</p></footer></main>
  </div>;
}
