import {tr, language} from './language';
import {useEffect,useMemo,useRef,useState} from 'react';
import type {ReactNode} from 'react';
import interpreter from 'js-interpreter/lib/js-interpreter.min.js?raw';
import purifier from '../node_modules/dompurify/dist/purify.min.js?raw';
import bridge from './frame.js?raw';
import {api,fmt,type Visual,type Sim} from './types';

const code=[purifier,interpreter,bridge].map(s=>'<script nonce="lab">'+s.replace(/<\/script/gi,'<\\/script')+'</script>').join('');
const page='<!doctype html><html lang="'+language+'"><meta charset=utf-8><meta http-equiv="Content-Security-Policy" content="default-src \'none\'; script-src \'nonce-lab\'; style-src \'unsafe-inline\'; base-uri \'none\'; form-action \'none\'"><style>body{margin:0;font:15px system-ui;color:#21493d}main{padding:8px}svg{width:100%;height:210px;display:block}</style><main></main>'+code;

function Plot({sim,index}:{sim:Sim,index:number}){
  const [field,setField]=useState<'s'|'v'>('s');
  const values=sim.points.map(p=>p[field]), min=Math.min(0,...values),max=Math.max(min+0.1,...values);
  const x=(t:number)=>40+248*t/sim.params.duration, y=(n:number)=>148-124*(n-min)/(max-min);
  const point=sim.points[index];
  return <div className="plot"><select aria-label={tr("Đại lượng đồ thị", "Quantity to plot")} value={field} onChange={e=>setField(e.target.value as 's'|'v')}><option value="s">{tr("Vị trí (m)", "Position (m)")}</option><option value="v">{tr("Vận tốc (m/s)", "Velocity (m/s)")}</option></select>
    <svg viewBox="0 0 312 172" role="img" aria-label={tr("Đồ thị theo thời gian", "Graph over time")}>{[0,1,2,3,4].map(i=><g key={i}><line x1="40" x2="288" y1={24+31*i} y2={24+31*i} stroke="#ccdbd1"/><text x="36" y={28+31*i} textAnchor="end">{fmt(max-(max-min)*i/4)}</text></g>)}
    <polyline points={sim.points.map(p=>x(p.t)+','+y(p[field])).join(' ')} fill="none" stroke="#23664e" strokeWidth="3"/>
    {sim.points.filter(p=>Math.abs(p.t-Math.round(p.t))<0.00001).map(p=><circle key={p.t} cx={x(p.t)} cy={y(p[field])} r="3" fill="#23664e"/>)}
    <circle cx={x(point.t)} cy={y(point[field])} r="6" fill="#b95224"/><text x="40" y="166">0</text><text x="288" y="166" textAnchor="end">{fmt(sim.params.duration)} s</text></svg></div>;
}

function Ruler({sim,index}:{sim:Sim,index:number}){
  const positions=sim.points.map(p=>p.s), min=Math.min(...positions), span=Math.max(...positions)-min||1;
  const x=(s:number)=>25+450*(s-min)/span;
  const marks=sim.marks||sim.points.filter(p=>Number.isInteger(p.t));
  const step=Math.max(1,Math.ceil(marks.length/7));
  return <svg className="ruler" viewBox="0 0 500 57" role="img" aria-label={tr("Vị trí của vật sau từng giây", "Position of the object at each second")}>
    <line x1="25" x2="475" y1="19" y2="19" stroke="#789385"/>
    {marks.map(p=><g key={p.t}><title>{p.t} s · {fmt(p.s)} m</title><line x1={x(p.s)} x2={x(p.s)} y1="14" y2="25" stroke="#315542"/>
    {p.t%step===0&&<text x={x(p.s)} y={p.t%2?51:38} textAnchor="middle">{p.t} s</text>}</g>)}
    <circle cx={x(sim.points[index].s)} cy="19" r="5" fill="#b95224"/></svg>;
}

