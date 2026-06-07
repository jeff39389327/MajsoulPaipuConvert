// step-crawl —— 執行 Stage 1（爬牌譜 ID）。不定量進度 + 可取消 + 完成後自動接到下載。
import { h } from './dom.js';
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

  const startBtn = h('button', { class: 'primary' }, t('btn.start'));
  const actions = h('div', { class: 'actions' }, startBtn);
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

  startBtn.onclick = async () => {
    if (!form) { ctx.navigate('mode'); return; }
    result.innerHTML = '';
    bar.classList.add('indeterminate');
    label.textContent = t('status.running');
    await ctx.api.writeCrawler(buildConfig(form));
    await ctx.runJob('crawl', { config: buildConfig(form) });
    bar.classList.remove('indeterminate');
  };

  return off;
}
