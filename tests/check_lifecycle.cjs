const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {spawn} = require('node:child_process');
const {chromium} = require(path.join(process.argv[2], 'playwright'));
const root = path.resolve(__dirname, '..');
const scratch = fs.mkdtempSync(path.join(root, 'tests', 'lifecycle-test-'));
const port = 17862;
const delay = ms => new Promise(resolve => setTimeout(resolve, ms));
let server, browser;
async function run() {
  server = spawn(path.join(root, '.venv', 'Scripts', 'python.exe'), ['-B', path.join(root, 'web', 'app.py')], {
    cwd: root, windowsHide: true,
    env: {...process.env, PORT: String(port), PAPER_DIALOGUE_AUDIO_PROJECT_DIR: scratch, PAPER_DIALOGUE_CLOSE_GRACE_SECONDS: '40'},
    stdio: ['ignore', 'ignore', 'pipe']
  });
  let logs = '';
  server.stderr.on('data', chunk => logs += chunk);
  const base = `http://127.0.0.1:${port}`;
  let ready = false;
  for (let i = 0; i < 100; i++) {
    try { if ((await fetch(base + '/api/health')).ok) { ready = true; break; } } catch {}
    await delay(100);
  }
  assert.ok(ready, logs);
  browser = await chromium.launch({headless: true, ...(process.argv[3] ? {executablePath: process.argv[3]} : {})});
  const first = await browser.newPage();
  const second = await browser.newPage();
  await Promise.all([first.goto(base), second.goto(base)]);
  await Promise.all([first, second].map(page => page.waitForFunction(() => state.serviceEvents?.readyState === EventSource.OPEN)));
  console.log('LIFECYCLE: two pages connected; checking survival beyond the startup and idle grace periods.');
  await delay(55000);
  assert.equal(server.exitCode, null, 'Open pages must keep the service alive.');
  await first.close();
  await delay(10000);
  assert.equal(server.exitCode, null, 'Closing one of two pages must not stop the service.');
  assert.ok((await fetch(base + '/api/health')).ok);
  const closedAt = Date.now();
  await second.close();
  console.log('LIFECYCLE: final page closed; waiting for the actual server process to exit.');
  for (let i = 0; i < 70 && server.exitCode === null; i++) await delay(1000);
  assert.equal(server.exitCode, 0, 'Service did not exit cleanly after its final page closed.');
  const seconds = Math.round((Date.now() - closedAt) / 1000);
  assert.ok(seconds >= 20 && seconds <= 70, `Unexpected shutdown delay: ${seconds}s`);
  console.log(`LIFECYCLE_OK: open pages keep service alive; one closed page is safe; all pages closed -> process exit after ${seconds}s.`);
}
run().catch(error => { console.error(error); process.exitCode = 1; }).finally(async () => {
  if (browser) await browser.close();
  if (server && server.exitCode === null) {
    server.kill();
    await new Promise(resolve => { server.once('exit', resolve); setTimeout(resolve, 3000); });
  }
  // Delete only the isolated directory this test created, never project inputs or outputs.
  if (path.dirname(scratch) === path.join(root, 'tests') && path.basename(scratch).startsWith('lifecycle-test-')) {
    fs.rmSync(scratch, {recursive: true, force: true});
  }
});
