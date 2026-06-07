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

// 標準欄位容器：label + 控件 + hint
export function field(labelText, control, hintText) {
  return h(
    'div',
    { class: 'field' },
    h('label', null, labelText),
    control,
    hintText ? h('div', { class: 'hint' }, hintText) : null
  );
}

// 文字輸入
export function textInput(value, oninput, opts = {}) {
  return h('input', { type: opts.type || 'text', value: value ?? '', oninput: (e) => oninput(e.target.value), placeholder: opts.placeholder || '' });
}

// 數字輸入
export function numberInput(value, oninput, opts = {}) {
  return h('input', { type: 'number', value: value ?? 0, min: opts.min ?? 0, max: opts.max ?? 99999, oninput: (e) => oninput(Number(e.target.value)) });
}

// 開關 (checkbox)
export function toggle(labelText, checked, onchange, disabled = false) {
  const input = h('input', { type: 'checkbox', checked, disabled, onchange: (e) => onchange(e.target.checked) });
  return h('label', { class: 'toggle' }, input, h('span', null, labelText));
}

// 多選 chips；values 為目前選取陣列，options 為 [{value,label}]
export function chips(options, values, onchange) {
  const set = new Set(values);
  const wrap = h('div', { class: 'checks' });
  for (const opt of options) {
    const chip = h('span', { class: 'chip' + (set.has(opt.value) ? ' on' : '') }, opt.label);
    chip.onclick = () => {
      if (set.has(opt.value)) set.delete(opt.value);
      else set.add(opt.value);
      chip.classList.toggle('on');
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
