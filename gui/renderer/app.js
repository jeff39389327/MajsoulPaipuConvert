// app —— renderer 狀態機：載入設定/語系/設定檔、繪製導覽與步驟、統籌 job 事件。
import { initI18n, setLocale, getLocale, onLocaleChange, t } from './i18n/index.js';
import { renderSettings } from './views/step-settings.js';
import { renderMode } from './views/step-mode.js';
import { renderCrawl } from './views/step-crawl.js';
import { renderDownload } from './views/step-download.js';

const STEPS = [
  { id: 'mode', icon: '①', render: renderMode },
  { id: 'crawl', icon: '②', render: renderCrawl },
  { id: 'download', icon: '③', render: renderDownload },
  { id: 'settings', icon: '⚙', render: renderSettings },
];

const state = {
  settings: null,
  paths: null,
  configPath: '', // 單一 config.ini 的位置（設定頁顯示 + 可開啟）
  packaged: false,
  appVersion: '',
  systemLocale: 'en',
  backendAvailable: true,
  releasesUrl: '', // 更新橫幅「改用瀏覽器下載」退路（由主程序依 publish 設定推導）
  config: { env: {}, crawler: null },
  doctor: null,
  crawlOutputFile: null, // Stage 1 完成後的輸出檔，供 Stage 2 自動接手
  downloadInputList: null, // 下載頁的 ID 清單（txt）路徑；爬取完成會自動帶入，也可手動指定
  autoStartDownload: false, // 由 crawl 自動串接時設 true，download view 進場即自動開始
  activeStep: 'mode',
  jobStatus: 'idle', // idle | running | done | error
};

// ---- job 事件管線 -------------------------------------------------------
const jobHandlers = new Set();
function onJobEvent(cb) {
  jobHandlers.add(cb);
  return () => jobHandlers.delete(cb);
}

// log 轉送可能極高頻（如 scrapy/selenium DEBUG 洪流）。若每行都直接寫 DOM 並無上限累加，
// renderer 主執行緒會被拖垮，導致「取消」鈕點不動、狀態也更新不了。對策：(1) 緩衝字串設上限，
// (2) 用 requestAnimationFrame 把多次寫入合併成每幀一次 DOM 更新，讓事件迴圈保持可回應點擊。
const LOG_MAX_CHARS = 200000;
let logBuffer = '';
let logFlushScheduled = false;
function appendLog(text) {
  logBuffer += text.endsWith('\n') ? text : text + '\n';
  if (logBuffer.length > LOG_MAX_CHARS) {
    logBuffer = logBuffer.slice(logBuffer.length - LOG_MAX_CHARS);
  }
  if (logFlushScheduled) return;
  logFlushScheduled = true;
  requestAnimationFrame(() => {
    logFlushScheduled = false;
    const drawer = document.getElementById('log-drawer');
    drawer.textContent = logBuffer;
    drawer.scrollTop = drawer.scrollHeight;
  });
}

function setStatus(status) {
  state.jobStatus = status;
  const el = document.getElementById('status-text');
  el.className = 'status ' + status;
  el.textContent = t('status.' + status);
  document.getElementById('cancel-btn').hidden = status !== 'running';
}

