'use strict';
// configIni —— 單一 config.ini 的低階解析 / 序列化 / 鏡像備援。
//
// 設計：所有設定集中在「執行檔同層」的 config.ini（使用者選定的位置，最好找、可手動編輯）。
// 因該位置正是 electron-updater(NSIS) 升級時會清掉的安裝目錄，故每次寫入都同步鏡像一份到
// userData；開機時若同層檔不見了（被升級洗掉）就從鏡像還原。如此兼顧「好找」與「升級不丟」。
//
// 格式與 Python 端 config_store.py 對齊：區段 / 鍵一律小寫、布林用 true/false、多值用逗號分隔。

const fs = require('fs');
const path = require('path');

// 區段與鍵的標準順序（序列化時據此排版；未列出的鍵會保留並追加於區段尾）。
const SCHEMA = {
  account: ['ms_username', 'ms_password', 'ms_res_version', 'account_pool'],
  download: [
    'collect_timing', 'save_debug', 'save_raw_json', 'convert_concurrency',
  ],
  crawler: [
    'crawler_mode', 'output_filename', 'headless_mode', 'fast_mode', 'paipu_limit',
    'time_periods', 'ranks', 'max_players_per_period', 'save_screenshots',
    'manual_player_urls', 'start_date', 'end_date', 'target_room', 'game_mode',
  ],
  app: ['work_dir', 'python_path', 'locale', 'auto_download_after_crawl'],
};

// 預設值（缺鍵時補上，確保檔案完整、後端 / 前端讀到的型別穩定）。
const DEFAULTS = {
  account: { ms_username: '', ms_password: '', ms_res_version: '', account_pool: '' },
  download: {
    collect_timing: 'false', save_debug: 'false', save_raw_json: 'false',
    convert_concurrency: '0',
  },
  crawler: {
    crawler_mode: 'date_room', output_filename: 'date_room_list.txt',
    headless_mode: 'true', fast_mode: 'false', paipu_limit: '9999',
    time_periods: '', ranks: '', max_players_per_period: '20', save_screenshots: 'true',
    manual_player_urls: '', start_date: '', end_date: '', target_room: 'Jade',
    game_mode: 'yonma',
  },
  app: { work_dir: '', python_path: '', locale: '', auto_download_after_crawl: 'true' },
};

const SECTION_COMMENT = {
  account: '# 雀魂帳號（中國伺服器）。ms_res_version 平常留空，error 151 時自動寫回。\n# account_pool 為備用帳號池（JSON 陣列 [{"username":"...","password":"..."}]），下載失敗時依序切換。',
  download: '# 下載 / 轉換選項與效能。布林用 true/false；convert_concurrency=0 表自動。下載固定串行（單帳號單連線）。',
  crawler: '# 爬取設定（最後一次使用的值）。多值（time_periods/ranks/manual_player_urls）逗號分隔。',
  app: '# GUI 偏好。work_dir 留空＝執行檔同層；locale 留空＝跟隨系統。',
};

// 解析 INI 文字 -> { section: { key: value } }（區段 / 鍵小寫，忽略註解與空行）。
function parse(text) {
  const out = {};
  let cur = null;
  for (const raw of String(text).split(/\r?\n/)) {
    const line = raw.trim();
    if (!line || line.startsWith('#') || line.startsWith(';')) continue;
    const m = line.match(/^\[(.+)\]$/);
    if (m) {
      cur = m[1].trim().toLowerCase();
      if (!out[cur]) out[cur] = {};
      continue;
    }
    if (!cur) continue;
    const idx = line.indexOf('=');
    if (idx < 0) continue;
    out[cur][line.slice(0, idx).trim().toLowerCase()] = line.slice(idx + 1).trim();
  }
  return out;
}

// 物件 -> INI 文字（含表頭與區段註解，鍵依 SCHEMA 排序，未知鍵保留於區段尾）。
function serialize(obj) {
  const lines = [
    '# MajsoulPaipuGUI 設定（單一檔，與執行檔同層；升級會自動保留）',
    '# 由 GUI 讀寫，也可手動編輯。布林用 true/false，多值用逗號分隔。',
    '',
  ];
  for (const section of Object.keys(SCHEMA)) {
    if (SECTION_COMMENT[section]) lines.push(SECTION_COMMENT[section]);
    lines.push(`[${section}]`);
    const sec = obj[section] || {};
    const known = SCHEMA[section];
    for (const k of known) lines.push(`${k} = ${sec[k] != null ? sec[k] : ''}`);
    for (const k of Object.keys(sec)) {
      if (!known.includes(k)) lines.push(`${k} = ${sec[k]}`);
    }
    lines.push('');
  }
  // 保留任何未知區段（手動加的）。
  for (const section of Object.keys(obj)) {
    if (SCHEMA[section]) continue;
    lines.push(`[${section}]`);
    for (const [k, v] of Object.entries(obj[section] || {})) lines.push(`${k} = ${v}`);
    lines.push('');
  }
  return lines.join('\n');
}

// 讀取 primary（缺則試 mirror），與 DEFAULTS 合併後回傳完整物件。
function readObj(primaryPath, mirrorPath) {
  let parsed = {};
  for (const p of [primaryPath, mirrorPath]) {
    if (p && fs.existsSync(p)) {
      try {
        parsed = parse(fs.readFileSync(p, 'utf-8'));
        break;
      } catch (_) {
        /* 試下一個 */
      }
    }
  }
  const obj = {};
  for (const section of Object.keys(DEFAULTS)) {
    obj[section] = Object.assign({}, DEFAULTS[section], parsed[section] || {});
  }
  for (const section of Object.keys(parsed)) {
    if (!obj[section]) obj[section] = parsed[section];
  }
  return obj;
}

// 寫入 primary 並同步鏡像到 mirror（鏡像失敗不致命）。
function writeObj(primaryPath, mirrorPath, obj) {
  const text = serialize(obj);
  let primaryOk = false;
  try {
    fs.mkdirSync(path.dirname(primaryPath), { recursive: true });
    fs.writeFileSync(primaryPath, text, 'utf-8');
    primaryOk = true;
  } catch (_) {
    /* 同層不可寫（如裝在 Program Files）：仍寫鏡像，由鏡像當實際存放處 */
  }
  if (mirrorPath && mirrorPath !== primaryPath) {
    try {
      fs.mkdirSync(path.dirname(mirrorPath), { recursive: true });
      fs.writeFileSync(mirrorPath, text, 'utf-8');
    } catch (_) {
      /* 鏡像失敗忽略 */
    }
  }
  return primaryOk;
}

// 開機還原：同層 config.ini 不存在但鏡像存在（被升級洗掉）→ 從鏡像複製回來。
function restoreFromMirror(primaryPath, mirrorPath) {
  try {
    if (primaryPath && mirrorPath && primaryPath !== mirrorPath &&
        !fs.existsSync(primaryPath) && fs.existsSync(mirrorPath)) {
      fs.mkdirSync(path.dirname(primaryPath), { recursive: true });
      fs.copyFileSync(mirrorPath, primaryPath);
      return true;
    }
  } catch (_) {
    /* 同層不可寫：略過，讀取時會自動退回鏡像 */
  }
  return false;
}

module.exports = { SCHEMA, DEFAULTS, parse, serialize, readObj, writeObj, restoreFromMirror };
