'use strict';
// pyRunner —— spawn 後端子程序、逐行解析 NDJSON 事件、串給 renderer，並支援取消。
//
// 一次只跑一個 job (wizard 線性流程)。stdout 為乾淨事件流 (每行一 JSON)，stderr 為
// 原始 log。參數經 stdin 以 JSON 傳入 (含帳密)，不進 argv。

const { spawn } = require('child_process');
const readline = require('readline');

const { resolveBackend } = require('./pythonLocator');

let current = null; // { child, kind }

function isRunning() {
  return current !== null;
}

// 啟動一個 job。send(channel, payload) 用來把事件推給 renderer。
// kind: 'crawl' | 'download' | 'doctor'；options: { params, pythonPath, cwd }
function startJob(kind, options, send) {
  if (current) {
    send('py:event', { type: 'error', code: 'BUSY', msg: 'a job is already running', fatal: true });
    return false;
  }
  options = options || {};
  const backend = resolveBackend({ pythonPath: options.pythonPath });
  if (!backend) {
    send('py:event', { type: 'error', code: 'NO_PYTHON', msg: 'no python interpreter found', fatal: true });
    return false;
  }

  const args = [...backend.baseArgs, kind, '--params-stdin'];

  const child = spawn(backend.command, args, {
    cwd: options.cwd || backend.cwd,
    env: backend.env,
    windowsHide: true,
  });
  current = { child, kind };

  // 把參數從 stdin 餵入 (敏感資料不進 argv)
  try {
    child.stdin.write(JSON.stringify(options.params || {}));
    child.stdin.end();
  } catch (_) {
    /* child may have failed to spawn */
  }

  const rl = readline.createInterface({ input: child.stdout });
  rl.on('line', (line) => {
    if (!line) return;
    try {
      send('py:event', JSON.parse(line));
    } catch (_) {
      send('py:raw', line);
    }
  });

  child.stderr.on('data', (d) => send('py:stderr', d.toString()));

  child.on('error', (err) => {
    send('py:event', { type: 'error', code: 'SPAWN_FAILED', msg: String(err), fatal: true });
    current = null;
  });

  child.on('exit', (code, signal) => {
    send('py:exit', { code, signal });
    current = null;
  });

  return true;
}

// 取消目前 job。Windows 上殺整棵進程樹 (否則 chrome/chromedriver 殘留)。
function cancelJob() {
  if (!current) return false;
  const { child } = current;
  if (process.platform === 'win32') {
    try {
      spawn('taskkill', ['/pid', String(child.pid), '/T', '/F']);
    } catch (_) {
      child.kill('SIGKILL');
    }
  } else {
    child.kill('SIGTERM');
    setTimeout(() => {
      if (current && current.child === child) child.kill('SIGKILL');
    }, 4000);
  }
  return true;
}

module.exports = { startJob, cancelJob, isRunning };