// 啟動 job 並回傳 Promise。終止路徑有三：done 事件、startJob 回傳 false、或後端在未發出
// done 前就 py:exit（取消/匯入期崩潰）。任一路徑都會解除訂閱並 resolve，避免殘留 handler。
function runJob(kind, params, onEvent) {
  return new Promise((resolve) => {
    setStatus('running');
    let settled = false;
    let doneResult = null; // 後端送出的 done 事件先存著，待程序真正 exit 才據以 resolve
    let offEvent = null;
    let offExit = null;
    const finish = (result) => {
      if (settled) return;
      settled = true;
      if (offEvent) offEvent();
      if (offExit) offExit();
      resolve(result);
    };
    offEvent = onJobEvent((ev) => {
      if (onEvent) onEvent(ev);
      if (ev.type === 'error' && ev.fatal) setStatus('error');
      if (ev.type === 'done') {
        if (state.jobStatus !== 'error') setStatus(ev.ok ? 'done' : 'error');
        // 不在此 resolve：等後端程序真正 exit 再 resolve。否則自動串接時，爬蟲已送 done 但
        // 子程序（scrapy/twisted/selenium 關閉）尚未結束，緊接著啟動下載會撞到 pyRunner 的 BUSY。
        doneResult = ev;
      }
    });
    // 程序退出才真正結束：帶上先前的 done 結果；若未曾收到 done（取消/崩潰）則依退出碼判定。
    offExit = window.api.onExit((info) => {
      if (state.jobStatus === 'running') setStatus(info && info.code === 0 ? 'done' : 'error');
      finish(doneResult || { type: 'done', ok: !!(info && info.code === 0), viaExit: true });
    });
    window.api.startJob(kind, params || {}).then((ok) => {
      if (!ok) {
        setStatus('error');
        finish({ type: 'done', ok: false });
      }
    });
  });
}

function cancelJob() {
  window.api.cancelJob();
}

// ---- GUI 自動更新橫幅 ---------------------------------------------------
// 固定於視窗頂端，狀態：發現新版/下載中/已就緒(可重啟)/錯誤。dev 模式不會收到事件。
function ensureUpdateBanner() {
  let el = document.getElementById('update-banner');
  if (!el) {
    el = document.createElement('div');
    el.id = 'update-banner';
    el.hidden = true;
    document.body.appendChild(el);
  }
  return el;
}

// 位元組數人類可讀化（自動換 B/KB/MB/GB），給更新進度的速度與下載量用。
function humanBytes(n) {
  const v = Number(n) || 0;
  const units = ['B', 'KB', 'MB', 'GB'];
  let i = 0;
  let x = v;
  while (x >= 1024 && i < units.length - 1) { x /= 1024; i++; }
  return `${i === 0 ? x : x.toFixed(1)} ${units[i]}`;
}

function setupUpdater() {
  if (!window.api.onUpdate) return;
  const banner = ensureUpdateBanner();
  const show = (html) => { banner.innerHTML = html; banner.hidden = false; };
  // 在橫幅文字後附上「改用瀏覽器下載」連結（in-app 下載卡住時的退路）。
  const withBrowserLink = (html) => {
    show(`<span>${html}</span>`);
    if (state.releasesUrl && window.api.openExternal) {
      const link = document.createElement('button');
      link.className = 'ghost';
      link.textContent = t('update.browserDownload');
      link.onclick = () => window.api.openExternal(state.releasesUrl);
      banner.append(link);
    }
  };

  window.api.onUpdate((ev) => {
    if (!ev || !ev.state) return;
    if (ev.state === 'available') {
      withBrowserLink(t('update.available', { version: ev.version || '' }));
    } else if (ev.state === 'progress') {
      withBrowserLink(t('update.downloading', {
        percent: ev.percent ?? 0,
        speed: `${humanBytes(ev.bytesPerSecond)}/s`,
        transferred: humanBytes(ev.transferred),
        total: humanBytes(ev.total),
      }));
    } else if (ev.state === 'stalled') {
      // 自動下載多次停滯（網路對 GitHub 資產域名悶死）：明確請使用者改走瀏覽器。
      withBrowserLink(t('update.stalled', { version: ev.version || '' }));
    } else if (ev.state === 'downloaded') {
      banner.innerHTML = '';
      banner.append(
        Object.assign(document.createElement('span'), {
          textContent: t('update.downloaded', { version: ev.version || '' }),
        })
      );
      const btn = document.createElement('button');
      btn.className = 'primary';
      btn.textContent = t('update.restart');
      btn.onclick = () => window.api.quitAndInstall();
      const dismiss = document.createElement('button');
      dismiss.className = 'ghost';
      dismiss.textContent = t('update.later');
      dismiss.onclick = () => { banner.hidden = true; };
      banner.append(btn, dismiss);
      banner.hidden = false;
    } else {
      // checking / none / error：不打擾使用者，靜默（錯誤已寫入 stderr log）。
      banner.hidden = true;
    }
  });
}

