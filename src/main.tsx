import {tr, language} from './language';
import React,{useEffect,useRef,useState} from 'react';
import {createRoot} from 'react-dom/client';
import {Lab} from './Lab';
import {api,type Road,type Bundle,type Topic,type Anchor,type Msg,type Progress} from './types';
import './style.css';

function Dialog({title,children,close,pop}:{title:string,children:React.ReactNode,close:()=>void,pop?:{x:number,y:number}}){
  const ref=useRef<HTMLDialogElement>(null);
  useEffect(()=>{const d=ref.current!;const origin=document.activeElement as HTMLElement;d.showModal();return()=>{d.close();origin?.focus({preventScroll:true})}},[]);
  const style=pop?{margin:0,left:Math.max(8,Math.min(pop.x,innerWidth-Math.min(440,innerWidth-16)-8)),top:Math.max(8,Math.min(pop.y+8,innerHeight-Math.min(490,innerHeight-16)-8))}:undefined;
  return <dialog ref={ref} aria-label={title} className={pop?'popup':''} style={style} onCancel={e=>{e.preventDefault();close()}}><header><h2>{title}</h2><button aria-label={tr("Đóng", "Close")} onClick={close}>×</button></header>{children}</dialog>
}

function Planner({base,done,close}:{base:Road|null,done:(r:Road)=>void,close:()=>void}){
  const [draft,setDraft]=useState<Road|null>(base),[busy,setBusy]=useState(false),[err,setErr]=useState('');
  const [values,setValues]=useState({subject:base?.title||tr("Vật lý", "Physics"),goal:base?.goal||'',level:tr("Mới bắt đầu", "Beginner"),schedule:tr("30 phút mỗi ngày", "30 minutes a day"),revision:''});
  async function generate(e:React.FormEvent){e.preventDefault();setBusy(true);setErr('');try{setDraft(await api<Road>('drafts',{...values,previous:draft}))}catch(e){setErr(String(e))}finally{setBusy(false)}}
  return <Dialog title={base?tr("Phiên bản lộ trình mới", "New roadmap version"):tr("Tạo lộ trình", "Create roadmap")} close={close}><form onSubmit={generate}>{(['subject','goal','level','schedule'] as const).map((k,i)=><label key={k}>{[tr("Chủ đề", "Subject"),tr("Mục tiêu học", "Learning goal"),tr("Trình độ hiện tại", "Current level"),tr("Thời gian học", "Study time")][i]}<input required value={values[k]} onChange={e=>setValues({...values,[k]:e.target.value})}/></label>)}
  {draft&&<><h3>{draft.title}</h3>{draft.chapters.map((c,i)=><section key={i}><b>{c.title}</b><ol>{c.topics.map((t,j)=><li key={j}>{t.title} — {t.goal}</li>)}</ol></section>)}<label>{tr("Điều bạn muốn chỉnh", "What would you like to change?")}<input value={values.revision} onChange={e=>setValues({...values,revision:e.target.value})}/></label></>}
  <div className="actions"><button disabled={busy}>{busy?tr("Đang xử lý…", "Preparing draft…"):draft?tr("Chỉnh bản nháp", "Revise draft"):tr("Tạo bản nháp", "Create draft")}</button>{draft&&<button type="button" className="primary" disabled={busy} onClick={async()=>{setBusy(true);setErr('');try{done(await api<Road>('roads',draft))}catch(e){setErr(String(e));setBusy(false)}}}>{tr("Chốt lộ trình", "Confirm roadmap")}</button>}</div>{err&&<p role="alert">{err}</p>}</form></Dialog>
}

