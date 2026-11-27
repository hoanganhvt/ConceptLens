import { chromium } from 'playwright-core';
import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { once } from 'node:events';
import { existsSync, mkdtempSync, readFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { delimiter, extname, join, resolve } from 'node:path';
import { performance } from 'node:perf_hooks';
import { createInterface } from 'node:readline';
import { fileURLToPath } from 'node:url';

const scripts = fileURLToPath(new URL('.', import.meta.url));
const root = resolve(scripts, '../../..');
const temp = mkdtempSync(join(tmpdir(), 'phase4c-independent-'));
const evidence = join(root, 'result', 'phase-4c', 'evidence');
const python = join(root, '.venv', 'Scripts', 'python.exe');
const origin = 'http://localhost';
const executablePath = process.env.CHROME_PATH || 'C:/Program Files/Google/Chrome/Application/chrome.exe';
const headers = { 'X-Study-Language': 'en' };
const mime = { '.js': 'text/javascript', '.css': 'text/css', '.html': 'text/html',
  '.woff': 'font/woff', '.woff2': 'font/woff2', '.ttf': 'font/ttf' };
let worker, browser;
let injectInvalidFrame = false;

function start() {
  const child = spawn(python, ['-u', join(scripts, 'offline_api.py')], {
    cwd: root,
    env: { ...process.env, STUDY_DATA: temp, OPENAI_API_KEY: '', GOOGLE_API_KEY: '', GEMINI_API_KEY: '',
      PYTHONUTF8: '1', PYTHONPATH: [join(scripts, 'windows_test_support'),
      process.env.PYTHONPATH].filter(Boolean).join(delimiter) },
    stdio: ['pipe', 'pipe', 'inherit'],
  });
  let sequence = 0;
  const pending = new Map();
  createInterface({ input: child.stdout }).on('line', line => {
    const reply = JSON.parse(line);
    const current = pending.get(reply.id);
    if (!current) return;
    pending.delete(reply.id);
    clearTimeout(current.timer);
    current.resolve(reply.data);
  });
  child.on('exit', code => {
    for (const current of pending.values()) {
      clearTimeout(current.timer);
      current.reject(new Error(`ASGI worker exited with status ${code}`));
    }
    pending.clear();
  });
  return {
    send(body) {
      const id = ++sequence;
      return new Promise((resolve, reject) => {
        const timer = setTimeout(() => {
          pending.delete(id);
          reject(new Error(`ASGI worker did not respond for ${body.op} ${body.path || ''}`));
        }, 15000);
        pending.set(id, { resolve, reject, timer });
        child.stdin.write(JSON.stringify({ id, ...body }) + '\n');
      });
    },
    async stop() {
      if (child.exitCode !== null) return;
      const exited = once(child, 'exit');
      child.stdin.end();
      const timer = setTimeout(() => child.kill(), 1500);
      await exited;
      clearTimeout(timer);
    },
  };
}

function request(path, method = 'GET', body) {
  return worker.send({ op: 'request', path, method, body, headers });
}

function asset(route, url) {
  if (url.origin !== origin) return route.abort();
  const path = join(root, 'dist', url.pathname === '/' ? 'index.html' : url.pathname);
  return existsSync(path) ? route.fulfill({ body: readFileSync(path), contentType: mime[extname(path)] || 'application/octet-stream' })
    : route.fulfill({ status: 404, body: 'missing fixture asset' });
}

function apiRoute(route) {
  const req = route.request();
  const url = new URL(req.url());
  return { op: 'request', method: req.method(), path: url.pathname + url.search,
    headers: { 'X-Study-Language': req.headers()['x-study-language'] }, body: req.postDataJSON() };
}

async function runRegression() {
  worker = start();
  await worker.send({ op: 'seed-legacy' });
  browser = await chromium.launch({ executablePath, headless: true, timeout: 12000 });
  const page = await browser.newPage();
  const apiFetch = async route => {
    const reply = await worker.send(apiRoute(route));
    return { status: reply.status, json: async () => reply.json, ok: () => reply.status < 400 };
  };
  const hostFetch = async (url, options = {}) => {
    const path = new URL(url).pathname;
    const reply = await worker.send({ op: 'request', method: 'GET', path, headers: options.headers });
    return new Response(JSON.stringify(reply.json), { status: reply.status, headers: { 'Content-Type': 'application/json' } });
  };
  await page.route('**/*', async route => {
    const url = new URL(route.request().url());
    if (url.origin === origin && url.pathname.startsWith('/api/')) {
      const response = await apiFetch(route);
      return route.fulfill({ status: response.status, json: await response.json() });
    }
    return asset(route, url);
  });
  // Reuse the maintained assertion body. The replacements touch only network transport.
  const source = readFileSync(join(root, 'tests', 'browser.mjs'), 'utf8');
  const sourceStart = source.indexOf('  const modelId=');
  const sourceEnd = source.lastIndexOf('}finally{');
  assert.ok(sourceStart >= 0 && sourceEnd > sourceStart);
  const body = source.slice(sourceStart, sourceEnd)
    .replaceAll('route.fetch()', 'apiFetch(route)')
    .replaceAll('route.continue()', 'route.fallback()')
    .replaceAll('route.fulfill({response,json:', 'route.fulfill({status:response.status,json:')
    .replaceAll('route.fulfill({response})', 'route.fulfill({status:response.status,json:await response.json()})');
  const AsyncFunction = Object.getPrototypeOf(async function () {}).constructor;
  await new AsyncFunction('page', 'base', 'fetch', 'assert', 'apiFetch', 'join', body)(
    page, origin, hostFetch, assert, apiFetch, join);
  console.log(`Shared browser assertions passed in Chromium ${browser.version()} using the stdio ASGI relay.`);
}

async function snapshot(page, name) {
  await page.screenshot({ path: join(evidence, name), animations: 'disabled' });
}

async function waitOptions(page, selector, expected) {
  await page.waitForFunction(({ selector, expected }) => {
    const label = [...document.querySelectorAll('label')].find(node => node.firstChild?.textContent === selector);
    if (!label) return false;
    const options = Array.from(label.querySelectorAll('option:not([disabled])'));
    return JSON.stringify(options.map(item => item.value)) === JSON.stringify(expected);
  }, { selector, expected }).catch(async error => {
    console.error(await page.getByRole('dialog').innerText());
    throw error;
  });
}

async function run() {
  worker = start();
  const road = await worker.send({ op: 'seed' });
  const [topic, otherTopic] = road.chapters[0].topics;
  const lessonPath = `/api/lesson/${road.id}/${topic.id}`;
  const otherPath = `/api/lesson/${road.id}/${otherTopic.id}`;
  const repairPath = `/api/repair/${road.id}/${topic.id}/0`;
  browser = await chromium.launch({ executablePath, headless: true, timeout: 12000 });
  const page = await browser.newPage({ viewport: { width: 1240, height: 900 } });
  page.setDefaultTimeout(8000);
  await page.addInitScript(({ selected, testOrigin }) => {
    if (window.top !== window || location.origin !== testOrigin) return;
    if (localStorage.getItem('language') === null) localStorage.setItem('language', 'en');
    if (localStorage.getItem('selected') === null) localStorage.setItem('selected', selected);
  }, { selected: road.id + '/' + topic.id, testOrigin: origin });
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  let external = 0;
  let duplicateRetry = null;
  await page.route('**/*', async route => {
    const req = route.request();
    const url = new URL(req.url());
    if (url.origin !== origin) {
      external += 1;
      return route.abort();
    }
    if (url.pathname.startsWith('/api/')) {
      const packet = apiRoute(route);
      let reply;
      if (url.pathname === lessonPath + '/illustrations/1' && req.method() === 'POST') {
        duplicateRetry = await worker.send({ op: 'parallel', requests: [packet, packet] });
        [reply] = duplicateRetry;
      } else {
        reply = await worker.send(packet);
      }
      if (injectInvalidFrame && url.pathname === lessonPath && req.method() === 'GET' && reply.json.doc) {
        reply.json.doc.illustrations[0].html = '<img src="https://forbidden.invalid/probe.png">';
      }
      return route.fulfill({ status: reply.status, json: reply.json });
    }
    return asset(route, url);
  });
  const started = performance.now();
  await page.goto(origin);
  await page.getByRole('button', { name: 'Start lesson' }).waitFor();

  const open = () => page.getByRole('button', { name: 'Settings', exact: true }).click();
  const save = () => page.getByRole('button', { name: 'Save settings', exact: true }).click();
  const dialog = page.getByRole('dialog');
  const refresh = page.getByRole('button', { name: 'Refresh illustration models' });
  const choose = page.getByLabel('Illustration model');
  const field = (name) => page.getByLabel(name);
  const selector = 'Illustration model';
  await open();
  await field('AI provider').selectOption('codex');
  await waitOptions(page, selector, ['codex-alpha', 'codex-beta']);
  await field('Search by name or ID').fill('Precise Codex');
  await waitOptions(page, selector, ['codex-beta']);
  await field('Search by name or ID').fill('codex-alpha');
  await waitOptions(page, selector, ['codex-alpha']);
  await field('Illustration provider').selectOption('agy');
  await waitOptions(page, selector, ['agy-alpha', 'agy-beta']);
  await field('Search by name or ID').fill('agy-beta');
  await choose.selectOption('agy-beta');
  await save();
  await dialog.waitFor({ state: 'hidden' });
  await open();
  await waitOptions(page, selector, ['agy-alpha', 'agy-beta']);
  assert.equal(await choose.inputValue(), 'agy-beta');
  await worker.send({ op: 'catalog', provider: 'agy', mode: 'removed' });
  await refresh.click();
  await page.getByText(/Saved model \(agy-beta\) is unavailable/i).waitFor();
  await waitOptions(page, selector, ['agy-alpha']);
  await snapshot(page, 'offline-model-removed.png');
  console.log('V1 PASS. Codex and agy exact catalogs, name and ID search, provider switch, reopen, refresh, removed saved ID.');

  const failures = [
    ['empty', /agy returned no models/i, 502],
    ['malformed', /agy did not return a valid model catalog/i, 502],
    ['failure', /could not list models/i, 502],
    ['timeout', /agy model catalog timed out/i, 504],
  ];
  for (const [mode, message, code] of failures) {
    await worker.send({ op: 'catalog', provider: 'agy', mode });
    await refresh.click();
    await page.getByText(message).waitFor();
    await waitOptions(page, selector, []);
    assert.ok(await choose.isDisabled());
    assert.equal((await request('/api/settings/models/agy')).status, code);
  }
  for (const [mode] of failures.slice(0, 3)) {
    await worker.send({ op: 'catalog', provider: 'codex', mode });
    const result = await request('/api/settings/models/codex');
    assert.equal(result.status, 502);
    assert.equal(Array.isArray(result.json), false);
  }
  await worker.send({ op: 'catalog', provider: 'agy', mode: 'normal' });
  await refresh.click();
  await waitOptions(page, selector, ['agy-alpha', 'agy-beta']);
  await save();
  await dialog.waitFor({ state: 'hidden' });
  await field('Language').selectOption('vi');
  await page.getByRole('button', { name: 'Cài đặt', exact: true }).click();
  await page.getByRole('button', { name: 'Làm mới model minh họa' }).waitFor();
  await page.getByRole('button', { name: 'Làm mới model minh họa' }).isEnabled();
  await worker.send({ op: 'catalog', provider: 'agy', mode: 'malformed' });
  await page.getByRole('button', { name: 'Làm mới model minh họa' }).click();
  await page.getByText('agy không trả về danh sách model hợp lệ.').waitFor();
  await snapshot(page, 'offline-catalog-vietnamese.png');
  await page.getByRole('button', { name: 'Lưu cài đặt', exact: true }).click();
  await dialog.waitFor({ state: 'hidden' });
  await page.getByLabel('Ngôn ngữ').selectOption('en');
  console.log('V2 PASS. Empty/malformed/failure/timeout leave no options; English and Vietnamese catalog errors; refresh recovers.');

  await worker.send({ op: 'fail', stage: 'prose', enabled: true });
  await page.getByRole('button', { name: 'Start lesson' }).click();
  await page.getByRole('alert').filter({ hasText: 'Failed while writing the lesson (codex)' }).waitFor();
  assert.equal((await request(lessonPath)).json.doc, null);
  await worker.send({ op: 'fail', stage: 'prose', enabled: false });
  await page.getByRole('button', { name: 'Start lesson' }).click();
  await page.getByRole('heading', { name: 'Scene A' }).waitFor();
  await page.getByRole('heading', { name: 'Scene C' }).waitFor();
  await page.getByText(/could not generate the illustration.*timed out/i).waitFor();
  const original = (await request(lessonPath)).json.doc;
  assert.deepEqual(original.illustration_status.map(s => [s.state, s.index]), [['ready', 0], ['failed', undefined], ['ready', 1]]);
  assert.ok(!Object.hasOwn(original, 'illustration_plan'));
  const firstQuiz = page.locator('#quiz form').first();
  const scene = page.getByRole('heading', { name: 'Scene C' }).locator('xpath=ancestor::figure');
  const sceneSlider = scene.getByRole('slider', { name: 'Time' });
  await sceneSlider.fill('120');
  await scene.getByText('19.62 m', { exact: true }).waitFor();
  await firstQuiz.getByLabel('Answer and unit').fill('1962 cm');
  await firstQuiz.getByRole('button', { name: 'Check answer' }).click();
  await firstQuiz.getByText('Correct.', { exact: true }).waitFor();
  await page.locator('[data-block=i1]').evaluate(el => {
    const range = document.createRange();
    range.selectNodeContents(el);
    const selection = window.getSelection();
    selection.removeAllRanges();
    selection.addRange(range);
    el.dispatchEvent(new MouseEvent('mouseup', { bubbles: true }));
  });
  await page.locator('#tutor blockquote small').filter({ hasText: 's = 19.62' }).waitFor().catch(async error => {
    console.error(JSON.stringify((await request(lessonPath)).json.notes));
    console.error(await page.getByRole('alert').allTextContents());
    throw error;
  });
  const beforeRestart = (await request(lessonPath)).json;
  assert.equal(beforeRestart.notes[0].block, 'i1');
  assert.equal(beforeRestart.notes[0].snapshot.s, 19.62);
  const initialCalls = (await worker.send({ op: 'calls' })).filter(item => ['prose', 'scene'].includes(item.stage));
  assert.deepEqual(initialCalls, [
    { stage: 'prose', provider: 'codex', model: null },
    { stage: 'prose', provider: 'codex', model: null },
    ...['scene-a', 'scene-b', 'scene-c'].map(brief => ({ stage: 'scene', provider: 'agy', model: 'agy-beta', brief })),
  ]);
  await snapshot(page, 'offline-partial-lesson.png');
  await page.goto('about:blank');
  await request(lessonPath);
  await worker.stop();
  worker = start();
  await page.goto(origin);
  await firstQuiz.getByText('Correct.', { exact: true }).waitFor();
  await page.getByRole('button', { name: 'Retry illustration' }).waitFor();
  assert.equal((await request('/api/settings')).json.agy_visual_model, 'agy-beta');
  await open();
  await waitOptions(page, selector, ['agy-alpha', 'agy-beta']);
  await choose.selectOption('agy-alpha');
  await save();
  await dialog.waitFor({ state: 'hidden' });
  await worker.send({ op: 'fail', stage: 'scene', enabled: false });
  const retryPath = lessonPath + '/illustrations/1';
  await page.getByRole('button', { name: 'Retry illustration' }).click();
  await page.getByRole('heading', { name: 'Scene B' }).waitFor();
  const [retry, replay] = duplicateRetry;
  assert.equal(retry.status, 200);
  assert.deepEqual(retry, replay);
  assert.deepEqual(retry.json.illustrations.map(item => item.title), ['Scene A', 'Scene C', 'Scene B']);
  assert.equal(retry.json.version, original.version);
  const stale = await request(retryPath, 'POST', { version: 'stale', attempts: 0 });
  assert.equal(stale.status, 409);
  await page.reload();
  await page.getByRole('heading', { name: 'Scene B' }).waitFor();
  await firstQuiz.getByText('Correct.', { exact: true }).waitFor();
  assert.equal(await page.locator('[data-block=i1] mark').count(), 1);
  const afterRetry = (await request(lessonPath)).json;
  assert.deepEqual(afterRetry.notes, beforeRestart.notes);
  assert.equal(afterRetry.progress[0][0].attempt_id, beforeRestart.progress[0][0].attempt_id);
  assert.deepEqual((await worker.send({ op: 'calls' })).filter(item => item.stage === 'scene'),
    [{ stage: 'scene', provider: 'agy', model: 'agy-alpha', brief: 'scene-b' }]);
  console.log('V4 PASS. Prose timeout is distinct; partial lesson, sandboxed scene and quiz usable before repair; restart and retry preserved version.');
  console.log('V5 PASS. Concurrent retries committed once; out-of-order index stayed stable; quiz attempt and scene highlight preserved.');

  injectInvalidFrame = true;
  await page.reload();
  await page.getByRole('button', { name: 'Regenerate illustration' }).waitFor();
  await page.getByText(/failed while repairing the illustration/i).waitFor();
  const afterFailedRepair = (await request(lessonPath)).json.doc;
  assert.deepEqual(afterFailedRepair.illustrations[0], afterRetry.doc.illustrations[0]);
  const autoReplay = await request(repairPath, 'POST', { manual: false, error: 'synthetic repeat' });
  assert.equal(autoReplay.status, 409);
  injectInvalidFrame = false;
  await worker.send({ op: 'fail', stage: 'repair', enabled: false });
  await page.getByRole('button', { name: 'Regenerate illustration' }).click();
  await page.frameLocator('iframe[title="Scene A"]').locator('[id=ball]').waitFor({ state: 'attached' });
  const repaired = (await request(lessonPath)).json.doc.illustrations[0];
  assert.equal(repaired.css, 'svg { width: 99%; }');
  assert.equal(external, 0);
  assert.equal(await page.locator('iframe[title="Scene A"]').getAttribute('sandbox'), 'allow-scripts');
  assert.deepEqual((await worker.send({ op: 'calls' })).filter(item => item.stage === 'repair'),
    Array.from({ length: 2 }, () => ({ stage: 'repair', provider: 'agy', model: 'agy-alpha' })));
  console.log('V6 targeted PASS. Runtime rejected invalid HTML, failed automatic repair preserved scene, manual repair rendered within iframe.');

  const inherited = await request('/api/settings', 'POST', {
    provider: 'codex', visual_provider: null, codex_model: 'codex-beta',
  });
  assert.equal(inherited.status, 200);
  assert.equal((await request(otherPath, 'POST', {})).status, 200);
  assert.deepEqual((await worker.send({ op: 'calls' })).slice(-4), [
    { stage: 'prose', provider: 'codex', model: 'codex-beta' },
    ...['scene-a', 'scene-b', 'scene-c'].map(brief => ({ stage: 'scene', provider: 'codex', model: 'codex-beta', brief })),
  ]);
  await page.getByLabel('Your roadmap').selectOption('physics');
  await page.getByRole('heading', { name: 'Free fall', exact: true }).waitFor();
  const legacy = page.getByRole('slider', { name: 'Time' });
  await legacy.fill('120');
  await page.getByText('19.62 m', { exact: true }).waitFor();
  console.log('V6 legacy PASS. The saved lesson without slot metadata rendered and simulated free fall.');
  assert.deepEqual(errors, []);
  console.log('V3 PASS. Exact split on creation, retry and both repairs after server restart/model change; inherited general model works.');
  console.log(`Offline Chromium ${browser.version()} verification elapsed ${Math.round(performance.now() - started)}ms.`);
}

try {
  if (process.argv.includes('--regression')) await runRegression();
  else await run();
} finally {
  if (browser) await browser.close();
  if (worker) await worker.stop();
  rmSync(temp, { recursive: true, force: true });
}
