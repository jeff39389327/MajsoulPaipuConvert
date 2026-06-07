// step-download —— 執行 Stage 2（並行下載 + mjai 轉換），雙進度條 + 即時摘要。
import { h } from './dom.js';

export function renderDownload(ctx, container) {
  const { t, state } = ctx;

  container.append(h('h1', { class: 'view-title' }, t('download.title')));

  if (state.crawlOutputFile) {
    container.append(h('div', { class: 'notice' }, h('span', null, t('crawl.outputFile') + '：'),
      h('span', { class: 'path' }, state.crawlOutputFile)));
  }

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

  const off = ctx.onJobEvent((ev) => {
    if (ev.stage === 'download' && ev.type === 'stage_start') {
      total = ev.total || 0;
    } else if (ev.type === 'progress' && ev.phase === 'download') {
      dlDone = ev.done;
      setBar(dlBar, ev.done, ev.total || total);
      label.textContent = t('download.summary', { dl: dlDone, cv: cvDone, total: ev.total || total });
    } else if (ev.type === 'progress' && ev.phase === 'mjai') {
      cvDone = ev.done;
      setBar(cvBar, ev.done, ev.total || total);
      label.textContent = t('download.summary', { dl: dlDone, cv: cvDone, total: ev.total || total });
    } else if (ev.stage === 'download' && ev.type === 'stage_done') {
      setBar(dlBar, 1, 1);
      setBar(cvBar, 1, 1);
      label.textContent = t('download.done', { downloaded: ev.stats.downloaded ?? 0, total: ev.stats.total ?? 0 });
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
    dlDone = 0; cvDone = 0;
    setBar(dlBar, 0, 1); setBar(cvBar, 0, 1);
    label.textContent = t('status.running');
    const params = {};
    if (state.crawlOutputFile) params.input_list = state.crawlOutputFile;
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
