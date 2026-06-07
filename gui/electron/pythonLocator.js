'use strict';
// pythonLocator —— 解析後端執行體與相關路徑，統一 dev 與凍結兩種模式。
//
// dev    : 用偵測到/使用者指定的 python，跑 `python -u -m gui.backend.cli <cmd>`，cwd = repoRoot。
// 凍結   : 直接跑 `process.resourcesPath/backend/backend.exe <cmd>`，內建 mjai-reviewer.exe。

const { spawnSync } = require('child_process');
const fs = require('fs');
const path = require('path');

const app = require('electron').app;

// gui/electron/pythonLocator.js -> gui/electron -> gui -> <repo root>
const REPO_ROOT = path.resolve(__dirname, '..', '..');

function isPackaged() {
  return app && app.isPackaged;
}

// 在 PATH / 常見位置尋找可用的 python 直譯器 (dev 模式)。
function detectPython(userPath) {
  const candidates = [];
  if (userPath) candidates.push(userPath);
  // repo 內的虛擬環境
  candidates.push(path.join(REPO_ROOT, 'venv', 'Scripts', 'python.exe'));
  candidates.push(path.join(REPO_ROOT, 'venv', 'bin', 'python'));
  candidates.push(path.join(REPO_ROOT, '.venv', 'Scripts', 'python.exe'));
  candidates.push(path.join(REPO_ROOT, '.venv', 'bin', 'python'));
  // PATH 上的常見名稱
  candidates.push('python');
  candidates.push('python3');
  candidates.push('py');

  for (const c of candidates) {
    try {
      const args = c === 'py' ? ['-3', '--version'] : ['--version'];
      const res = spawnSync(c, args, { encoding: 'utf-8' });
      if (res.status === 0 || (res.stdout || res.stderr || '').toLowerCase().includes('python')) {
        return c === 'py' ? { command: 'py', prefix: ['-3'] } : { command: c, prefix: [] };
      }
    } catch (_) {
      /* try next */
    }
  }
  return null;
}

// 凍結模式下內建的 backend.exe 路徑。
function frozenBackendExe() {
  return path.join(process.resourcesPath, 'backend', 'backend.exe');
}

// 凍結模式下內建的 mjai-reviewer.exe 路徑。
function frozenMjaiBin() {
  return path.join(process.resourcesPath, 'bin', 'mjai-reviewer.exe');
}

// 回傳啟動後端所需的 { command, baseArgs, cwd, env }，依模式組裝。
function resolveBackend(opts) {
  opts = opts || {};
  const env = Object.assign({}, process.env, { PYTHONIOENCODING: 'utf-8' });

  if (isPackaged()) {
    const exe = frozenBackendExe();
    const mjai = frozenMjaiBin();
    if (fs.existsSync(mjai)) env.MJAI_REVIEWER_BIN = mjai;
    return { command: exe, baseArgs: [], cwd: REPO_ROOT, env, mode: 'frozen' };
  }

  const py = detectPython(opts.pythonPath);
  if (!py) return null;
  return {
    command: py.command,
    baseArgs: [...py.prefix, '-u', '-m', 'gui.backend.cli'],
    cwd: REPO_ROOT,
    env,
    mode: 'dev',
  };
}

module.exports = {
  REPO_ROOT,
  isPackaged,
  detectPython,
  resolveBackend,
  frozenBackendExe,
  frozenMjaiBin,
};
