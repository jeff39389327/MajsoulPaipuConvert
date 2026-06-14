// step-mode —— 選擇 crawler_mode 並填寫對應參數。label/value 分離：顯示翻譯、寫入英文原值。
import { h, field, textInput, numberInput, toggle, chips, select } from './dom.js';

const MODES = ['auto', 'manual', 'date_room', 'date_room_player', 'date_room_api'];
const PERIODS = ['4w', '1w', '3d', '1d'];
const RANKS = ['Throne', 'Jade', 'Gold', 'Throne East', 'Jade East', 'Gold East', 'All'];
const ROOMS = ['Throne', 'Jade', 'Gold', 'Throne East', 'Jade East', 'Gold East'];

function defaultForm(existing) {
  const e = existing || {};
  return {
    crawler_mode: e.crawler_mode || 'date_room',
    time_periods: e.time_periods && e.time_periods.length ? e.time_periods : ['4w', '1w', '3d'],
    ranks: e.ranks && e.ranks.length ? e.ranks : ['Gold'],
    max_players_per_period: e.max_players_per_period ?? 20,
    paipu_limit: e.paipu_limit ?? 9999,
    save_screenshots: e.save_screenshots ?? true,
    manual_player_urls: e.manual_player_urls || [],
    start_date: e.start_date || '',
    end_date: e.end_date || '',
    target_room: e.target_room || 'Jade',
    game_mode: e.game_mode || 'yonma',
    output_filename: e.output_filename || 'date_room_list.txt',
    headless_mode: e.headless_mode ?? true,
    fast_mode: e.fast_mode ?? false,
  };
}

// 對齊 CrawlerConfig.validate()
function validate(form, t) {
  if (form.crawler_mode === 'manual') {
    if (!form.manual_player_urls.length) return t('validation.required');
  } else if (form.crawler_mode === 'auto') {
    if (!form.time_periods.length || !form.ranks.length) return t('validation.pickOne');
  } else {
    if (!form.start_date || !form.end_date) return t('validation.required');
    if (!/^\d{4}-\d{2}-\d{2}$/.test(form.start_date) || !/^\d{4}-\d{2}-\d{2}$/.test(form.end_date))
      return t('validation.dateFormat');
    if (form.start_date > form.end_date) return t('validation.dateRange');
    if (!form.target_room) return t('validation.required');
  }
  return null;
}

