// step-download —— 執行 Stage 2（並行下載 + mjai 轉換），雙進度條 + 即時摘要。
import { h, field, textInput } from './dom.js';

export function renderDownload(ctx, container) {
  const { t, state } = ctx;

  container.append(h('h1', { class: 'view-title' }, t('download.title')));

  // ID 清單（txt）位置：由 Stage 1 自動帶入，也可直接指定（跳過爬取、單獨執行本步）。
  // 留空＝後端預設（工作資料夾的 tonpuulist.txt）。
  if (state.crawlOutputFile && !state.downloadInputList) {
    state.downloadInputList = state.crawlOutputFile;
  }
  const defaultList = state.paths && state.paths.workDir
    ? `${state.paths.workDir}\\tonpuulist.txt` : 'tonpuulist.txt';
  const listInput = textInput(state.downloadInputList || '', (v) => (state.downloadInputList = v),
    { placeholder: defaultList });
  const browseBtn = h('button', { class: 'ghost', onclick: async () => {
    const f = await ctx.api.pickFile();
    if (f) { state.downloadInputList = f; listInput.value = f; }
  } }, t('btn.browse'));
  container.append(field(t('download.inputList.label'),
    h('div', { class: 'inline-input' }, listInput, browseBtn), t('download.inputList.hint')));

  const dlBar = h('div', { class: 'bar' }, h('span'));
  const cvBar = h('div', { class: 'bar' }, h('span'));
  const label = h('div', { class: 'progress-label' }, t('download.idle'));
  container.append(h('div', { class: 'progress-wrap dual' },
    h('div', { class: 'hint' }, t('download.phase.download')), dlBar,
    h('div', { class: 'hint' }, t('download.phase.mjai')), cvBar, label));

  const result = h('div');
  container.append(result);

  let total = 0;
  const startBtn = h('button', { class: 'primary' }, t('btn.start'));
  container.append(h('div', { class: 'actions' }, startBtn));

  const setBar = (bar, done, tot) => {
    const pct = tot ? Math.round((done / tot) * 100) : 0;
    bar.querySelector('span').style.width = pct + '%';
  };

  let dlDone = 0;
  let cvDone = 0;
  let failCount = 0;

  const summaryText = (tot) => failCount > 0
    ? t('download.summaryFail', { dl: dlDone, cv: cvDone, total: tot, fail: failCount })
    : t('download.summary', { dl: dlDone, cv: cvDone, total: tot });

  const off = ctx.onJobEvent((ev) => {
    if (ev.stage === 'download' && ev.type === 'stage_start') {
      total = ev.total || 0;
    } else if (ev.type === 'progress' && ev.phase === 'download') {
      dlDone = ev.done;
      failCount = ev.failed || failCount;
      setBar(dlBar, ev.done, ev.total || total);
      label.textContent = summaryText(ev.total || total);
    } else if (ev.type === 'progress' && ev.phase === 'mjai') {
      cvDone = ev.done;
      setBar(cvBar, ev.done, ev.total || total);
      label.textContent = summaryText(ev.total || total);
    } else if (ev.stage === 'download' && ev.type === 'stage_done') {
      setBar(dlBar, 1, 1);
      setBar(cvBar, 1, 1);
      label.textContent = t('download.done', { downloaded: ev.stats.downloaded ?? 0, total: ev.stats.total ?? 0 });
      // 失敗摘要：已記錄於斷點檔，下次執行自動重試；提供開啟斷點檔位置。
      if (ev.stats.failed > 0) {
        const box = h('div', { class: 'notice err' },
          h('div', null, t('download.failedSummary', { fail: ev.stats.failed })));
        if (Array.isArray(ev.stats.failed_uuids) && ev.stats.failed_uuids.length) {
          box.append(h('div', { class: 'path' }, ev.stats.failed_uuids.join('\n')));
        }
        if (ev.stats.checkpoint_path) {
          box.append(h('div', { class: 'path' }, ev.stats.checkpoint_path),
            h('div', { class: 'actions' },
              h('button', { class: 'ghost', onclick: () => ctx.api.showItem(ev.stats.checkpoint_path) },
                t('download.checkpoint'))));
        }
        result.append(box);
      }
      // 顯示輸出資料夾的「絕對路徑」並提供開啟按鈕，方便使用者直接找到產出的牌譜檔。
      const dir = ev.stats.output_dir;
      if (dir) {
        result.append(h('div', { class: 'notice ok' },
          h('div', null, t('download.outputDir')),
          h('div', { class: 'path' }, dir),
          h('div', { class: 'actions' },
            h('button', { class: 'ghost', onclick: () => ctx.api.openPath(dir) }, t('btn.openFolder')))));
      }
    } else if (ev.type === 'notice') {
      // 非致命通知（自動更新資源版本、換帳號、重試上次失敗…）：顯示提示但不中止流程。
      // 後端把變數放在 ev.msg；以多個常見占位字一次帶入，缺 key 時退回原文。
      const key = 'notice.' + ev.code;
      const vars = { version: ev.msg, user: ev.msg, count: ev.msg, msg: ev.msg };
      const localized = ctx.t(key, vars);
      const text = localized === key ? (ev.msg || ev.code) : localized;
      result.append(h('div', { class: 'notice' }, text));
    } else if (ev.type === 'error' && ev.fatal) {
      // t() 缺 key 時回傳原 key，故以「是否等於 key」判斷有無在地化字串，沒有就用 generic。
      const localized = ctx.t('error.' + ev.code);
      const headline = localized === 'error.' + ev.code
        ? ctx.t('error.generic', { code: ev.code })
        : localized;
      const box = h('div', { class: 'notice err' }, h('div', null, headline));
      // 後端把真正的例外字串放在 ev.msg；附在錯誤框內，避免使用者只看到籠統訊息。
      if (ev.msg) box.append(h('div', { class: 'path' }, ev.msg));
      result.append(box);
    }
  });

  async function startDownload() {
    result.innerHTML = '';
    dlDone = 0; cvDone = 0; failCount = 0;
    setBar(dlBar, 0, 1); setBar(cvBar, 0, 1);
    label.textContent = t('status.running');
    const params = {};
    const listPath = (state.downloadInputList || '').trim();
    if (listPath) params.input_list = listPath;
    await ctx.runJob('download', params);
  }
  startBtn.onclick = startDownload;

  // 由 Stage 1 自動串接而來：進場即自動開始下載（只觸發一次）。
  if (state.autoStartDownload) {
    state.autoStartDownload = false;
    startDownload();
  }

  return off;
}
