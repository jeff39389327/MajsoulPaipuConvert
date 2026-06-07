// i18n —— 極簡在地化：t(key, vars) 查表 + {var} 插值，缺 key 回退 zh-TW 並警告。
// 語系資料由主程序透過 IPC (api.loadLocales) 提供，避免 renderer 直接讀檔。

const FALLBACK = 'zh-TW';

let locales = {}; // { 'zh-TW': {...}, en: {...}, ja: {...} }
let current = FALLBACK;
const listeners = new Set();

export async function initI18n(preferred) {
  locales = (await window.api.loadLocales()) || {};
  setLocale(preferred || FALLBACK, false);
}

export function availableLocales() {
  return Object.keys(locales);
}

export function getLocale() {
  return current;
}

export function setLocale(loc, notify = true) {
  current = locales[loc] ? loc : FALLBACK;
  if (notify) listeners.forEach((fn) => fn(current));
  return current;
}

// 訂閱語系變更，回傳取消訂閱函式。
export function onLocaleChange(fn) {
  listeners.add(fn);
  return () => listeners.delete(fn);
}

function interpolate(str, vars) {
  if (!vars) return str;
  return str.replace(/\{(\w+)\}/g, (m, k) => (k in vars ? String(vars[k]) : m));
}

export function t(key, vars) {
  const table = locales[current] || {};
  if (key in table) return interpolate(table[key], vars);
  const fb = locales[FALLBACK] || {};
  if (key in fb) {
    if (current !== FALLBACK) console.warn(`[i18n] missing "${key}" in ${current}`);
    return interpolate(fb[key], vars);
  }
  console.warn(`[i18n] missing key "${key}"`);
  return key;
}
