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
  systemLocale: 'en',
  backendAvailable: true,
  config: { env: {}, crawler: null },
  doctor: null,
  crawlOutputFile: null, // Stage 1 完成後的輸出檔，供 Stage 2 自動接手
  activeStep: 'mode',
  jobStatus: 'idle', // idle | running | done | error
};

// ---- job 事件管線 -------------------------------------------------------
const jobHandlers = new Set();
function onJobEvent(cb) {
  jobHandlers.add(cb);
  return () => jobHandlers.delete(cb);
}

function appendLog(text) {
  const drawer = document.getElementById('log-drawer');
  drawer.textContent += text.endsWith('\n') ? text : text + '\n';
  drawer.scrollTop = drawer.scrollHeight;
}

function setStatus(status) {
  state.jobStatus = status;
  const el = document.getElementById('status-text');
  el.className = 'status ' + status;
  el.textContent = t('status.' + status);
  document.getElementById('cancel-btn').hidden = status !== 'running';
}

// 啟動 job 並回傳 Promise（於 done 或 exit 時 resolve）。onEvent 收到每個 py:event。
function runJob(kind, params, dryRun, onEvent) {
  return new Promise((resolve) => {
    setStatus('running');
    const off = onJobEvent((ev) => {
      if (onEvent) onEvent(ev);
      if (ev.type === 'error' && ev.fatal) setStatus('error');
      if (ev.type === 'done') {
        off();
        if (state.jobStatus !== 'error') setStatus(ev.ok ? 'done' : 'error');
        resolve(ev);
      }
    });
    window.api.startJob(kind, params || {}, !!dryRun).then((ok) => {
      if (!ok) {
        off();
        setStatus('error');
        resolve({ type: 'done', ok: false });
      }
    });
  });
}

function cancelJob() {
  window.api.cancelJob();
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
  await runJob('doctor', {}, false, (ev) => {
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
  state.systemLocale = st.systemLocale;
  state.backendAvailable = st.backendAvailable;

  await initI18n(state.settings.locale || mapSystemLocale(state.systemLocale));
  await refreshConfig();

  // 全域事件訂閱（只訂一次）
  window.api.onEvent((ev) => jobHandlers.forEach((fn) => fn(ev)));
  window.api.onStderr((s) => appendLog(s));
  window.api.onRaw((line) => appendLog(line));
  window.api.onExit(() => {
    if (state.jobStatus === 'running') setStatus('idle');
  });

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

  // 背景跑環境檢查
  runDoctor();
}

// 暴露給 settings view 用來切語系
ctx.setLocale = (loc) => {
  setLocale(loc);
};
ctx.getLocale = getLocale;

bootstrap();
