import {chromium} from 'playwright-core';
import {spawn, spawnSync} from 'node:child_process';
import {existsSync, mkdtempSync} from 'node:fs';
import {join} from 'node:path';
import {tmpdir} from 'node:os';
import assert from 'node:assert/strict';
import {once} from 'node:events';
import {createServer} from 'node:net';

const portFinder=createServer().listen(0,'127.0.0.1');
await once(portFinder,'listening');
const port=portFinder.address().port;
await new Promise(resolve=>portFinder.close(resolve));
const base='http://127.0.0.1:'+port;
const py=process.platform==='win32'?'.venv/Scripts/python.exe':'.venv/bin/python';
const env={...process.env,STUDY_DATA:mkdtempSync(join(tmpdir(),'study-ui-')),OPENAI_API_KEY:''};
const seeded=spawnSync(py,['-c',`
from backend import main
key = 'lesson:physics:free-fall'
doc = main.get(key)
doc['quiz'].append(dict(kind='number', prompt='What is the second distance?', choices=[], answer='42 m', explanation='42 metres.'))
main.put(key, doc)
`],{env,encoding:'utf8'});
assert.equal(seeded.status,0,seeded.stderr||String(seeded.error||''));
const server=spawn(py,['-m','uvicorn','backend.main:app','--port',String(port)],{env,stdio:['ignore','ignore','inherit']});
const executablePath=process.env.CHROME_PATH||['C:/Program Files/Google/Chrome/Application/chrome.exe','/usr/bin/google-chrome','/usr/bin/chromium'].find(existsSync);
let browser;
try{
  for(let i=0;i<100;i++){try{if((await fetch(base+'/api/roads')).ok)break}catch{}await new Promise(r=>setTimeout(r,100))}
  browser=await chromium.launch({executablePath,headless:true});
  const page=await browser.newPage();
  page.on('pageerror',err=>console.error('Browser error:',err.message));
  const modelId='codex-visual-fixture';
  let agyCatalog=[{id:'gemini-agy-fixture',name:'Fixture Antigravity'},{id:'agy-second-fixture',name:'Other model'}];
  let agyLoads=0;
  await page.route('**/api/settings/models/codex',route=>route.fulfill({
    json:[{id:modelId,name:'Codex Visual Fixture'}]
  }));
  await page.route('**/api/settings/models/agy',route=>{
    agyLoads++;
    return route.fulfill({json:agyCatalog});
  });
  await page.route('**/api/settings',async route=>{
    if(route.request().method()!=='GET')return route.continue();
    const response=await route.fetch();
    const settings=await response.json();
    await route.fulfill({response,json:{...settings,codex_models:[{id:modelId,name:'Codex Visual Fixture'}]}});
  });
  await page.goto(base);
  const settingsButton=page.getByRole('button',{name:'Cài đặt',exact:true});
  await settingsButton.click();
  await page.getByLabel('Nguồn AI').selectOption('codex');
  const modelSelect=page.getByLabel('Model Codex');
  await modelSelect.selectOption(modelId);
  await page.getByLabel('Model minh họa').selectOption(modelId);
  await page.getByRole('button',{name:'Lưu cài đặt'}).click();
  await page.getByRole('dialog').waitFor({state:'hidden'});
  await page.reload();
  await settingsButton.click();
  assert.equal(await page.getByLabel('Nguồn AI').inputValue(),'codex');
  assert.equal(await page.getByLabel('Model Codex').inputValue(),modelId);
  await page.getByLabel('Model minh họa').locator(`option[value="${modelId}"]`).waitFor({state:'attached'});
  assert.equal(await page.getByLabel('Model minh họa').inputValue(),modelId);
  await page.getByLabel('Nguồn AI').selectOption('openai');
  await page.getByLabel('Model minh họa').fill('fixture-visual-model');
  if(process.platform==='win32'){
    await page.getByLabel('OpenAI API key',{exact:true}).fill('offline-test-secret');
    await page.getByRole('button',{name:'Lưu cài đặt'}).click();
    await page.getByRole('dialog').waitFor({state:'hidden'});
    const publicSettings=await (await fetch(base+'/api/settings')).text();
    assert.equal(JSON.parse(publicSettings).saved_key,true);
    assert.equal(JSON.parse(publicSettings).openai_visual_model,'fixture-visual-model');
    assert.ok(!publicSettings.includes('offline-test-secret'));
    await settingsButton.click();
    await page.getByLabel('Xóa khóa đã lưu trên máy').check();
  }
  await page.getByRole('button',{name:'Lưu cài đặt'}).click();
  await page.getByRole('dialog').waitFor({state:'hidden'});
  await settingsButton.click();
  await page.getByLabel('Nguồn AI').selectOption('gemini');
  await page.getByLabel('Nguồn minh họa').selectOption('agy');
  await page.getByLabel('Model Gemini').fill('gemini-lesson-fixture');
  await page.getByLabel('Tìm theo tên hoặc ID').fill('Fixture Antigravity');
  const visualSelect=page.getByLabel('Model minh họa');
  await visualSelect.locator('option[value="gemini-agy-fixture"]').waitFor({state:'attached'});
  assert.deepEqual(await visualSelect.locator('option:not([disabled])').evaluateAll(options=>options.map(o=>o.value)),
                   ['gemini-agy-fixture']);
  await page.getByLabel('Tìm theo tên hoặc ID').fill('gemini-agy-fixture');
  await visualSelect.selectOption('gemini-agy-fixture');
  if(process.platform==='win32')await page.getByLabel('Gemini API key').fill('fixture-google-secret');
  await page.getByRole('button',{name:'Lưu cài đặt'}).click();
  await page.getByRole('dialog').waitFor({state:'hidden'});
  const googleSettings=await (await fetch(base+'/api/settings')).text();
  assert.equal(JSON.parse(googleSettings).google_saved_key,process.platform==='win32');
  assert.ok(!googleSettings.includes('fixture-google-secret'));
  await page.reload();
  await settingsButton.click();
  assert.equal(await page.getByLabel('Nguồn AI').inputValue(),'gemini');
  assert.equal(await page.getByLabel('Nguồn minh họa').inputValue(),'agy');
  assert.equal(await page.getByLabel('Model Gemini').inputValue(),'gemini-lesson-fixture');
  await visualSelect.locator('option[value="gemini-agy-fixture"]').waitFor({state:'attached'});
  assert.equal(await page.getByLabel('Model minh họa').inputValue(),'gemini-agy-fixture');
  agyCatalog=[{id:'agy-second-fixture',name:'Other model'}];
  await page.getByRole('button',{name:'Làm mới model minh họa'}).click();
  await page.getByText(/gemini-agy-fixture.*không có trong danh sách/).waitFor();
  assert.deepEqual(await visualSelect.locator('option:not([disabled])').evaluateAll(options=>options.map(o=>o.value)),
                   ['agy-second-fixture']);
  assert.ok(agyLoads>=3);
  if(process.platform==='win32')await page.getByLabel('Xóa khóa Gemini đã lưu').check();
  await page.getByRole('button',{name:'Lưu cài đặt'}).click();
  await page.getByRole('dialog').waitFor({state:'hidden'});
  await settingsButton.click();
  await page.getByLabel('Nguồn AI').selectOption('openai');
  await page.getByLabel('Nguồn minh họa').selectOption('');
  await page.getByRole('button',{name:'Lưu cài đặt'}).click();
  await page.getByRole('dialog').waitFor({state:'hidden'});
  const time=page.getByRole('slider',{name:'Thời gian'});
  await page.waitForFunction(()=>document.querySelector('input[type=range]')?.disabled===false,null,{timeout:10000}).catch(async e=>{console.error(await page.locator('figure').innerText());throw e});
  await time.fill('120');
  await page.getByText('19,62 m',{exact:true}).first().waitFor();
  await page.getByRole('button',{name:'Phát',exact:true}).click();
  await page.getByRole('button',{name:'Dừng',exact:true}).click();
  await time.fill('120');
  await page.getByText('Điều chỉnh điều kiện ban đầu').click();
  await page.getByLabel('Gia tốc (m/s²)').fill('5');
  await page.getByRole('button',{name:'Áp dụng'}).click();
  await page.getByText('10 m',{exact:true}).waitFor();
  await page.locator('[data-block=i0]').evaluate(el=>{const range=document.createRange();range.selectNodeContents(el);const s=getSelection();s.removeAllRanges();s.addRange(range);el.dispatchEvent(new MouseEvent('mouseup',{bubbles:true}))});
  await page.locator('#tutor').waitFor();
  assert.match(await page.locator('#tutor small').innerText(),/s = 10/);
  await page.getByRole('button',{name:'Ẩn gia sư'}).click();
  await page.getByLabel('Đáp số và đơn vị').fill('1962 cm');
  await page.getByRole('button',{name:'Kiểm tra đáp án'}).first().click();
  await page.getByText('Chính xác.',{exact:true}).waitFor();
  await page.reload();
  await page.getByText('Chính xác.',{exact:true}).waitFor();
  await page.locator('mark').first().click();
  await page.locator('#tutor').waitFor();
  await page.getByRole('button',{name:'Ẩn gia sư'}).click();
  await page.getByRole('button',{name:'Tạo lộ trình'}).first().click();
  await page.getByLabel('Mục tiêu học').fill('Đọc đồ thị');
  await page.getByRole('button',{name:'Tạo bản nháp'}).click();
  await page.getByRole('alert').filter({hasText:'OPENAI_API_KEY'}).waitFor();
  await page.getByRole('button',{name:'Đóng',exact:true}).click();
  await page.setViewportSize({width:375,height:820});
  assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
  // Simulate a malformed generated artifact, then a manual code-only repair.
  let good, repairs=0;
  await page.route('**/api/lesson/vat-ly/roi-tu-do',async route=>{
    const response=await route.fetch(), b=await response.json();
    good=b.doc.illustrations[0];
    b.doc.illustrations[0]={...good,html:'<img src="https://invalid.example/illustration.png">'};
    await route.fulfill({json:b});
  });
  await page.route('**/api/repair/**',async route=>{
    repairs++;
    if(!route.request().postDataJSON().manual)await route.fulfill({status:502,json:{detail:'Lỗi sửa minh họa'}});
    else await route.fulfill({json:good});
  });
  const external=[];
  page.on('request',request=>{if(request.url().includes('invalid.example'))external.push(request.url())});
  await page.reload();
  await page.getByText('Error: Lỗi sửa minh họa',{exact:false}).first().waitFor();
  await page.getByRole('button',{name:'Tạo lại minh họa'}).click();
  await page.waitForFunction(()=>document.querySelector('input[type=range]')?.disabled===false);
  assert.equal(repairs,2);
  assert.deepEqual(external,[]);
  await page.getByLabel('Ngôn ngữ').selectOption('en');
  await page.getByRole('heading',{name:'Free fall',exact:true}).waitFor();
  const question=page.locator('#quiz form').first();
  await question.getByLabel('Answer and unit').fill('1962 cm');
  await question.getByRole('button',{name:'Check answer'}).click();
  await question.getByText('Correct.',{exact:true}).waitFor();
  await page.reload();
  await question.getByText('Correct.',{exact:true}).waitFor();
  assert.equal(await page.locator('html').getAttribute('lang'),'en');
  const tutor=page.locator('#tutor');
  const conversations=new Map([['main',[{role:'user',text:'First question'},{role:'assistant',text:'First reply'}]]]);
  const inlineFormula='\\(t = 2\\)';
  const equation='\\[s = \\frac{1}{2}at^2\\]';
  const formulaLesson='At '+inlineFormula+', distance follows '+equation;
  let formulaHighlight;
  await page.route('**/api/lesson/physics/free-fall',async route=>{
    const b=await (await route.fetch()).json();
    b.doc.sections[0].text=formulaLesson;
    await route.fulfill({json:b});
  });
  await page.route('**/api/notes/physics/free-fall',async route=>{
    formulaHighlight=route.request().postDataJSON();
    await route.fulfill({json:{...formulaHighlight,id:'formula-highlight'}});
  });
  const submissions=[];
  const {promise:firstReply,resolve:releaseFirstReply}=Promise.withResolvers();
  await page.route('**/api/chat/physics/free-fall',route=>route.fulfill({json:[...conversations].reverse().map(([id,messages])=>({id,question:messages[0].text}))}));
  await page.route('**/api/chat/physics/free-fall/*',async route=>{
    const id=new URL(route.request().url()).pathname.split('/').at(-1);
    const previous=conversations.get(id)||[];
    if(route.request().method()==='GET')return route.fulfill({json:previous});
    const send=route.request().postDataJSON();
    submissions.push(send);
    if(submissions.length===1){
      await firstReply;
      return route.fulfill({status:409,json:{detail:'Please retry.'}});
    }
    const reply=send.text==='How far did it fall?'?{text:equation+'\nThe object falls 19.62 m.',
      sources:[{title:'Formula source',url:'https://example.com/formula',end:8}]}:{text:'Reply to '+send.text};
    previous.push({role:'user',text:send.text},{role:'assistant',...reply});
    conversations.set(id,previous);
    await route.fulfill({json:previous});
  });
  await page.reload();
  const formulaBlock=page.locator('[data-block=s0]');
  await formulaBlock.locator('.math-display .mfrac').waitFor();
  assert.equal(await formulaBlock.locator('math').count(),2);
  await formulaBlock.evaluate(el=>{
    const glyph=el.querySelector('.math-display .katex-html .mord');
    const range=document.createRange();
    range.selectNodeContents(glyph);
    const selection=getSelection();
    selection.removeAllRanges();
    selection.addRange(range);
    el.dispatchEvent(new MouseEvent('mouseup',{bubbles:true}));
  });
  await tutor.locator('blockquote math').waitFor({state:'attached'});
  assert.equal(formulaHighlight.quote,equation);
  assert.equal(formulaHighlight.start,formulaLesson.indexOf(equation));
  assert.equal(formulaHighlight.end,formulaLesson.length);
  assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
  await tutor.getByRole('button',{name:'Hide tutor'}).click();
  await tutor.waitFor({state:'hidden'});
  await page.setViewportSize({width:1440,height:900});
  const openTutor=page.getByRole('button',{name:'Ask the tutor',exact:true});
  await openTutor.click();
  const readerRect=await page.locator('article').boundingBox(), tutorRect=await tutor.boundingBox();
  assert.ok(readerRect.x+readerRect.width<=tutorRect.x+1);
  await tutor.getByRole('button',{name:'First question'}).click();
  await tutor.getByText('First reply',{exact:true}).waitFor();
  await tutor.getByRole('button',{name:'New question',exact:false}).click();
  await tutor.getByRole('textbox').fill('How far did it fall?');
  await tutor.getByRole('button',{name:'Send question'}).click();
  const loading=tutor.getByRole('status').filter({hasText:'Tutor is thinking…'});
  await loading.waitFor();
  const dot=loading.locator('.dots i').first();
  assert.equal(await dot.evaluate(el=>getComputedStyle(el).animationName),'ai-bounce');
  await page.emulateMedia({reducedMotion:'reduce'});
  assert.equal(await dot.evaluate(el=>getComputedStyle(el).animationName),'none');
  await page.emulateMedia({reducedMotion:'no-preference'});
  releaseFirstReply();
  await tutor.getByRole('alert').getByText('Please retry.',{exact:false}).waitFor();
  await loading.waitFor({state:'hidden'});
  assert.equal(await tutor.getByRole('textbox').inputValue(),'How far did it fall?');
  await tutor.getByRole('button',{name:'Send question'}).click();
  await tutor.getByText('The object falls 19.62 m.',{exact:false}).waitFor();
  await tutor.locator('.math-display .mfrac').waitFor();
  assert.ok(await tutor.getByRole('link',{name:'[Formula source]'}).isVisible());
  assert.match(submissions[0].request_id,/^[0-9a-f-]{36}$/);
  assert.deepEqual(submissions[0],submissions[1]);
  await tutor.getByRole('textbox').fill('Why?');
  await tutor.getByRole('button',{name:'Send question'}).click();
  await tutor.getByText('Reply to Why?',{exact:true}).waitFor();
  await tutor.getByRole('button',{name:'New question',exact:false}).click();
  await tutor.getByRole('textbox').fill('What is acceleration?');
  await tutor.getByRole('button',{name:'Send question'}).click();
  await tutor.getByText('Reply to What is acceleration?',{exact:true}).waitFor();
  assert.equal(await tutor.locator('.msg').count(),2);
  await page.reload();
  await openTutor.click();
  await tutor.getByRole('button',{name:'How far did it fall?',exact:true}).click();
  await tutor.getByText('The object falls 19.62 m.',{exact:false}).waitFor();
  await tutor.getByText('Reply to Why?',{exact:true}).waitFor();
  assert.equal(await tutor.locator('.msg').count(),4);
  await tutor.press('Escape');
  await tutor.waitFor({state:'hidden'});
  const englishSettings=page.getByRole('button',{name:'Settings',exact:true});
  const memoryDialog=page.getByRole('dialog');
  const memoryList=async()=>{
    const response=await fetch(base+'/api/memories',{headers:{'X-Study-Language':'en'}});
    assert.ok(response.ok);
    return response.json();
  };
  const waitForMemory=async status=>{
    for(let i=0;i<100;i++){
      const entry=(await memoryList()).memories.find(m=>m.status===status);
      if(entry)return entry;
      await new Promise(resolve=>setTimeout(resolve,100));
    }
    assert.fail(`No learner memory reached status ${status}`);
  };

  await englishSettings.click();
  await memoryDialog.getByRole('heading',{name:'Learner memory',exact:true}).waitFor();
  const capture=memoryDialog.getByRole('checkbox',{name:'Enable learner memory'});
  assert.equal(await capture.isChecked(),false);
  await capture.focus();
  await page.keyboard.press('Space');
  await memoryDialog.getByLabel('Memory type').selectOption('goal');
  const memoryText=memoryDialog.getByRole('textbox',{name:/^Memory text/});
  await memoryText.fill('Practice converting units');
  let saves=0;
  await page.route('**/api/memories',route=>{
    if(route.request().method()==='POST'&&saves++===0)
      return route.fulfill({status:502,json:{detail:'Memory save interrupted.'}});
    return route.continue();
  });
  await memoryDialog.getByRole('button',{name:'Save memory',exact:true}).click();
  await memoryDialog.getByRole('alert').filter({hasText:'Memory save interrupted.'}).waitFor();
  assert.equal(await memoryText.inputValue(),'Practice converting units');
  await memoryDialog.getByRole('button',{name:'Save memory',exact:true}).click();
  await memoryDialog.getByText('Practice converting units',{exact:true}).waitFor();
  await page.unroute('**/api/memories');
  await memoryDialog.getByLabel('Memory type').selectOption('preference');
  await memoryText.fill('Show the conversion step');
  await memoryDialog.getByRole('button',{name:'Save memory',exact:true}).click();
  await memoryDialog.getByText('Show the conversion step',{exact:true}).waitFor();
  await memoryDialog.getByRole('button',{name:'Close',exact:true}).click();

  const quizPath='**/api/quiz/physics/free-fall';
  const attempts=[];
  await page.route(quizPath,async route=>{
    attempts.push(route.request().postDataJSON());
    const response=await route.fetch();
    assert.ok(response.ok());
    if(attempts.length===1)await route.fulfill({status:502,json:{detail:'Quiz response lost.'}});
    else await route.fulfill({response});
  });
  const firstDistance=page.locator('#quiz form').first();
  await firstDistance.getByLabel('Answer and unit').fill('19.62 s');
  await firstDistance.getByRole('button',{name:'Check answer'}).click();
  await page.getByRole('alert').filter({hasText:'Quiz response lost.'}).waitFor();
  assert.equal(await firstDistance.getByLabel('Answer and unit').inputValue(),'19.62 s');
  await firstDistance.getByRole('button',{name:'Check answer'}).click();
  await firstDistance.getByText('Try again.',{exact:true}).waitFor();
  assert.match(attempts[0].attempt_id,/^[0-9a-f-]{36}$/);
  assert.deepEqual(attempts[0],attempts[1]);
  await page.unroute(quizPath);
  const secondDistance=page.locator('#quiz form').filter({hasText:'What is the second distance?'});
  await secondDistance.getByLabel('Answer and unit').fill('42 s');
  await secondDistance.getByRole('button',{name:'Check answer'}).click();
  await secondDistance.getByText('Try again.',{exact:true}).waitFor();
  const recurring=await waitForMemory('recurring');
  assert.equal(recurring.evidence.length,2);
  const englishMemoryThread=[{role:'user',text:'My unit mistake'},{role:'assistant',text:'Review units.',
    memory_refs:[{id:recurring.id,revision:recurring.revision}]}];
  conversations.set('phase3-verification',englishMemoryThread);
  await openTutor.click();
  await tutor.getByRole('button',{name:'My unit mistake',exact:true}).click();
  const memoriesUsed=tutor.getByText('Memories used',{exact:true});
  await memoriesUsed.press('Enter');
  await tutor.getByRole('button',{name:'View attempt 1',exact:true}).press('Enter');
  await tutor.getByText('19.62 s',{exact:false}).waitFor();
  await tutor.getByRole('button',{name:'Open memory in Settings',exact:true}).press('Enter');
  const mistake=memoryDialog.locator('article').filter({hasText:recurring.statement});
  await mistake.waitFor();
  await page.waitForFunction(item=>item===document.activeElement,await mistake.elementHandle());
  if(process.env.STUDY_VERIFICATION_ARTIFACTS)
    await page.screenshot({path:join(process.env.STUDY_VERIFICATION_ARTIFACTS,'verification-memory-settings-en.png')});
  await memoryDialog.getByRole('button',{name:'View attempt 1',exact:true}).click();
  await memoryDialog.getByText('19.62 s',{exact:false}).waitFor();
  await memoryDialog.getByRole('button',{name:'View attempt 2',exact:true}).click();
  await memoryDialog.getByText('42 s',{exact:false}).waitFor();
  await mistake.getByRole('button',{name:'Edit memory',exact:true}).click();
  await mistake.getByRole('textbox',{name:/^Edited memory/}).fill('Review dimensional compatibility first');
  await mistake.getByRole('button',{name:'Save changes',exact:true}).click();
  await memoryDialog.getByText('Review dimensional compatibility first',{exact:true}).waitFor();
  await memoryDialog.getByRole('button',{name:'Close',exact:true}).press('Enter');
  await tutor.getByText('This memory is no longer available.',{exact:true}).waitFor();
  await tutor.getByText('Review units.',{exact:true}).waitFor();
  await englishSettings.click();
  const [pauseResponse]=await Promise.all([
    page.waitForResponse(response=>response.url().endsWith('/api/memories/capture')&&response.request().method()==='PUT'),
    capture.press('Space'),
  ]);
  assert.ok(pauseResponse.ok());
  await page.reload();
  await englishSettings.click();
  await memoryDialog.getByText('Review dimensional compatibility first',{exact:true}).waitFor();
  assert.equal(await capture.isChecked(),false);
  await memoryDialog.getByRole('button',{name:'Close',exact:true}).click();

  await page.getByLabel('Language').selectOption('vi');
  await page.getByRole('heading',{name:'Sự rơi tự do',exact:true}).waitFor();
  const correctedMemory=(await memoryList()).memories.find(item=>item.id===recurring.id);
  const viThread=[{role:'user',text:'Lỗi đơn vị'},{role:'assistant',text:'Ôn đơn vị.',
    memory_refs:[{id:correctedMemory.id,revision:correctedMemory.revision}]}];
  await page.route('**/api/chat/vat-ly/roi-tu-do',route=>route.fulfill({json:[{id:'phase3-verification',question:'Lỗi đơn vị'}]}));
  await page.route('**/api/chat/vat-ly/roi-tu-do/*',route=>route.fulfill({
    json:route.request().url().endsWith('/phase3-verification')?viThread:[]}));
  await page.getByRole('button',{name:'Hỏi gia sư',exact:true}).press('Enter');
  await tutor.getByRole('button',{name:'Lỗi đơn vị',exact:true}).press('Enter');
  await tutor.getByText('Ký ức đã dùng',{exact:true}).press('Enter');
  await tutor.getByText('Review dimensional compatibility first',{exact:true}).waitFor();
  if(process.env.STUDY_VERIFICATION_ARTIFACTS)
    await page.screenshot({path:join(process.env.STUDY_VERIFICATION_ARTIFACTS,'verification-memory-disclosure-vi.png')});
  await tutor.getByRole('button',{name:'Mở ký ức trong Cài đặt',exact:true}).press('Enter');
  await memoryDialog.getByRole('heading',{name:'Bộ nhớ học tập',exact:true}).waitFor();
  assert.equal(await memoryDialog.getByRole('checkbox',{name:'Bật bộ nhớ học tập'}).isChecked(),false);
  await memoryDialog.getByText('Practice converting units',{exact:true}).waitFor();
  await memoryDialog.getByText('Show the conversion step',{exact:true}).waitFor();
  const corrected=memoryDialog.locator('article').filter({hasText:'Review dimensional compatibility first'});
  await corrected.getByRole('button',{name:'Xem lần làm 1',exact:true}).click();
  await corrected.getByText('19.62 s',{exact:false}).waitFor();
  await corrected.getByRole('button',{name:'Quên bộ nhớ',exact:true}).click();
  await corrected.getByRole('button',{name:'Xác nhận quên',exact:true}).click();
  await corrected.waitFor({state:'detached'});
  await memoryDialog.getByRole('button',{name:'Đóng',exact:true}).press('Enter');
  await tutor.getByText('Ký ức này không còn khả dụng.',{exact:true}).waitFor();
  const original=await (await fetch(base+'/api/lesson/physics/free-fall')).json();
  assert.equal(original.progress['0'].filter(item=>item.attempt_id===attempts[0].attempt_id).length,1);
  console.log('Browser checks passed: illustration, grading, LaTeX, highlights, conversation history, tutor panel, API settings, bilingual keyboard memory disclosure, stale references, exact quiz evidence, and mobile width.');
}finally{await browser?.close();server.kill()}

