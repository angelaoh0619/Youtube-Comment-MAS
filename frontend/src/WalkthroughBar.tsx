import type {Stage} from './types';

const STEPS:{stage:Stage;label:string;help:string}[]=[
  {stage:'start',label:'Initial view',help:'Read the opinion that started this recorded journey.'},
  {stage:'explore',label:'Explore',help:'See the five perspectives and compare them with the initial view.'},
  {stage:'converse',label:'Converse',help:'Read the recorded 1:1 and group conversations. Open Evidence to see the original comments.'},
  {stage:'reflect',label:'Reflect',help:'Read the completed reflection and follow its links back to the conversations.'},
];

export default function WalkthroughBar({stage,onStage,onTry}:{stage:Stage;onStage:(stage:Stage)=>void;onTry:()=>void}){
  const current=STEPS.find(s=>s.stage===stage)||STEPS[0];
  return <aside className="walkthrough-banner" aria-label="Completed example walkthrough">
    <div className="walkthrough-heading"><div><span className="walkthrough-label">COMPLETED EXAMPLE <small>Fictional opinions · Real comment evidence</small></span><p>{current.help}</p></div><button className="secondary" onClick={onTry}>Write your own view</button></div>
    <nav className="walkthrough-steps" aria-label="Example journey">{STEPS.map(s=><button key={s.stage} onClick={()=>onStage(s.stage)} aria-current={stage===s.stage?'step':undefined}><span aria-hidden="true">✓</span>{s.label}</button>)}</nav>
  </aside>;
}
