// dom —— 極簡 DOM 建構工具，供各 view 使用。

// h('div', {class:'x', onclick:fn}, child1, child2...) -> HTMLElement
export function h(tag, props, ...children) {
  const el = document.createElement(tag);
  if (props) {
    for (const [k, v] of Object.entries(props)) {
      if (v == null || v === false) continue;
      if (k === 'class') el.className = v;
      else if (k === 'html') el.innerHTML = v;
      else if (k.startsWith('on') && typeof v === 'function') el.addEventListener(k.slice(2).toLowerCase(), v);
      else if (k === 'value') el.value = v;
      else if (k === 'checked') el.checked = !!v;
      else el.setAttribute(k, v);
    }
  }
  for (const c of children.flat()) {
    if (c == null || c === false) continue;
    el.append(c.nodeType ? c : document.createTextNode(String(c)));
  }
  return el;
}

// 唯一 id 產生器（供 label/控件/說明文字的無障礙關聯使用）
let _uid = 0;
const uid = (prefix) => `${prefix}-${++_uid}`;
const LABELABLE = /^(INPUT|SELECT|TEXTAREA)$/;

// 標準欄位容器：label + 控件 + hint。
// 為無障礙，把 <label> 綁到控件（for / aria-labelledby），hint 綁為 aria-describedby。
export function field(labelText, control, hintText) {
  const fieldEl = h('div', { class: 'field' });

  // 空 labelText（如 toggle 自帶文字）不渲染多餘的空 <label>。
  if (labelText) {
    const labelEl = h('label', null, labelText);
    if (control && control.nodeType === 1) {
      if (LABELABLE.test(control.tagName)) {
        const id = control.id || uid('ctl');
        control.id = id;
        labelEl.setAttribute('for', id);
      } else {
        // 群組型控件（chips/inline-input…）：用 aria-labelledby 指回 label。
        const lid = uid('lbl');
        labelEl.id = lid;
        const prev = control.getAttribute('aria-labelledby');
        control.setAttribute('aria-labelledby', prev ? `${prev} ${lid}` : lid);
      }
    }
    fieldEl.append(labelEl);
  }

  fieldEl.append(control);

  if (hintText) {
    const hid = uid('hint');
    fieldEl.append(h('div', { class: 'hint', id: hid }, hintText));
    if (control && control.nodeType === 1 && LABELABLE.test(control.tagName)) {
      const prev = control.getAttribute('aria-describedby');
      control.setAttribute('aria-describedby', prev ? `${prev} ${hid}` : hid);
    }
  }
  return fieldEl;
}

// 文字輸入
export function textInput(value, oninput, opts = {}) {
  return h('input', { type: opts.type || 'text', value: value ?? '', oninput: (e) => oninput(e.target.value), placeholder: opts.placeholder || '' });
}

// 數字輸入
export function numberInput(value, oninput, opts = {}) {
  return h('input', { type: 'number', value: value ?? 0, min: opts.min ?? 0, max: opts.max ?? 99999, oninput: (e) => oninput(Number(e.target.value)) });
}

// 開關 (原生 checkbox，CSS 畫成 switch；鍵盤與報讀器原生可用)
export function toggle(labelText, checked, onchange, disabled = false) {
  const input = h('input', { type: 'checkbox', checked, disabled, onchange: (e) => onchange(e.target.checked) });
  return h('label', { class: 'toggle' }, input, h('span', null, labelText));
}

// 多選 chips；values 為目前選取陣列，options 為 [{value,label}]。
// 用真正的 <button aria-pressed>，鍵盤可達、報讀器會播報選取狀態。
export function chips(options, values, onchange) {
  const set = new Set(values);
  const wrap = h('div', { class: 'checks', role: 'group' });
  for (const opt of options) {
    const on = set.has(opt.value);
    const chip = h('button', { type: 'button', class: 'chip' + (on ? ' on' : ''), 'aria-pressed': String(on) }, opt.label);
    chip.onclick = () => {
      const nowOn = !set.has(opt.value);
      if (nowOn) set.add(opt.value);
      else set.delete(opt.value);
      chip.classList.toggle('on', nowOn);
      chip.setAttribute('aria-pressed', String(nowOn));
      onchange([...set]);
    };
    wrap.append(chip);
  }
  return wrap;
}

// 下拉
export function select(options, value, onchange) {
  const sel = h('select', { onchange: (e) => onchange(e.target.value) });
  for (const opt of options) {
    sel.append(h('option', { value: opt.value, selected: opt.value === value }, opt.label));
  }
  return sel;
}
