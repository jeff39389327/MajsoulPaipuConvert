'use strict';
// smoke —— 不需 Electron / Chrome / 雀魂，驗證後端 NDJSON 協定與事件順序。
// 執行：node gui/test/smoke.js   (cwd 任意；會以 repo root 為後端 cwd)

const { spawn } = require('child_process');
const readline = require('readline');
const os = require('os');
const fs = require('fs');
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
  // 1) doctor --mock
  const doctor = await runBackend(['doctor', '--mock', '--params-stdin'], {});
  const types = doctor.events.map((e) => e.type);
  assert(types[0] === 'stage_start', 'doctor: first event is stage_start');
  assert(types.includes('stage_done'), 'doctor: has stage_done');
  assert(types[types.length - 1] === 'done', 'doctor: last event is done');

  // 2) crawl --dry-run -> 產生輸出檔
  const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'paipu-'));
  const crawl = await runBackend(['crawl', '--dry-run', '--params-stdin'], {
    repo_root: tmp,
    work_dir: tmp,
    config: { crawler_mode: 'date_room', start_date: '2024-01-01', end_date: '2024-01-01', target_room: 'Jade', output_filename: 'date_room_list.txt' },
  });
  const doneCrawl = crawl.events.find((e) => e.type === 'stage_done');
  assert(doneCrawl && doneCrawl.stats.collected === 5, 'crawl: collected 5 ids');
  const outFile = doneCrawl.stats.output_file;
  assert(fs.existsSync(outFile), 'crawl: output file written');

  // 3) download --dry-run，以 crawl 輸出為輸入清單 (自動銜接)
  const dl = await runBackend(['download', '--dry-run', '--params-stdin'], {
    repo_root: tmp, work_dir: tmp, input_list: outFile,
  });
  const dlTypes = dl.events.map((e) => e.type);
  const phases = dl.events.filter((e) => e.type === 'progress').map((e) => e.phase);
  assert(dlTypes[0] === 'stage_start', 'download: first event is stage_start');
  assert(phases.includes('download') && phases.includes('mjai'), 'download: has download+mjai phases');
  assert(dlTypes[dlTypes.length - 1] === 'done', 'download: last event is done');

  fs.rmSync(tmp, { recursive: true, force: true });
  console.log(process.exitCode ? '\nSMOKE FAILED' : '\nSMOKE PASSED');
})();
