// step-crawl —— 執行 Stage 1（爬牌譜 ID）。不定量進度 + 可取消 + 完成後自動接到下載。
import { h, toggle } from './dom.js';
import { buildConfig } from './step-mode.js';

export function renderCrawl(ctx, container) {
  const { t, state } = ctx;
  const form = state.crawlerForm;

  container.append(h('h1', { class: 'view-title' }, t('crawl.title')));

  // date_room_player 續跑提示
  if (form && form.crawler_mode === 'date_room_player') {
    container.append(h('div', { class: 'notice' }, t('crawl.resumeHint')));
  }

  const label = h('div', { class: 'progress-label' }, t('crawl.idle'));
  const bar = h('div', { class: 'bar' }, h('span'));
  container.append(h('div', { class: 'progress-wrap' }, bar, label));

  const result = h('div');
  container.append(result);

  let dryRun = false;
  const dryToggle = toggle('dry-run', false, (v) => (dryRun = v));

  const startBtn = h('button', { class: 'primary' }, t('btn.start'));
  const actions = h('div', { class: 'actions' }, startBtn, dryToggle);
  container.append(actions);

  // 訂閱 job 事件（離開此 view 時取消）
  const off = ctx.onJobEvent((ev) => {
    if (ev.stage === 'crawl' && ev.type === 'progress') {
      label.textContent = t('crawl.collected', { count: ev.count });
    } else if (ev.stage === 'crawl' && ev.type === 'stage_done') {
      bar.classList.remove('indeterminate');
      bar.querySelector('span').style.width = '100%';
      state.crawlOutputFile = ev.stats.output_file;
      label.textContent = t('crawl.done', { count: ev.stats.collected ?? 0 });
      result.innerHTML = '';
      result.append(h('div', { class: 'notice ok' },
        h('div', null, t('crawl.outputFile')),
        h('div', { class: 'path' }, ev.stats.output_file || '')));
      result.append(h('div', { class: 'actions' },
        h('button', { class: 'primary', onclick: () => ctx.navigate('download') }, t('btn.toDownload'))));
    } else if (ev.type === 'error' && ev.fatal) {
      bar.classList.remove('indeterminate');
      result.append(h('div', { class: 'notice err' }, ctx.t('error.' + ev.code) || ctx.t('error.generic', { code: ev.code })));
    }
  });

  startBtn.onclick = async () => {
    if (!form) { ctx.navigate('mode'); return; }
    result.innerHTML = '';
    bar.classList.add('indeterminate');
    label.textContent = t('status.running');
    await ctx.api.writeCrawler(buildConfig(form));
    await ctx.runJob('crawl', { config: buildConfig(form) }, dryRun);
    bar.classList.remove('indeterminate');
  };

  return off;
}
