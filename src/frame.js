// This trusted bridge is embedded in an opaque-origin iframe. Generated code runs inside JSInterpreter.
let engine;
const tr = (vi, en) => document.documentElement.lang === 'en' ? en : vi;
const container = document.querySelector('main');
const attrs = 'x y cx cy x1 x2 y1 y2 width height r d points fill stroke opacity transform'.split(' ');
function element(id) {
  const target = container.querySelector('#'+CSS.escape(String(id)));
  if (!target) throw Error(tr('Không tìm thấy phần tử ', 'Element not found: ')+id);
  return target;
}
function execute(code) {
  engine.appendCode(code);
  let steps = 0;
  while (engine.step()) if (++steps > 40000) throw Error(tr('Mã minh họa vượt giới hạn bước.', 'Illustration code exceeded its step limit.'));
}
function render(values) {
  if (!Array.isArray(values) || values.length !== 4 || !values.every(Number.isFinite)) throw Error(tr('Sai dữ liệu mô phỏng.', 'Invalid simulation data.'));
  execute('render('+values.join(',')+');');
}
window.addEventListener('message', e=>{
  if (e.source !== parent) return;
  try {
    if(e.data.type==='init'){
      const v=e.data.item;
      const allowed='div span p strong svg g line rect circle path text polyline'.split(' ');
      const clean=DOMPurify.sanitize(v.html,{ALLOWED_TAGS:allowed,ALLOWED_ATTR:[...attrs,'class','id','viewBox','stroke-width','font-size','text-anchor'],ALLOW_DATA_ATTR:false});
      if(DOMPurify.removed.some(r=>r.element && r.element.nodeName!=='BODY' || r.attribute)) throw Error(tr('HTML chứa phần tử hoặc thuộc tính ngoài danh sách cho phép.', 'Illustration HTML contains an unsupported element or attribute.'));
      container.innerHTML=clean;
      if(!container.firstElementChild) throw Error(tr('Minh họa không có hình.', 'The illustration is empty.'));
      const sheet=document.querySelector('style').sheet;
      for(const match of v.css.matchAll(/([^{}]+)\{([^{}]*)\}/g)){
        const selector=match[1].trim();
        if(!/^[#.]?[\w-]+$/.test(selector)) continue;
        const rule=sheet.cssRules[sheet.insertRule(selector+'{}',sheet.cssRules.length)];
        for(const pair of match[2].split(';')){
          const [key,val]=pair.split(':').map(s=>s.trim());
          if(/^(color|background-color|fill|stroke|font-size|font-weight|padding|margin|border|width|height)$/.test(key) && /^[\w#.,% -]+$/.test(val)) rule.style.setProperty(key,val);
        }
      }
      engine=new JSInterpreter(v.js,(vm,scope)=>{
        function expose(name,fn){vm.setProperty(scope,name,vm.createNativeFunction(fn));}
        expose('text',(id,value)=>{element(id).textContent=String(value).slice(0,2000);});
        expose('attr',(id,name,value)=>{
          if(!attrs.includes(name)|| /url\s*\(/i.test(String(value))) throw Error(tr('Thuộc tính không hợp lệ.', 'Invalid attribute.'));
          element(id).setAttribute(name,String(value).slice(0,8000));
        });
      });
      render(e.data.values);
      render(e.data.testValues);
      render(e.data.values);
      parent.postMessage({type:'ready'},'*');
    }else if(e.data.type==='draw' && engine) render(e.data.values);
  }catch(error){parent.postMessage({type:'failed',error:String(error).slice(0,500)},'*');}
});