export function Lab({item,index,path,annotate,onSnapshot}:{item:Visual,index:number,path:string,annotate:(id:string,text:string)=>ReactNode,onSnapshot:(s:Record<string,number>)=>void}){
  const [visual,setVisual]=useState(item),[sim,setSim]=useState<Sim|null>(null),[pos,setPos]=useState(0),[play,setPlay]=useState(false);
  const [ready,setReady]=useState(false),[failure,setFailure]=useState(''),[busy,setBusy]=useState(false),[simError,setSimError]=useState('');
  const frame=useRef<HTMLIFrameElement>(null),last=useRef<number[]>([0,0,0,0]),tried=useRef(false), saving=useRef(Promise.resolve()), alive=useRef(true);
  const endpoint='motion/'+path+'/'+index,isMotion=visual.mode==='motion';
  useEffect(()=>{alive.current=true;return()=>{alive.current=false}},[]);
  useEffect(()=>{if(isMotion)api<Sim>(endpoint).then(data=>{if(alive.current){setSim(data);setPos(data.index)}}).catch(e=>setSimError(e.message));},[endpoint,isMotion]);
  const point=sim?.points[pos];
  // For motion, k places the object on a scale spanning the whole trajectory.
  const bounds=useMemo(()=>{const s=sim?.points.map(p=>p.s)||[0];return [Math.min(...s),Math.max(...s)]},[sim]);
  const values=isMotion&&point?[point.t,point.s,point.v,100*(point.s-bounds[0])/(bounds[1]-bounds[0]||1)]:[0,0,0,pos];
  last.current=values;
  useEffect(()=>{if(ready) frame.current?.contentWindow?.postMessage({type:'draw',values:last.current},'*');
    onSnapshot(isMotion && point && sim?{...point,...sim.params}:{k:pos});
  },[ready,pos,sim]);
  useEffect(()=>{if(!play)return;const id=window.setInterval(()=>setPos(p=>Math.min(240,p+1)),(sim?.params.duration||4)*1000/240);return()=>clearInterval(id)},[play,sim]);
  useEffect(()=>{if(pos===240)setPlay(false)},[pos]);
  function persist(params:Sim['params'],index:number,update=false){
    if(update){setBusy(true);setPlay(false)}
    saving.current=saving.current.then(async()=>{try{const data=await api<Sim>(endpoint,{params,index});if(alive.current){setSimError('');if(update){setSim(data);setPos(data.index)}}}catch(e){if(alive.current)setSimError(String(e))}finally{if(alive.current&&update)setBusy(false)}});
  }
  useEffect(()=>{if(!sim||play)return;const id=setTimeout(()=>persist(sim.params,pos),260);return()=>clearTimeout(id)},[pos,play,sim]);
  async function repair(error:string,manual:boolean){
    setBusy(true);setReady(false);setPlay(false);setFailure(error);
    try{const v=await api<Visual>('repair/'+path+'/'+index,{error,manual});if(alive.current){setVisual(v);setFailure('')}}
    catch(e){if(alive.current)setFailure(String(e))}finally{if(alive.current)setBusy(false)}
  }
  useEffect(()=>{
    function failed(message:string){setReady(false);setFailure(message);setPlay(false);if(!tried.current){tried.current=true;void repair(message,false)}}
    function listen(e:MessageEvent){if(!frame.current || e.source!==frame.current.contentWindow)return;
      if(e.data?.type==='ready')setReady(true);
      if(e.data?.type==='failed')failed(String(e.data.error));
    }
    window.addEventListener('message',listen);return()=>window.removeEventListener('message',listen);
  },[visual]);
  return <figure className="lab"><div className="labhead"><span className="labicon" aria-hidden="true">∿</span><h3>{visual.title}</h3></div>
    {annotate('i'+index,visual.instruction)}
    {(sim||!isMotion)&&!failure&&<div className={'stage '+(isMotion?'':'full')} style={{visibility:ready?'visible':'hidden'}}>
      <iframe key={visual.js+visual.html+visual.css} title={visual.title} ref={frame} sandbox="allow-scripts" srcDoc={page} onLoad={()=>frame.current?.contentWindow?.postMessage({type:'init',item:visual,values:last.current,testValues:isMotion&&sim?[sim.points[120].t,sim.points[120].s,sim.points[120].v,50]:[0,0,0,75]},'*')}/>
      {sim&&isMotion&&<><Plot sim={sim} index={pos}/><Ruler sim={sim} index={pos}/></>}</div>}
    {failure?<div role="status">{busy?tr("Đang sửa minh họa…", "Repairing illustration…"):failure} <button disabled={busy} onClick={()=>repair(failure,true)}>{tr("Tạo lại minh họa", "Regenerate illustration")}</button></div>:
    <><div className="controls">{isMotion&&<button aria-label={play?tr("Dừng", "Pause"):tr("Phát", "Play")} disabled={!ready||busy} onClick={()=>{if(pos===240)setPos(0);setPlay(!play)}}>{play?'Ⅱ':'▶'}</button>}
      <label>{isMotion?tr("Thời gian", "Time"):tr("Tham số", "Parameter")}<input aria-label={isMotion?tr("Thời gian", "Time"):tr("Tham số", "Parameter")} type="range" min="0" max={isMotion?240:100} value={pos} disabled={!ready||busy} onChange={e=>{setPlay(false);setPos(+e.target.value)}}/></label>
      <output>{isMotion?fmt(point?.t??0)+' s':pos+'%'}</output></div>
      {isMotion&&sim&&<><div className="numbers"><span>{tr("Vị trí", "Position")} <b>{fmt(point?.s??0)} m</b></span><span>{tr("Vận tốc", "Velocity")} <b>{fmt(point?.v??0)} m/s</b></span></div>
      <details><summary>{tr("Điều chỉnh điều kiện ban đầu", "Adjust initial conditions")}</summary><form className="params" onSubmit={e=>{e.preventDefault();const f=new FormData(e.currentTarget);persist({acceleration:Number(f.get('a')),velocity:Number(f.get('v')),duration:Number(f.get('d'))},pos,true)}}>
      <label>{tr("Gia tốc (m/s²)", "Acceleration (m/s²)")}<input required type="number" name="a" min="-100" max="100" step="any" defaultValue={sim.params.acceleration}/></label>
      <label>{tr("Vận tốc đầu (m/s)", "Initial velocity (m/s)")}<input required type="number" name="v" min="-100" max="100" step="any" defaultValue={sim.params.velocity}/></label>
      <label>{tr("Thời lượng (s)", "Duration (s)")}<input required type="number" name="d" min="0.1" max="60" step="any" defaultValue={sim.params.duration}/></label><button disabled={busy}>{tr("Áp dụng", "Apply")}</button></form></details></>}</>}
    {simError&&<p role="alert">{simError}</p>}{annotate('e'+index,visual.explanation)}</figure>;
}

