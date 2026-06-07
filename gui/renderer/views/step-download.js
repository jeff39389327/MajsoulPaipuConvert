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
      result.append(h('div', { class: 'notice err' }, ctx.t('error.' + ev.code) || ctx.t('error.generic', { code: ev.code })));
    }
  });

  startBtn.onclick = async () => {
    result.innerHTML = '';
    dlDone = 0; cvDone = 0;
    setBar(dlBar, 0, 1); setBar(cvBar, 0, 1);
    label.textContent = t('status.running');
    const params = {};
    if (state.crawlOutputFile) params.input_list = state.crawlOutputFile;
    await ctx.runJob('download', params);
  };

  return off;
}
