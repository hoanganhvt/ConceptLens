import {useEffect,useRef,useState} from 'react';
import {language,tr} from './language';
import {renderMath} from './math';
import {api,type MemoryRef} from './types';

type EvidenceRef={attempt_id:string};
type Evidence=EvidenceRef&{prompt:string,answer:string,correct:boolean,explanation:string,observed_at:string|null};
type MemoryKind='goal'|'preference';
type Memory=MemoryRef&{
  kind:MemoryKind|'recurring_mistake',statement:string,roadmap_id:string|null,
  roadmap_title:string|null,dimension:string|null,status:'tentative'|'recurring'|'resolved'|'confirmed',
  evidence:EvidenceRef[]
};
type MemoryList={enabled:boolean,memories:Memory[],encoder_status?:'missing'|'building'|'ready'|'error'};

function dimensionName(dimension:string){
  const names:Record<string,string>={
    length:tr('chiều dài','length'),time:tr('thời gian','time'),mass:tr('khối lượng','mass'),
    temperature:tr('nhiệt độ','temperature'),current:tr('dòng điện','electric current'),
    substance:tr('lượng chất','amount of substance'),luminosity:tr('cường độ sáng','luminous intensity')
  };
  return dimension==='dimensionless'?tr('không thứ nguyên','dimensionless'):
    dimension.replace(/\[([^\]]+)\]/g,(token,name:string)=>names[name]??token);
}

function MemorySource({memoryId,attemptId,index}:{memoryId:string,attemptId:string,index:number}){
  const [open,setOpen]=useState(false),[item,setItem]=useState<Evidence|null>(null),[error,setError]=useState('');
  async function toggle(){
    setOpen(!open);
    if(open)return;
    setItem(null);
    setError('');
    try{setItem(await api<Evidence>(`memories/${memoryId}/evidence/${attemptId}`))}
    catch(err){setError(String(err))}
  }
  return <li><button type="button" aria-expanded={open} onClick={toggle}>{tr('Xem lần làm','View attempt')} {index+1}</button>
    {open&&(item?<div>
      <p>{renderMath(item.prompt)}</p>
      <p><b>{tr('Đáp án đã nộp','Submitted answer')}</b> {renderMath(item.answer)}</p>
      <p>{item.correct?tr('Chính xác.','Correct.'):tr('Chưa đúng.','Incorrect.')} {renderMath(item.explanation)}</p>
      {item.observed_at&&<time dateTime={item.observed_at}>{new Date(item.observed_at).toLocaleString(language)}</time>}
    </div>:error?<p role="alert">{error}</p>:<p>{tr('Đang tải nguồn…','Loading source…')}</p>)}
  </li>;
}

function MemorySources({item}:{item:Memory}){
  return item.evidence.length>0&&<ul>{item.evidence.map((ref,i)=>
    <MemorySource key={ref.attempt_id} memoryId={item.id} attemptId={ref.attempt_id} index={i}/>)}</ul>;
}

export function MemoriesUsed({references,epoch,manage}:{references:MemoryRef[],epoch:number,manage:(ref:MemoryRef)=>void}){
  const [open,setOpen]=useState(false);
  const [resolved,setResolved]=useState<{epoch:number,items:(Memory|null)[]}|null>(null);
  useEffect(()=>{
    if(!open)return;
    let live=true;
    setResolved(null);
    Promise.all(references.map(ref=>api<Memory>(`memories/${encodeURIComponent(ref.id)}?revision=${ref.revision}`)
      .catch(()=>null))).then(items=>{if(live)setResolved({epoch,items})});
    return()=>{live=false};
  },[epoch,open,references]);
  return <details onToggle={e=>setOpen(e.currentTarget.open)}>
    <summary>{tr('Ký ức đã dùng','Memories used')}</summary>
    {open&&(resolved?.epoch===epoch?resolved.items.map((item,index)=>item?<div key={item.id}>
      <p>{item.statement}</p>
      <MemorySources item={item}/>
      <button type="button" onClick={()=>manage(references[index])}>{tr('Mở ký ức trong Cài đặt','Open memory in Settings')}</button>
    </div>:<p key={references[index].id}>{tr('Ký ức này không còn khả dụng.','This memory is no longer available.')}</p>):
      <p role="status">{tr('Đang đọc bộ nhớ…','Loading memories…')}</p>)}
  </details>;
}

