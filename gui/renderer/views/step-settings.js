// step-settings —— 帳號、下載/轉換選項、效能與執行環境、語言、環境檢查。
import { h, field, textInput, numberInput, toggle, select } from './dom.js';

export function renderSettings(ctx, container) {
  const { t, state } = ctx;
  const env = state.config.env || {};
  const s = state.settings;

  // 表單模型（編輯中的值）
  const form = {
    ms_username: env.ms_username || '',
    ms_password: env.ms_password || '',
    MS_RES_VERSION: env.MS_RES_VERSION || '',
    COLLECT_TIMING: (env.COLLECT_TIMING ?? 'true') === 'true',
    SAVE_DEBUG: (env.SAVE_DEBUG ?? 'false') === 'true',
    SAVE_RAW_JSON: (env.SAVE_RAW_JSON ?? 'false') === 'true',
    downloadConcurrency: s.downloadConcurrency,
    convertConcurrency: s.convertConcurrency,
    sequentialDownload: s.sequentialDownload,
    pythonPath: s.pythonPath || '',
    workDir: s.workDir || '',
    locale: ctx.getLocale(),
  };

  container.append(h('h1', { class: 'view-title' }, t('settings.title')));

  // --- 帳號 ---
  container.append(h('div', { class: 'section-title' }, t('settings.section.account')));
  container.append(field(t('settings.ms_username.label'),
    textInput(form.ms_username, (v) => (form.ms_username = v)), t('settings.ms_username.hint')));
  container.append(field(t('settings.ms_password.label'),
    textInput(form.ms_password, (v) => (form.ms_password = v), { type: 'password' }), t('settings.ms_password.hint')));

  // 備用帳號池：下載失敗時依序切換（config.ini [account] account_pool，JSON 陣列）。
  let pool = [];
  try { pool = JSON.parse(env.ACCOUNT_POOL || '[]'); } catch (_) { pool = []; }
  if (!Array.isArray(pool)) pool = [];
  pool = pool.map((a) => ({ username: (a && a.username) || '', password: (a && a.password) || '' }));
  const poolWrap = h('div');
  const renderPool = () => {
    poolWrap.innerHTML = '';
    pool.forEach((acct, i) => {
      poolWrap.append(h('div', { class: 'inline-input', style: 'margin-bottom:6px' },
        textInput(acct.username, (v) => (acct.username = v), { placeholder: t('settings.pool.username') }),
        textInput(acct.password, (v) => (acct.password = v), { type: 'password', placeholder: t('settings.pool.password') }),
        h('button', { class: 'ghost', onclick: () => { pool.splice(i, 1); renderPool(); } }, t('settings.pool.remove'))));
    });
    poolWrap.append(h('button', { class: 'ghost', onclick: () => { pool.push({ username: '', password: '' }); renderPool(); } },
      t('settings.pool.add')));
  };
  renderPool();
  container.append(field(t('settings.pool.label'), poolWrap, t('settings.pool.hint')));

  container.append(field(t('settings.res_version.label'),
    textInput(form.MS_RES_VERSION, (v) => (form.MS_RES_VERSION = v)), t('settings.res_version.hint')));

  // --- 下載/轉換選項 ---
  container.append(h('div', { class: 'section-title' }, t('settings.section.timing')));
  const debugToggle = toggle(t('settings.save_debug.label'), form.SAVE_DEBUG, (v) => (form.SAVE_DEBUG = v));
  const timingToggle = toggle(t('settings.collect_timing.label'), form.COLLECT_TIMING, (v) => (form.COLLECT_TIMING = v));
  // SAVE_RAW_JSON 勾選會強制 COLLECT_TIMING
  const rawToggle = toggle(t('settings.save_raw_json.label'), form.SAVE_RAW_JSON, (v) => {
    form.SAVE_RAW_JSON = v;
    if (v) {
      form.COLLECT_TIMING = true;
      const cb = timingToggle.querySelector('input');
      cb.checked = true;
      cb.disabled = true;
    } else {
      timingToggle.querySelector('input').disabled = false;
    }
  });
  if (form.SAVE_RAW_JSON) timingToggle.querySelector('input').disabled = true;
  container.append(field('', timingToggle, t('settings.collect_timing.hint')));
  container.append(field('', rawToggle, t('settings.save_raw_json.hint')));
  container.append(field('', debugToggle, t('settings.save_debug.hint')));

  // --- 效能與執行環境 ---
  container.append(h('div', { class: 'section-title' }, t('settings.section.runtime')));
  container.append(h('div', { class: 'row' },
    field(t('settings.download_concurrency.label'),
      numberInput(form.downloadConcurrency, (v) => (form.downloadConcurrency = v), { min: 1, max: 16 }),
      t('settings.download_concurrency.hint')),
    field(t('settings.convert_concurrency.label'),
      numberInput(form.convertConcurrency, (v) => (form.convertConcurrency = v), { min: 0, max: 32 }),
      t('settings.convert_concurrency.hint'))));
  container.append(field('', toggle(t('settings.sequential.label'), form.sequentialDownload, (v) => (form.sequentialDownload = v)),
    t('settings.sequential.hint')));

  // 工作目錄（含瀏覽）。留空時以 placeholder 顯示實際解析到的預設路徑（凍結版＝執行檔同層）。
  const workInput = textInput(form.workDir, (v) => (form.workDir = v),
    { placeholder: (state.paths && state.paths.workDir) || '' });
  const browseBtn = h('button', { class: 'ghost', onclick: async () => {
    const dir = await ctx.api.pickDir();
    if (dir) { form.workDir = dir; workInput.value = dir; }
  } }, t('btn.browse'));
  container.append(field(t('settings.work_dir.label'), h('div', { class: 'inline-input' }, workInput, browseBtn), t('settings.work_dir.hint')));

  // Python 路徑（僅 dev 模式顯示）
  if (!state.packaged) {
    const pyInput = textInput(form.pythonPath, (v) => (form.pythonPath = v));
    const pyBrowse = h('button', { class: 'ghost', onclick: async () => {
      const f = await ctx.api.pickFile();
      if (f) { form.pythonPath = f; pyInput.value = f; }
    } }, t('btn.browse'));
    container.append(field(t('settings.python_path.label'), h('div', { class: 'inline-input' }, pyInput, pyBrowse), t('settings.python_path.hint')));
  }

  // --- 語言 ---
  container.append(h('div', { class: 'section-title' }, t('settings.section.lang')));
  const localeOptions = [
    { value: 'zh-TW', label: '繁體中文' },
    { value: 'en', label: 'English' },
    { value: 'ja', label: '日本語' },
  ];
  container.append(field(t('settings.locale.label'),
    select(localeOptions, form.locale, (v) => { form.locale = v; ctx.setLocale(v); })));

  // --- 設定檔 ---
  container.append(h('div', { class: 'section-title' }, t('settings.section.config')));
  const openCfgBtn = h('button', { class: 'ghost', onclick: () => ctx.api.revealConfig() }, t('btn.openConfig'));
  container.append(field(t('settings.config.label'),
    h('div', { class: 'inline-input' }, h('span', { class: 'path' }, state.configPath || '—'), openCfgBtn),
    t('settings.config.hint')));

  // --- 關於與更新 ---
  container.append(h('div', { class: 'section-title' }, t('settings.section.about')));
  const verText = state.appVersion ? 'v' + state.appVersion : '—';
  const checkBtn = h('button', { class: 'ghost', onclick: () => {
    ctx.toast(t('update.checking'));
    ctx.api.checkUpdate();
  } }, t('btn.checkUpdate'));
  container.append(field(t('settings.version.label'),
    h('div', { class: 'inline-input' }, h('span', { class: 'path' }, verText), checkBtn),
    t('settings.version.hint')));

  // --- 環境檢查 ---
  container.append(h('div', { class: 'section-title' }, t('env.title')));
  container.append(renderDoctorPanel(ctx));

  // --- 動作 ---
  const save = h('button', { class: 'primary', onclick: async () => {
    const cleanPool = pool
      .map((a) => ({ username: a.username.trim(), password: a.password.trim() }))
      .filter((a) => a.username && a.password);
    await ctx.api.writeEnv({
      ms_username: form.ms_username,
      ms_password: form.ms_password,
      MS_RES_VERSION: form.MS_RES_VERSION,
      ACCOUNT_POOL: cleanPool.length ? JSON.stringify(cleanPool) : '',
      COLLECT_TIMING: form.COLLECT_TIMING ? 'true' : 'false',
      SAVE_DEBUG: form.SAVE_DEBUG ? 'true' : 'false',
      SAVE_RAW_JSON: form.SAVE_RAW_JSON ? 'true' : 'false',
    });
    await ctx.api.setSettings({
      downloadConcurrency: form.downloadConcurrency,
      convertConcurrency: form.convertConcurrency,
      sequentialDownload: form.sequentialDownload,
      pythonPath: form.pythonPath,
      workDir: form.workDir,
      locale: form.locale,
    });
    state.settings = (await ctx.api.getState()).settings;
    await ctx.refreshConfig();
    ctx.toast(t('settings.saved'));
  } }, t('btn.save'));
  container.append(h('div', { class: 'actions' }, save));
}