export function renderMode(ctx, container) {
  const { t, state } = ctx;
  if (!state.crawlerForm) state.crawlerForm = defaultForm(state.config.crawler);
  const form = state.crawlerForm;

  container.append(h('h1', { class: 'view-title' }, t('mode.title')));
  container.append(h('p', { class: 'view-sub' }, t('mode.subtitle')));

  // 模式卡片
  const cards = h('div', { class: 'cards' });
  for (const m of MODES) {
    const card = h('div', { class: 'card' + (form.crawler_mode === m ? ' on' : '') },
      h('div', { class: 'card-title' }, t('mode.' + m + '.label')),
      h('div', { class: 'card-desc' }, t('mode.' + m + '.desc')));
    card.onclick = () => {
      form.crawler_mode = m;
      // 切換預設輸出檔名
      form.output_filename = (m === 'auto' || m === 'manual') ? 'tonpuulist.txt' : 'date_room_list.txt';
      ctx.rerender();
    };
    cards.append(card);
  }
  container.append(cards);

  // 動態欄位
  const fields = h('div');
  if (form.crawler_mode === 'auto') {
    fields.append(field(t('mode.field.time_periods'),
      chips(PERIODS.map((p) => ({ value: p, label: t('enum.period.' + p) })), form.time_periods, (v) => (form.time_periods = v))));
    fields.append(field(t('mode.field.ranks'),
      chips(RANKS.map((r) => ({ value: r, label: t('enum.rank.' + r) })), form.ranks, (v) => (form.ranks = v))));
    fields.append(h('div', { class: 'row' },
      field(t('mode.field.max_players'), numberInput(form.max_players_per_period, (v) => (form.max_players_per_period = v), { min: 1, max: 200 })),
      field(t('mode.field.paipu_limit'), numberInput(form.paipu_limit, (v) => (form.paipu_limit = v), { min: 1, max: 99999 }))));
    fields.append(field('', toggle(t('mode.field.save_screenshots'), form.save_screenshots, (v) => (form.save_screenshots = v))));
  } else if (form.crawler_mode === 'manual') {
    const ta = h('textarea', { oninput: (e) => (form.manual_player_urls = e.target.value.split(/\r?\n/).map((x) => x.trim()).filter(Boolean)) });
    ta.value = form.manual_player_urls.join('\n');
    fields.append(field(t('mode.field.manual_urls'), ta));
  } else {
    fields.append(h('div', { class: 'row' },
      field(t('mode.field.start_date'), textInput(form.start_date, (v) => (form.start_date = v), { type: 'date' })),
      field(t('mode.field.end_date'), textInput(form.end_date, (v) => (form.end_date = v), { type: 'date' }))));
    fields.append(field(t('mode.field.target_room'),
      select(ROOMS.map((r) => ({ value: r, label: t('enum.rank.' + r) })), form.target_room, (v) => (form.target_room = v))));
    // 三/四麻選擇：僅純 API 模式 (date_room_api) 支援三麻收集 (pl3)；Selenium 模式只有四麻。
    // 非 API 模式時不顯示此選單，且 buildConfig 一律送 yonma（唯一權威重設點，毋需在此變異 form）。
    if (form.crawler_mode === 'date_room_api') {
      fields.append(field(t('mode.field.game_mode'),
        select([
          { value: 'yonma', label: t('enum.gameMode.yonma') },
          { value: 'sanma', label: t('enum.gameMode.sanma') },
        ], form.game_mode, (v) => (form.game_mode = v)),
        t('mode.field.game_mode.hint')));
    }
  }

  // 通用欄位
  fields.append(field(t('mode.field.output_filename'), textInput(form.output_filename, (v) => (form.output_filename = v))));
  // date_room_api 走純 HTTP API，不開瀏覽器，headless/fast 對它無意義，故隱藏。
  const usesBrowser = form.crawler_mode !== 'date_room_api';
  if (usesBrowser) {
    fields.append(field('', toggle(t('mode.field.headless'), form.headless_mode, (v) => (form.headless_mode = v))));
    if (form.crawler_mode !== 'manual') {
      fields.append(field('', toggle(t('mode.field.fast'), form.fast_mode, (v) => (form.fast_mode = v))));
    }
  }
  container.append(fields);

  // 錯誤提示位
  const errBox = h('div');
  container.append(errBox);

  const next = h('button', { class: 'primary', onclick: async () => {
    const err = validate(form, t);
    errBox.innerHTML = '';
    if (err) { errBox.append(h('div', { class: 'notice err' }, err)); return; }
    await ctx.api.writeCrawler(buildConfig(form));
    ctx.navigate('crawl');
  } }, t('btn.next'));
  container.append(h('div', { class: 'actions' }, h('div', { class: 'spacer' }), next));
}

// 只輸出該模式相關欄位（避免寫入無關鍵造成混淆，但保留 spider 接受的欄位）
export function buildConfig(form) {
  const base = {
    crawler_mode: form.crawler_mode,
    output_filename: form.output_filename,
    headless_mode: form.headless_mode,
    fast_mode: form.fast_mode,
    paipu_limit: form.paipu_limit,
  };
  if (form.crawler_mode === 'auto') {
    return Object.assign(base, {
      time_periods: form.time_periods,
      ranks: form.ranks,
      max_players_per_period: form.max_players_per_period,
      save_screenshots: form.save_screenshots,
    });
  }
  if (form.crawler_mode === 'manual') {
    return Object.assign(base, { manual_player_urls: form.manual_player_urls });
  }
  return Object.assign(base, {
    start_date: form.start_date,
    end_date: form.end_date,
    target_room: form.target_room,
    // 三麻僅 date_room_api 支援；其餘 date_room 模式一律送四麻（defaultForm 已保證 game_mode 有值）。
    game_mode: form.crawler_mode === 'date_room_api' ? form.game_mode : 'yonma',
  });
}
