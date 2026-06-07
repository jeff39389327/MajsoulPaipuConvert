'use strict';
// config —— Node 端讀寫 config.env 與 crawler_config.json。
//
// config.env       : dotenv 格式 (KEY=VALUE)，逐行解析、保留註解、就地更新；缺檔以
//                    config.env.example 為模板生成。帳密只存此檔 (已 gitignored)。
// crawler_config   : 純 JSON，欄位即 CrawlerConfig dataclass；依 crawler_mode 由前端決定顯示。

const fs = require('fs');
const path = require('path');

// config.env 中由 GUI 管理的鍵 (與 config.env.example / toumajsoul.py 對齊)。
const ENV_KEYS = [
  'ms_username',
  'ms_password',
  'MS_RES_VERSION',
  'COLLECT_TIMING',
  'SAVE_DEBUG',
  'SAVE_RAW_JSON',
];

function envPath(workDir) {
  return path.join(workDir, 'config.env');
}

function examplePath(repoRoot) {
  return path.join(repoRoot, 'config.env.example');
}

// 把一行解析成 { key, value } 或 null (註解/空行)。
function parseEnvLine(line) {
  const trimmed = line.trim();
  if (!trimmed || trimmed.startsWith('#')) return null;
  const idx = trimmed.indexOf('=');
  if (idx < 0) return null;
  return { key: trimmed.slice(0, idx).trim(), value: trimmed.slice(idx + 1).trim() };
}

// 讀取 config.env，回傳已知鍵的物件 (缺檔回空物件)。
function readEnv(workDir) {
  const out = {};
  const p = envPath(workDir);
  if (!fs.existsSync(p)) return out;
  const text = fs.readFileSync(p, 'utf-8');
  for (const line of text.split(/\r?\n/)) {
    const kv = parseEnvLine(line);
    if (kv && ENV_KEYS.includes(kv.key)) out[kv.key] = kv.value;
  }
  return out;
}

// 寫入/更新 config.env：保留既有註解與順序，就地更新存在的鍵，缺檔則以 example 為模板。
function writeEnv(workDir, repoRoot, values) {
  const p = envPath(workDir);
  let lines;
  if (fs.existsSync(p)) {
    lines = fs.readFileSync(p, 'utf-8').split(/\r?\n/);
  } else if (fs.existsSync(examplePath(repoRoot))) {
    lines = fs.readFileSync(examplePath(repoRoot), 'utf-8').split(/\r?\n/);
  } else {
    lines = [];
  }

  const remaining = new Set(Object.keys(values));
  const updated = lines.map((line) => {
    const kv = parseEnvLine(line);
    if (kv && Object.prototype.hasOwnProperty.call(values, kv.key)) {
      remaining.delete(kv.key);
      return `${kv.key}=${values[kv.key]}`;
    }
    return line;
  });

  // 模板/既有檔沒有的鍵 -> 追加到檔尾
  for (const key of remaining) {
    updated.push(`${key}=${values[key]}`);
  }

  fs.writeFileSync(p, updated.join('\n'), 'utf-8');
  return true;
}

function crawlerConfigPath(innerDir) {
  return path.join(innerDir, 'crawler_config.json');
}

function readCrawlerConfig(innerDir) {
  const p = crawlerConfigPath(innerDir);
  if (!fs.existsSync(p)) return null;
  try {
    return JSON.parse(fs.readFileSync(p, 'utf-8'));
  } catch (_) {
    return null;
  }
}

function writeCrawlerConfig(innerDir, config) {
  const p = crawlerConfigPath(innerDir);
  fs.mkdirSync(path.dirname(p), { recursive: true });
  fs.writeFileSync(p, JSON.stringify(config, null, 2), 'utf-8');
  return true;
}

module.exports = {
  ENV_KEYS,
  readEnv,
  writeEnv,
  readCrawlerConfig,
  writeCrawlerConfig,
};