function Cited({msg}:{msg:Msg}){
  const text=Array.from(msg.text), parts:React.ReactNode[]=[];let last=0;
  for(const [i,s] of [...(msg.sources||[])].sort((a,b)=>a.end-b.end).entries()){
    const end=Math.min(text.length,Math.max(last,s.end));parts.push(text.slice(last,end).join(''),<a key={i} href={s.url} target="_blank" rel="noreferrer" title={s.title}> [{s.title||tr("Nguồn", "Source")}] </a>);last=end;
  }
  return <>{parts}{text.slice(last).join('')}</>
}
function Chat({path,initial=[]}:{path:string,initial?:Msg[]}){
  const [history,setHistory]=useState<Msg[]>(initial),[text,setText]=useState(''),[search,setSearch]=useState(false),[busy,setBusy]=useState(false),[err,setErr]=useState(''),[loaded,setLoaded]=useState(false);
  useEffect(()=>{let live=true;api<Msg[]>('chat/'+path).then(x=>{if(live)setHistory(x)}).catch(e=>{if(live)setErr(String(e))}).finally(()=>{if(live)setLoaded(true)});return()=>{live=false}},[path]);
  return <><div className="history" aria-live="polite">{history.map((m,i)=><div className={'msg '+m.role} key={i}><b>{m.role==='user'?tr("Bạn", "You"):tr("Gia sư", "Tutor")}</b><p><Cited msg={m}/></p>{!!m.traces?.length&&<details><summary>{tr("Phép kiểm chứng Python", "Python calculations")}</summary><pre>{JSON.stringify(m.traces,null,2)}</pre></details>}</div>)}</div>
  <form onSubmit={async e=>{e.preventDefault();if(!text.trim()||busy)return;setBusy(true);setErr('');try{setHistory(await api<Msg[]>('chat/'+path,{text,search}));setText('')}catch(e){setErr(String(e))}finally{setBusy(false)}}}>
  <label>{tr("Câu hỏi của bạn", "Your question")}<textarea required value={text} onChange={e=>setText(e.target.value)} placeholder={tr("Bạn muốn hiểu rõ điều gì?", "What would you like to understand?")}/></label><div className="actions"><label className="inline"><input type="checkbox" checked={search} onChange={e=>setSearch(e.target.checked)}/>{tr("Tra cứu web", "Search the web")}</label><button className="primary" disabled={!loaded||busy}>{busy?tr("Đang trả lời…", "Thinking…"):tr("Gửi câu hỏi", "Send question")}</button></div>{err&&<p role="alert">{err}</p>}</form></>
}

