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
  packaged: false,
  appVersion: '',
  systemLocale: 'en',
  backendAvailable: true,
  config: { env: {}, crawler: null },
  doctor: null,
  crawlOutputFile: null, // Stage 1 完成後的輸出檔，供 Stage 2 自動接手
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

function setupUpdater() {
  if (!window.api.onUpdate) return;
  const banner = ensureUpdateBanner();
  const show = (html) => { banner.innerHTML = html; banner.hidden = false; };

  window.api.onUpdate((ev) => {
    if (!ev || !ev.state) return;
    if (ev.state === 'available') {
      show(`<span>${t('update.available', { version: ev.version || '' })}</span>`);
    } else if (ev.state === 'progress') {
      show(`<span>${t('update.downloading', { percent: ev.percent ?? 0 })}</span>`);
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
    const item = document.createElement('div');
    item.className = 'nav-item' + (step.id === state.activeStep ? ' active' : '');
    item.innerHTML = `<span class="idx">${step.icon}</span><span>${t('nav.' + step.id)}</span>`;
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

function navigate(stepId) {
  if (activeCleanup) {
    activeCleanup();
    activeCleanup = null;
  }
  state.activeStep = stepId;
  renderNav();
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
  document.getElementById('log-toggle').textContent = t('log.show');
  document.getElementById('cancel-btn').textContent = t('btn.cancel');
  setStatus(state.jobStatus);
}

function mapSystemLocale(loc) {
  if (!loc) return 'en';
  if (loc.startsWith('zh')) return 'zh-TW';
  if (loc.startsWith('ja')) return 'ja';
  return 'en';
}

// ---- 啟動 ---------------------------------------------------------------
async function bootstrap() {
  const st = await window.api.getState();
  state.settings = st.settings;
  state.paths = st.paths;
  state.packaged = st.packaged;
  state.appVersion = st.appVersion || '';
  state.systemLocale = st.systemLocale;
  state.backendAvailable = st.backendAvailable;

  await initI18n(state.settings.locale || mapSystemLocale(state.systemLocale));
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
  };
  document.getElementById('cancel-btn').onclick = cancelJob;

  // 語系變更時整體重繪
  onLocaleChange(() => {
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

bootstrap();