function toast(msg) {
  const el = document.createElement('div');
  el.className = 'toast';
  el.textContent = msg;
  document.body.appendChild(el);
  setTimeout(() => el.remove(), 1800);
}

async function refreshConfig() {
  state.config = await window.api.readConfig();
}

async function runDoctor() {
  let result = null;
  await runJob('doctor', {}, (ev) => {
    if (ev.type === 'stage_done' && ev.stage === 'doctor') result = ev.stats;
  });
  state.doctor = result;
  renderEnvBadge();
  return result;
}

// ---- 導覽與繪製 ---------------------------------------------------------
let activeCleanup = null;

const ctx = {
  state,
  t,
  api: window.api,
  navigate,
  rerender: () => navigate(state.activeStep),
  refreshGameMode: () => renderGameModeBadge(),
  runJob,
  cancelJob,
  setStatus,
  appendLog,
  onJobEvent,
  toast,
  refreshConfig,
  runDoctor,
};

function renderNav() {
  const nav = document.getElementById('nav');
  nav.innerHTML = '';
  for (const step of STEPS) {
    const item = document.createElement('button');
    item.type = 'button';
    item.className = 'nav-item';
    if (step.id === state.activeStep) item.setAttribute('aria-current', 'page');
    // 步驟圖示僅為視覺輔助，對報讀器隱藏（已有文字標籤）。
    item.innerHTML = `<span class="idx" aria-hidden="true">${step.icon}</span><span>${t('nav.' + step.id)}</span>`;
    item.onclick = () => navigate(step.id);
    nav.appendChild(item);
  }
}

function renderEnvBadge() {
  const el = document.getElementById('env-badge');
  if (!state.doctor) {
    el.className = 'env-badge';
    el.textContent = t('env.checking');
    return;
  }
  const ok = state.doctor.ok;
  el.className = 'env-badge ' + (ok ? 'ok' : 'fail');
  el.textContent = ok ? '✓ ' + t('env.ok') : '⚠ ' + t('env.fail');
}

// 目前牌種（四麻/三麻）徽章——標題列全程顯示。優先用使用者在「選擇下載方式」頁的即時
// 選擇（state.crawlerForm），其次回退已存設定（state.config.crawler），預設四麻。
function currentGameMode() {
  const fromForm = state.crawlerForm && state.crawlerForm.game_mode;
  const fromCfg = state.config && state.config.crawler && state.config.crawler.game_mode;
  return (fromForm || fromCfg || 'yonma');
}

function renderGameModeBadge() {
  const el = document.getElementById('gamemode-badge');
  if (!el) return;
  const gm = currentGameMode() === 'sanma' ? 'sanma' : 'yonma';
  el.className = 'gamemode-badge ' + gm;
  el.textContent = '🀄 ' + t('enum.gameMode.' + gm);
}

function navigate(stepId) {
  if (activeCleanup) {
    activeCleanup();
    activeCleanup = null;
  }
  state.activeStep = stepId;
  renderNav();
  renderGameModeBadge();
  const view = document.getElementById('view');
  view.innerHTML = '';
  const step = STEPS.find((s) => s.id === stepId);
  const cleanup = step.render(ctx, view);
  activeCleanup = typeof cleanup === 'function' ? cleanup : null;
}

function applyStaticI18n() {
  document.querySelectorAll('[data-i18n]').forEach((el) => {
    el.textContent = t(el.getAttribute('data-i18n'));
  });
  const drawerEl = document.getElementById('log-drawer');
  document.getElementById('log-toggle').textContent = drawerEl && !drawerEl.hidden ? t('log.hide') : t('log.show');
  document.getElementById('log-clear').textContent = t('log.clear');
  document.getElementById('cancel-btn').textContent = t('btn.cancel');
  setStatus(state.jobStatus);
  renderGameModeBadge();
}