function Reader({road,topic}:{road:Road,topic:Topic}){
  const path=road.id+'/'+topic.id;
  const [bundle,setBundle]=useState<Bundle|null>(null),[err,setErr]=useState(''),[busy,setBusy]=useState(false);
  const [branch,setBranch]=useState<{note:Anchor,x:number,y:number}|null>(null);
  const [attempt,setAttempt]=useState<number|null>(null);
  const snapshots=useRef<Record<number,Record<string,number>>>({}), live=useRef(true),restored=useRef(false);
  const doc=bundle?.doc;
  useEffect(()=>{live.current=true;api<Bundle>('lesson/'+path).then(b=>{if(live.current)setBundle(b)}).catch(e=>{if(live.current)setErr(String(e))});return()=>{live.current=false}},[path]);
  useEffect(()=>{
    if(!doc||restored.current)return;restored.current=true;const original=bundle!.scroll;
    const raf=requestAnimationFrame(()=>window.scrollTo(0,original));
    let timer=0,changed=false,position=original;
    const save=()=>{clearTimeout(timer);if(!changed)return;changed=false;void fetch('/api/scroll/'+path,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({y:position}),keepalive:true}).catch(()=>{})};
    const scroll=()=>{changed=true;position=Math.max(0,Math.round(window.scrollY));clearTimeout(timer);timer=window.setTimeout(save,400)};
    window.addEventListener('scroll',scroll);window.addEventListener('pagehide',save);return()=>{cancelAnimationFrame(raf);window.removeEventListener('scroll',scroll);window.removeEventListener('pagehide',save);save()}
  },[doc?.version]);
  async function select(){
    const sel=window.getSelection();if(!doc||!sel?.rangeCount||sel.isCollapsed)return;
    const range=sel.getRangeAt(0),parent=(n:Node)=>n.nodeType===1?n as Element:n.parentElement;
    const block=parent(range.startContainer)?.closest<HTMLElement>('[data-block]');
    if(!block||block!==parent(range.endContainer)?.closest('[data-block]'))return;
    const prefix=range.cloneRange();prefix.selectNodeContents(block);prefix.setEnd(range.startContainer,range.startOffset);
    const start=prefix.toString().length,quote=range.toString();if(!quote.trim())return;
    const id=block.dataset.block!,rect=range.getBoundingClientRect(),snapshot=/^[ie]\d+$/.test(id)?snapshots.current[Number(id.slice(1))]??null:null;
    try{const note=await api<Anchor>('notes/'+path,{version:doc.version,block:id,start,end:start+quote.length,quote,snapshot});if(!live.current)return;
      setBundle(b=>b&&({...b,notes:b.notes.some(n=>n.id===note.id)?b.notes:[...b.notes,note]}));sel.removeAllRanges();setBranch({note,x:rect.left,y:rect.bottom})}catch(e){setErr(String(e))}
  }
  function annotated(id:string,text:string){
    const notes=(bundle?.notes||[]).filter(n=>n.block===id);
    const stops=[...new Set([0,text.length,...notes.flatMap(n=>[n.start,n.end])])].sort((a,b)=>a-b);
    return <p data-block={id} onMouseUp={select} onKeyUp={e=>{if(e.key==='Shift')void select()}} onTouchEnd={()=>setTimeout(select,0)}>{stops.slice(1).map((end,i)=>{const start=stops[i],s=text.slice(start,end),n=notes.find(n=>n.start<=start&&n.end>=end);
      const open=(el:HTMLElement)=>{const r=el.getBoundingClientRect();setBranch({note:n!,x:r.left,y:r.bottom})};
      return n?<mark key={i} role="button" tabIndex={0} onKeyDown={e=>{if(e.key==='Enter')open(e.currentTarget)}} onClick={e=>{if(window.getSelection()?.isCollapsed)open(e.currentTarget)}}>{s}</mark>:s})}</p>
  }
  return <article key={path}><div className="crumb">{road.title} <span>/</span> {road.chapters.find(c=>c.topics.some(t=>t.id===topic.id))?.title}</div><h1>{topic.title}</h1>
  {err&&<p role="alert">{err}</p>}{!bundle&&!err&&<p>{tr("Đang mở bài…", "Opening lesson…")}</p>}
  {bundle&&!doc&&<><p>{topic.goal}</p><button className="primary" disabled={busy} onClick={async()=>{setBusy(true);setErr('');try{await api('lesson/'+path,{});const next=await api<Bundle>('lesson/'+path);if(live.current)setBundle(next)}catch(e){setErr(String(e))}finally{setBusy(false)}}}>{busy?tr("Gia sư đang soạn bài…", "Preparing your lesson…"):tr("Học bài này", "Start lesson")}</button></>}
  {doc&&bundle&&<><div className="intro">{annotated('intro',doc.intro)}</div><nav className="tabs"><a href="#lesson">{tr("Bài giảng", "Lesson")}</a><a href="#quiz">Quiz</a><a href="#tutor">{tr("Hỏi gia sư", "Ask the tutor")}</a></nav>
  <div id="lesson">{doc.sections.map((s,i)=><section key={i}><h2>{s.title}</h2>{annotated('s'+i,s.text)}
    {doc.illustrations.map((v,j)=>v.section===i?<Lab key={j} item={v} index={j} path={path} annotate={annotated} onSnapshot={state=>{snapshots.current[j]=state}}/>:null)}</section>)}</div>
  <section id="quiz"><h2>{tr("Kiểm tra nhanh", "Quick quiz")}</h2>{doc.quiz.map((q,i)=>{const prev=bundle.progress[i]?.at(-1);return <form key={i} className="question" onSubmit={async e=>{e.preventDefault();const answer=new FormData(e.currentTarget).get('answer');setAttempt(i);setErr('');try{const progress=await api<Progress>('quiz/'+path,{question:i,answer});setBundle(b=>b&&({...b,progress}))}catch(e){setErr(String(e))}finally{setAttempt(null)}}}>
    <h3>{q.prompt}</h3>{q.kind==='choice'?q.choices.map(c=><label className="inline" key={c}><input type="radio" name="answer" required value={c} defaultChecked={prev?.answer===c}/>{c}</label>):<label>{tr("Đáp số và đơn vị", "Answer and unit")}<input required name="answer" defaultValue={prev?.answer} placeholder={tr("Ví dụ: 1,5 m", "For example, 1.5 m")}/></label>}
    <button disabled={attempt!==null}>{tr("Kiểm tra đáp án", "Check answer")}</button>{prev&&<p role="status" className={prev.correct?'success':'feedback'}><b>{prev.correct?tr("Chính xác.", "Correct."):tr("Chưa đúng.", "Try again.")}</b> {prev.explanation}</p>}</form>})}</section>
  <section id="tutor"><h2>{tr("Hỏi gia sư", "Ask the tutor")}</h2><Chat path={path+'/main'} initial={bundle.main}/></section>
  {!!bundle.notes.length&&<details><summary>{tr("Các đoạn đã đánh dấu", "Highlighted passages")} ({bundle.notes.length})</summary>{bundle.notes.map(n=><button className="note" key={n.id} onClick={e=>{const r=e.currentTarget.getBoundingClientRect();setBranch({note:n,x:r.left,y:r.top})}}>{n.quote}</button>)}</details>}
  {branch&&<Dialog title={tr("Hỏi về đoạn này", "Ask about this passage")} pop={branch} close={()=>setBranch(null)}><blockquote>{branch.note.quote}</blockquote>{branch.note.snapshot&&<small>{Object.entries(branch.note.snapshot).map(([k,v])=>k+' = '+Number(v.toFixed(3))).join(' · ')}</small>}<Chat key={branch.note.id} path={path+'/'+branch.note.id}/></Dialog>}</>}</article>
}

