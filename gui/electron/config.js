'use strict';
// config —— 單一 config.ini 與「renderer / 後端面向的形狀」之間的映射層。
//
// 全部設定集中於一個 config.ini（見 configIni.js）。本模組把它投影成三種既有形狀，讓
// renderer 與 main.js 幾乎不用改：
//   - env      : {ms_username, ms_password, MS_RES_VERSION, COLLECT_TIMING, SAVE_DEBUG, SAVE_RAW_JSON}
//   - crawler  : CrawlerConfig 物件（陣列 / 數字 / 布林已還原型別）
//   - settings : {workDir, pythonPath, locale, autoDownloadAfterCrawl, convertConcurrency}
// 三者讀寫的是同一個 config.ini 的不同區段；每次寫入皆 read-modify-write 整檔並鏡像備援。

const fs = require('fs');
const configIni = require('./configIni');

// ---- env（[account] + [download] 旗標）----------------------------------
// 環境變數名稱 -> (section, key)。鍵與 Python 端 config_store._ENV_MAP 對齊。
const ENV_TO_INI = {
  ms_username: ['account', 'ms_username'],
  ms_password: ['account', 'ms_password'],
  MS_RES_VERSION: ['account', 'ms_res_version'],
  ACCOUNT_POOL: ['account', 'account_pool'],
  COLLECT_TIMING: ['download', 'collect_timing'],
  SAVE_DEBUG: ['download', 'save_debug'],
  SAVE_RAW_JSON: ['download', 'save_raw_json'],
};

function readEnv(primaryPath, mirrorPath) {
  const obj = configIni.readObj(primaryPath, mirrorPath);
  const out = {};
  for (const [envKey, [s, k]] of Object.entries(ENV_TO_INI)) {
    out[envKey] = (obj[s] && obj[s][k]) || '';
  }
  return out;
}

function writeEnv(primaryPath, mirrorPath, values) {
  const obj = configIni.readObj(primaryPath, mirrorPath);
  for (const [envKey, [s, k]] of Object.entries(ENV_TO_INI)) {
    if (Object.prototype.hasOwnProperty.call(values, envKey)) {
      obj[s] = obj[s] || {};
      obj[s][k] = String(values[envKey] != null ? values[envKey] : '');
    }
  }
  return configIni.writeObj(primaryPath, mirrorPath, obj);
}

// ---- crawler（[crawler]）------------------------------------------------
const CRAWLER_LIST = new Set(['time_periods', 'ranks', 'manual_player_urls']);
const CRAWLER_INT = new Set(['paipu_limit', 'max_players_per_period']);
const CRAWLER_BOOL = new Set(['headless_mode', 'fast_mode', 'save_screenshots']);

function readCrawler(primaryPath, mirrorPath) {
  const obj = configIni.readObj(primaryPath, mirrorPath);
  const sec = obj.crawler || {};
  const out = {};
  for (const [k, v] of Object.entries(sec)) {
    if (CRAWLER_LIST.has(k)) {
      out[k] = v ? v.split(',').map((x) => x.trim()).filter(Boolean) : [];
    } else if (CRAWLER_INT.has(k)) {
      out[k] = v === '' ? undefined : Number(v);
    } else if (CRAWLER_BOOL.has(k)) {
      out[k] = v === 'true';
    } else {
      out[k] = v;
    }
  }
  return out;
}

function writeCrawler(primaryPath, mirrorPath, cfg) {
  const obj = configIni.readObj(primaryPath, mirrorPath);
  obj.crawler = obj.crawler || {};
  // buildConfig() 只帶該模式相關欄位 → 合併進既有區段（其餘鍵保留）。
  for (const [k, v] of Object.entries(cfg || {})) {
    obj.crawler[k] = Array.isArray(v) ? v.join(',') : String(v);
  }
  return configIni.writeObj(primaryPath, mirrorPath, obj);
}

// ---- settings（[app] + [download] 效能鍵）-------------------------------
// settings 物件鍵 -> (section, key)。
const APP_TO_INI = {
  workDir: ['app', 'work_dir'],
  pythonPath: ['app', 'python_path'],
  locale: ['app', 'locale'],
  theme: ['app', 'theme'],
  autoDownloadAfterCrawl: ['app', 'auto_download_after_crawl'],
  convertConcurrency: ['download', 'convert_concurrency'],
};
const APP_BOOL = new Set(['autoDownloadAfterCrawl']);
const APP_INT = new Set(['convertConcurrency']);

function readSettings(primaryPath, mirrorPath) {
  const obj = configIni.readObj(primaryPath, mirrorPath);
  const out = {};
  for (const [key, [s, k]] of Object.entries(APP_TO_INI)) {
    const v = (obj[s] && obj[s][k] != null) ? obj[s][k] : '';
    if (APP_BOOL.has(key)) out[key] = v === 'true';
    else if (APP_INT.has(key)) out[key] = Number(v || '0');
    else out[key] = v;
  }
  return out;
}

function writeSettings(primaryPath, mirrorPath, patch) {
  const obj = configIni.readObj(primaryPath, mirrorPath);
  for (const [key, [s, k]] of Object.entries(APP_TO_INI)) {
    if (Object.prototype.hasOwnProperty.call(patch, key)) {
      obj[s] = obj[s] || {};
      const v = patch[key];
      obj[s][k] = typeof v === 'boolean' ? String(v) : String(v != null ? v : '');
    }
  }
  return configIni.writeObj(primaryPath, mirrorPath, obj);
}

// ---- 舊設定遷移（首次啟動）---------------------------------------------
// 把舊的 config.env（dotenv 文字）解析成 {KEY: value}。
function parseEnvFile(text) {
  const out = {};
  for (const raw of String(text).split(/\r?\n/)) {
    const line = raw.trim();
    if (!line || line.startsWith('#')) continue;
    const idx = line.indexOf('=');
    if (idx < 0) continue;
    out[line.slice(0, idx).trim()] = line.slice(idx + 1).trim();
  }
  return out;
}

function readJsonSafe(p) {
  try {
    return JSON.parse(fs.readFileSync(p, 'utf-8'));
  } catch (_) {
    return null;
  }
}

function readTextSafe(p) {
  try {
    return fs.readFileSync(p, 'utf-8');
  } catch (_) {
    return null;
  }
}

module.exports = {
  readEnv,
  writeEnv,
  readCrawler,
  writeCrawler,
  readSettings,
  writeSettings,
  parseEnvFile,
  readJsonSafe,
  readTextSafe,
};