export function MemorySettings({onMemoryPolicyChange,focusMemory}:{onMemoryPolicyChange:()=>void,focusMemory?:MemoryRef}){
  const [data,setData]=useState<MemoryList|null>(null),[busy,setBusy]=useState(false),[error,setError]=useState('');
  const [kind,setKind]=useState<MemoryKind>('goal'),[statement,setStatement]=useState('');
  const [edit,setEdit]=useState<{id:string,text:string}|null>(null),[forget,setForget]=useState<string|null>(null);
  const target=useRef<HTMLElement>(null);
  const loaded=data!==null;
  const found=data?.memories.some(item=>item.id===focusMemory?.id&&item.revision===focusMemory.revision);
  useEffect(()=>{
    if(loaded&&focusMemory)target.current?.focus();
  },[focusMemory,loaded]);
  async function update(load:()=>Promise<MemoryList>,done?:()=>void){
    setBusy(true);
    setError('');
    try{setData(await load());done?.()}
    catch(err){setError(String(err))}
    finally{setBusy(false)}
  }
  const load=()=>api<MemoryList>('memories');
  useEffect(()=>{void update(load)},[]);
  const labels={goal:tr('Mục tiêu','Goal'),preference:tr('Sở thích học tập','Preference'),
    recurring_mistake:tr('Lỗi dùng đơn vị','Unit mistake')};
  const statuses={tentative:tr('Tạm thời','Tentative'),recurring:tr('Lặp lại','Recurring'),
    resolved:tr('Đã khắc phục','Resolved'),confirmed:tr('Bạn xác nhận','Learner confirmed')};
  const encoder={
    missing:tr('Chưa bật bộ mã hóa cục bộ.','Local encoder is unavailable.'),
    building:tr('Đang chuẩn bị chỉ mục ký ức…','Building the memory index…'),
    ready:tr('Bộ mã hóa cục bộ đã sẵn sàng.','Local encoder is ready.'),
    error:tr('Bộ mã hóa gặp lỗi. Gia sư vẫn có thể dùng ngữ cảnh bài học.','The encoder encountered an error. The tutor can still use lesson context.')
  };
  return <section className="memory-settings" aria-labelledby="memory-title">
    <h3 id="memory-title">{tr('Bộ nhớ học tập','Learner memory')}</h3>
    {data&&<>
      <label className="inline"><input type="checkbox" checked={data.enabled} disabled={busy}
        onChange={e=>{const enabled=e.target.checked;void update(()=>api('memories/capture',{enabled},'PUT'),onMemoryPolicyChange)}}/>
        {tr('Bật bộ nhớ học tập','Enable learner memory')}</label>
      <p>{tr('Tắt bộ nhớ để tạm dừng ghi nhận và sử dụng bộ nhớ. Bạn vẫn có thể xem, sửa hoặc quên các mục đã lưu.','Turn memory off to pause collection and use. You can still review, edit, or forget saved memories.')}</p>
      <p>{tr('Khi bật và bộ mã hóa đã sẵn sàng, ký ức liên quan có thể được gửi tới nhà cung cấp AI đã chọn để trả lời câu hỏi.','When enabled and the local encoder is ready, relevant memories may be sent to your selected AI provider to answer a question.')}</p>
      <p role="status">{data.encoder_status==='building'&&!data.enabled?
        tr('Bộ mã hóa sẽ khởi động khi bạn bật ký ức.','The local encoder starts when you enable memory.'):
        encoder[data.encoder_status??'missing']}</p>
      {data.enabled&&data.encoder_status==='building'&&<button type="button" disabled={busy}
        onClick={()=>void update(load)}>{tr('Kiểm tra trạng thái bộ mã hóa','Check encoder status')}</button>}
      {focusMemory&&!found&&<p ref={node=>{target.current=node}} tabIndex={-1}>{tr('Ký ức này không còn khả dụng.','This memory is no longer available.')}</p>}
      {data.enabled&&<form onSubmit={e=>{e.preventDefault();void update(()=>api('memories',{kind,statement}),()=>setStatement(''))}}>
        <label>{tr('Loại bộ nhớ','Memory type')}<select disabled={busy} value={kind} onChange={e=>setKind(e.target.value as MemoryKind)}>
          <option value="goal">{labels.goal}</option><option value="preference">{labels.preference}</option>
        </select></label>
        <label>{tr('Nội dung bộ nhớ','Memory text')}<textarea required disabled={busy} maxLength={2000} value={statement} onChange={e=>setStatement(e.target.value)}/></label>
        <button disabled={busy||!statement.trim()}>{tr('Lưu bộ nhớ','Save memory')}</button>
      </form>}
      {data.memories.map(item=><article className="memory-item" key={item.id}
        ref={item.id===focusMemory?.id&&item.revision===focusMemory.revision?target:undefined} tabIndex={-1}>
        <h4>{labels[item.kind]}</h4>
        <p className="memory-meta">{statuses[item.status]} · {item.roadmap_id?
          item.roadmap_title||tr('Lộ trình đã lưu','Saved roadmap'):tr('Mọi lộ trình','All roadmaps')}
          {item.dimension&&<> · {tr('Loại đại lượng','Expected dimension')} {dimensionName(item.dimension)}</>}</p>
        <p>{item.statement}</p>
        <MemorySources key={item.revision} item={item}/>
        {edit?.id===item.id?<form onSubmit={e=>{e.preventDefault();void update(
          ()=>api(`memories/${item.id}`,{statement:edit.text,revision:item.revision},'PATCH'),()=>{setEdit(null);onMemoryPolicyChange()})}}>
          <label>{tr('Nội dung chỉnh sửa','Edited memory')}<textarea required disabled={busy} maxLength={2000} value={edit.text}
            onChange={e=>setEdit({id:item.id,text:e.target.value})}/></label>
          <div className="actions"><button disabled={busy||!edit.text.trim()}>{tr('Lưu thay đổi','Save changes')}</button>
            <button type="button" disabled={busy} onClick={()=>setEdit(null)}>{tr('Hủy','Cancel')}</button></div>
        </form>:forget===item.id?<div>
          <p>{tr('Bộ nhớ và bằng chứng kèm theo sẽ bị xóa. Các lần làm bài và cuộc trò chuyện gốc vẫn còn trong lịch sử học.','This removes the memory and its attached evidence. Original quiz attempts and conversations stay in your study history.')}</p>
          <div className="actions"><button type="button" disabled={busy} onClick={()=>void update(
            ()=>api(`memories/${item.id}?revision=${item.revision}`,undefined,'DELETE'),()=>{setForget(null);onMemoryPolicyChange()})}>{tr('Xác nhận quên','Confirm forget')}</button>
            <button type="button" disabled={busy} onClick={()=>setForget(null)}>{tr('Hủy','Cancel')}</button></div>
        </div>:<div className="actions">
          <button type="button" disabled={busy} onClick={()=>{setForget(null);setEdit({id:item.id,text:item.statement})}}>{tr('Sửa bộ nhớ','Edit memory')}</button>
          <button type="button" disabled={busy} onClick={()=>{setEdit(null);setForget(item.id)}}>{tr('Quên bộ nhớ','Forget memory')}</button>
        </div>}
      </article>)}
    </>}
    {!data&&!error&&<p>{tr('Đang đọc bộ nhớ…','Loading memories…')}</p>}
    {error&&<div><p role="alert">{error}</p><button type="button" disabled={busy} onClick={()=>void update(load)}>{tr('Tải lại bộ nhớ','Refresh memories')}</button></div>}
  </section>;
}