type AISettings={provider:'openai'|'codex',saved_key:boolean,environment_key:boolean,codex:'ready'|'logged_out'|'missing'|'unknown',codex_model:string|null,codex_models:{id:string,name:string}[]};

function Settings({close}:{close:()=>void}){
  const [settings,setSettings]=useState<AISettings|null>(null),[key,setKey]=useState(''),[remove,setRemove]=useState(false);
  const [busy,setBusy]=useState(false),[error,setError]=useState('');
  useEffect(()=>{let active=true;api<AISettings>('settings').then(s=>{if(active)setSettings(s)}).catch(e=>{if(active)setError(String(e))});return()=>{active=false}},[]);
  const status={ready:tr("Codex CLI đã đăng nhập.", "Codex CLI is signed in."),logged_out:tr("Chạy codex login trong terminal để đăng nhập.", "Run codex login in your terminal to sign in."),missing:tr("Chưa tìm thấy Codex CLI trong PATH của máy chủ.", "Codex CLI was not found on the server PATH."),unknown:tr("Chưa xác định được trạng thái. Kiểm tra bằng codex login status.", "Sign-in status is unknown. Run codex login status to check.")};
  return <Dialog title={tr("Cài đặt", "Settings")} close={close}>{settings?<form onSubmit={async e=>{
    e.preventDefault();setBusy(true);setError('');
    try{await api('settings',{provider:settings.provider,...(settings.provider==='codex'?{codex_model:settings.codex_model}:{}),...(settings.provider==='openai'&&key.trim()?{api_key:key.trim()}:{}),remove_key:settings.provider==='openai'&&remove});close()}
    catch(e){setError(String(e));setBusy(false)}
  }}>
    <label>{tr("Nguồn AI", "AI provider")}<select value={settings.provider} onChange={e=>setSettings({...settings,provider:e.target.value as AISettings['provider']})}>
      <option value="openai">OpenAI API key</option><option value="codex">Codex CLI</option></select></label>
    {settings.provider==='openai'?<>
      <label>{settings.saved_key?tr("Thay API key", "Replace API key"):'OpenAI API key'}<input type="password" autoComplete="off" disabled={remove} value={key} onChange={e=>setKey(e.target.value)} placeholder={settings.saved_key?tr("Đã lưu khóa trên máy", "Key saved on this device"):tr("Nhập API key", "Enter API key")}/></label>
      <p>{settings.saved_key?tr("Khóa đã lưu được mã hóa bằng tài khoản Windows của bạn.", "Your saved key is encrypted with your Windows account."):settings.environment_key?tr("Đang dùng khóa từ OPENAI_API_KEY. Khóa nhập ở đây sẽ được ưu tiên.", "Using OPENAI_API_KEY. A key entered here takes priority."):tr("Bạn cũng có thể dùng biến môi trường OPENAI_API_KEY.", "You can also set the OPENAI_API_KEY environment variable.")}</p>
      {settings.saved_key&&<label className="inline"><input type="checkbox" checked={remove} onChange={e=>setRemove(e.target.checked)}/>{tr("Xóa khóa đã lưu trên máy", "Remove the saved key from this device")}</label>}
    </>:<><p>{status[settings.codex]}</p><label>{tr("Model Codex", "Codex model")}<select value={settings.codex_model||''} onChange={e=>setSettings({...settings,codex_model:e.target.value||null})}>
      <option value="">{tr("Mặc định của Codex CLI", "Codex CLI default")}</option>
      {settings.codex_model&&!settings.codex_models.some(m=>m.id===settings.codex_model)&&<option value={settings.codex_model}>{settings.codex_model} {tr("(đã lưu)", "(saved)")}</option>}
      {settings.codex_models.map(m=><option key={m.id} value={m.id}>{m.name}</option>)}
    </select></label></>}
    <button className="primary" disabled={busy}>{busy?tr("Đang lưu…", "Saving…"):tr("Lưu cài đặt", "Save settings")}</button>
  </form>:!error&&<p>{tr("Đang đọc cài đặt…", "Loading settings…")}</p>}{error&&<p role="alert">{error}</p>}</Dialog>
}

