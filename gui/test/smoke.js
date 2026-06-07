'use strict';
// smoke —— 不需 Electron / Chrome / 雀魂，驗證後端 NDJSON 協定與事件順序。
// 執行：node gui/test/smoke.js   (cwd 任意；會以 repo root 為後端 cwd)
//
// crawl/download 需真實 Selenium/登入，無法在煙霧測試中執行，故僅驗證 doctor 的事件序列。

const { spawn } = require('child_process');
const readline = require('readline');
const path = require('path');

const REPO_ROOT = path.resolve(__dirname, '..', '..');
const PY = process.env.PYTHON || 'python3';

function runBackend(args, params) {
  return new Promise((resolve) => {
    const child = spawn(PY, ['-u', '-m', 'gui.backend', ...args], {
      cwd: REPO_ROOT,
      env: Object.assign({}, process.env, { PYTHONIOENCODING: 'utf-8' }),
    });
    child.stdin.write(JSON.stringify(params || {}));
    child.stdin.end();
    const events = [];
    readline.createInterface({ input: child.stdout }).on('line', (line) => {
      if (line.trim()) events.push(JSON.parse(line)); // throws if NDJSON invalid
    });
    child.on('exit', (code) => resolve({ code, events }));
  });
}

function assert(cond, msg) {
  if (!cond) {
    console.error('FAIL:', msg);
    process.exitCode = 1;
  } else {
    console.log('ok:', msg);
  }
}

(async () => {
  // doctor --mock：驗證 NDJSON 事件序列 (stage_start … stage_done … done)
  const doctor = await runBackend(['doctor', '--mock', '--params-stdin'], {});
  const types = doctor.events.map((e) => e.type);
  assert(types[0] === 'stage_start', 'doctor: first event is stage_start');
  assert(types.includes('stage_done'), 'doctor: has stage_done');
  assert(types[types.length - 1] === 'done', 'doctor: last event is done');

  console.log(process.exitCode ? '\nSMOKE FAILED' : '\nSMOKE PASSED');
})();