function mapSystemLocale(loc) {
  if (!loc) return 'en';
  if (loc.startsWith('zh')) return 'zh-TW';
  if (loc.startsWith('ja')) return 'ja';
  return 'en';
}

// 介面語系 -> <html lang>（供報讀器斷字、字型挑選）。
function localeToLang(loc) {
  if (loc === 'zh-TW') return 'zh-Hant';
  if (loc === 'ja') return 'ja';
  return 'en';
}
function syncHtmlLang() {
  document.documentElement.lang = localeToLang(getLocale());
}

// ---- 外觀主題（亮/暗/自動） --------------------------------------------
// setting 為 'light' | 'dark' | 'auto'（空字串視為 auto，跟隨系統偏好）。
let themeMql = null;
function applyTheme(setting) {
  const s = setting || (state.settings && state.settings.theme) || 'auto';
  let resolved = s;
  if (s !== 'light' && s !== 'dark') {
    resolved = window.matchMedia && window.matchMedia('(prefers-color-scheme: light)').matches ? 'light' : 'dark';
  }
  document.documentElement.dataset.theme = resolved;
  // 自動模式才需跟著系統切換；監聽只掛一次。
  if (window.matchMedia && !themeMql) {
    themeMql = window.matchMedia('(prefers-color-scheme: light)');
    themeMql.addEventListener('change', () => {
      const cur = (state.settings && state.settings.theme) || 'auto';
      if (cur !== 'light' && cur !== 'dark') applyTheme('auto');
    });
  }
}

// ---- 啟動 ---------------------------------------------------------------
async function bootstrap() {
  const st = await window.api.getState();
  state.settings = st.settings;
  state.paths = st.paths;
  state.configPath = st.configPath || '';
  state.packaged = st.packaged;
  state.appVersion = st.appVersion || '';
  state.systemLocale = st.systemLocale;
  state.backendAvailable = st.backendAvailable;
  state.releasesUrl = st.releasesUrl || '';

  await initI18n(state.settings.locale || mapSystemLocale(state.systemLocale));
  syncHtmlLang();
  applyTheme();
  await refreshConfig();

  // 全域事件訂閱（只訂一次）
  window.api.onEvent((ev) => jobHandlers.forEach((fn) => fn(ev)));
  window.api.onStderr((s) => appendLog(s));
  window.api.onRaw((line) => appendLog(line));
  // 註：job 退出由 runJob 內的 onExit 處理（終止 + 解除訂閱），此處不再全域攔截，避免競態。

  // log 抽屜
  const drawer = document.getElementById('log-drawer');
  const toggle = document.getElementById('log-toggle');
  toggle.onclick = () => {
    drawer.hidden = !drawer.hidden;
    toggle.textContent = drawer.hidden ? t('log.show') : t('log.hide');
    toggle.setAttribute('aria-expanded', String(!drawer.hidden));
  };
  // 清除日誌：緩衝與畫面一起清（appendLog 以 logBuffer 為準，只清 DOM 會被下一幀蓋回來）。
  document.getElementById('log-clear').onclick = () => {
    logBuffer = '';
    drawer.textContent = '';
  };
  document.getElementById('cancel-btn').onclick = cancelJob;

  // 語系變更時整體重繪
  onLocaleChange(() => {
    syncHtmlLang();
    applyStaticI18n();
    renderNav();
    renderEnvBadge();
    navigate(state.activeStep);
  });

  applyStaticI18n();
  renderEnvBadge();
  navigate('mode');

  // GUI 自動更新（打包版才會收到事件）
  setupUpdater();

  // 背景跑環境檢查
  runDoctor();
}

// 暴露給 settings view 用來切語系
ctx.setLocale = (loc) => {
  setLocale(loc);
};
ctx.getLocale = getLocale;
// 暴露給 settings view 即時預覽主題
ctx.applyTheme = applyTheme;

bootstrap();