function App(){
  const [showSettings,setShowSettings]=useState(false);
  const [roads,setRoads]=useState<Road[]>([]),[selected,setSelected]=useState(()=>localStorage.getItem('selected')||(language==='en'?'physics/free-fall':'vat-ly/roi-tu-do')),[planner,setPlanner]=useState<'new'|'revise'|null>(null),[err,setErr]=useState('');
  useEffect(()=>{api<Road[]>('roads').then(setRoads).catch(e=>setErr(String(e)))},[]);
  const [rid,tid]=selected.split('/'),road=roads.find(r=>r.id===rid)||roads[0],topic=road?.chapters.flatMap(c=>c.topics).find(t=>t.id===tid)||road?.chapters[0].topics[0];
  function choose(r:Road,t:Topic){const id=r.id+'/'+t.id;localStorage.setItem('selected',id);setSelected(id);window.scrollTo(0,0)}
  return <><header className="top"><div className="brand"><span className="brandmark" aria-hidden="true">∿</span> ConceptLens</div><div className="actions"><select aria-label={tr("Ngôn ngữ", "Language")} value={language} onChange={e=>{
    const next=e.target.value;
    localStorage.setItem('language',next);
    const samples:Record<string,string>={'vat-ly/roi-tu-do':'physics/free-fall','vat-ly/gia-toc':'physics/acceleration','physics/free-fall':'vat-ly/roi-tu-do','physics/acceleration':'vat-ly/gia-toc'};
    if(samples[selected])localStorage.setItem('selected',samples[selected]);
    window.location.reload();
  }}><option value="vi" lang="vi">Tiếng Việt</option><option value="en" lang="en">English</option></select><button onClick={()=>setShowSettings(true)}>{tr("Cài đặt", "Settings")}</button><button onClick={()=>setPlanner('new')}>{tr("＋ Tạo lộ trình", "＋ Create roadmap")}</button></div></header>
  {showSettings&&<Settings close={()=>setShowSettings(false)}/>}
  {err&&<p role="alert">{err}</p>}{road&&topic&&<div className="layout"><aside><label>{tr("Lộ trình của bạn", "Your roadmap")}<select value={road.id} onChange={e=>{const r=roads.find(x=>x.id===e.target.value)!;choose(r,r.chapters[0].topics[0])}}>{roads.map(r=><option key={r.id} value={r.id}>{r.title}</option>)}</select></label>
    {road.chapters.map((c,i)=><div key={i}><h3>{c.title}</h3>{c.topics.map(t=><button key={t.id} className={'topic '+(t.id===topic.id?'selected':'')} aria-current={t.id===topic.id?'page':undefined} onClick={()=>choose(road,t)}>{t.title}</button>)}</div>)}
    <button className="revise" onClick={()=>setPlanner('revise')}>{tr("Tạo phiên bản mới", "Create new version")}</button></aside><main><Reader key={road.id+'/'+topic.id} road={road} topic={topic}/></main></div>}
    {planner&&<Planner base={planner==='revise'?road:null} close={()=>setPlanner(null)} done={r=>{setRoads([r,...roads]);choose(r,r.chapters[0].topics[0]);setPlanner(null)}}/>}</>
}
createRoot(document.getElementById('root')!).render(<App/>);