function renderDoctorPanel(ctx) {
  const { t, state } = ctx;
  const wrap = h('div', { class: 'doctor' });
  const d = state.doctor;

  const lines = [];
  if (d) {
    lines.push(d.chrome ? ['ok', t('env.chrome.ok')] : ['err', t('env.chrome.missing')]);
    lines.push(d.mjai_reviewer ? ['ok', t('env.mjai.ok')] : ['warn', t('env.mjai.missing')]);
    if (!d.frozen) {
      const pkgs = d.packages || {};
      const pkgOk = Object.values(pkgs).every(Boolean);
      lines.push(pkgOk ? ['ok', t('env.python.ok')] : ['err', t('env.python.missing')]);
      lines.push(d.tensoul ? ['ok', t('env.tensoul.ok')] : ['err', t('env.tensoul.missing')]);
    }
    lines.push(d.work_dir_writable ? ['ok', t('env.workdir.ok')] : ['err', t('env.workdir.missing')]);
  } else {
    lines.push(['', t('env.checking')]);
  }

  for (const [kind, msg] of lines) {
    const cls = kind === 'ok' ? 'notice ok' : kind === 'err' ? 'notice err' : 'notice';
    wrap.append(h('div', { class: cls }, msg));
  }

  const recheck = h('button', { class: 'ghost', onclick: async () => {
    await ctx.runDoctor();
    ctx.rerender();
  } }, t('btn.runDoctor'));
  wrap.append(h('div', { class: 'actions' }, recheck));
  return wrap;
}
