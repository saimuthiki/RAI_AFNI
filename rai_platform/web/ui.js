// DOM helpers and the shared vocabulary of the console: coverage chips, stage
// badges, tables. Everything here is pure — it takes data and returns nodes.

/** Create an element. `a` may hold attributes, `class`, `text`, `data`, `on`.
 *  There is deliberately no `html` escape hatch: every string this console
 *  renders comes from the gateway, and a guardrail console that injects
 *  detector output as markup would be its own injection sink. Everything goes
 *  through textContent. */
export function el(tag, a = {}, kids = []) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(a)) {
    if (v === null || v === undefined || v === false) continue;
    if (k === 'class') node.className = v;
    else if (k === 'text') node.textContent = v;
    else if (k === 'on') for (const [ev, fn] of Object.entries(v)) node.addEventListener(ev, fn);
    else if (k === 'data') for (const [dk, dv] of Object.entries(v)) node.dataset[dk] = dv;
    else if (v === true) node.setAttribute(k, '');
    else node.setAttribute(k, String(v));
  }
  for (const kid of [].concat(kids)) {
    if (kid === null || kid === undefined || kid === false) continue;
    node.append(kid instanceof Node ? kid : document.createTextNode(String(kid)));
  }
  return node;
}

export const frag = (kids) => {
  const f = document.createDocumentFragment();
  for (const k of [].concat(kids)) if (k) f.append(k);
  return f;
};

export function clear(node) { while (node.firstChild) node.firstChild.remove(); return node; }

// ---------------------------------------------------------------- coverage --

/** The five states, in ordinal order. `pips` is the second, non-colour channel:
 *  4 filled means "runs today", 0 means "nothing looked". */
export const COVERAGE = [
  { key: 'implemented', pips: 4,
    short: 'runs today',
    say: 'A rail exists, its dependencies are present, and it runs on live traffic.' },
  { key: 'dependency-missing', pips: 3,
    short: 'cannot run',
    say: 'The rail is mounted but its library or model weights are absent, so it reports "could not judge". Fails closed — it is not protection.' },
  { key: 'cloud-not-configured', pips: 2,
    short: 'not wired',
    say: 'The only tool needs a paid managed service that is not configured here.' },
  { key: 'offline-only', pips: 1,
    short: 'CI only',
    say: 'A red-team or batch tool. It belongs in CI and is never reachable from the request path, so it is not runtime cover.' },
  { key: 'gap', pips: 0,
    short: 'nothing looked',
    say: 'Nothing implements this capability. No rail looks at it at all.' },
];

const COV_BY_KEY = new Map(COVERAGE.map((c) => [c.key, c]));
export const coverageMeta = (key) => COV_BY_KEY.get(key) ?? {
  key, pips: 0, short: 'unknown state', say: 'The gateway reported a coverage state this console does not know.' };

/** A coverage chip: pip meter + always-present text label + optional count. */
export function covChip(state, count = null, { title = true } = {}) {
  const meta = coverageMeta(state);
  const pips = el('span', { class: 'cov__pips', 'aria-hidden': 'true' },
    [0, 1, 2, 3].map((i) => el('i', { class: i < meta.pips ? 'on' : '' })));
  return el('span', {
    class: `cov cov--${state}`,
    title: title ? `${state} — ${meta.say}` : null,
  }, [
    pips,
    el('span', { class: 'cov__label', text: state }),
    count === null ? null : el('span', { class: 'cov__n', text: String(count) }),
  ]);
}

/** Stacked ordinal bar. Segments never touch (2px gap) and each carries its own
 *  title; the counts are always printed as chips beside it, so the bar is
 *  reinforcement rather than the only reading of the numbers. */
export function covBar(counts) {
  const total = COVERAGE.reduce((s, c) => s + (counts[c.key] || 0), 0) || 1;
  return el('div', {
    class: 'covbar', role: 'img',
    'aria-label': COVERAGE.filter((c) => counts[c.key])
      .map((c) => `${counts[c.key]} ${c.key}`).join(', ') || 'no capabilities',
  }, COVERAGE.filter((c) => counts[c.key]).map((c) => el('span', {
    class: 'covbar__seg',
    data: { state: c.key },
    style: `flex: ${counts[c.key]} 0 0`,
    title: `${counts[c.key]} × ${c.key}`,
  })));
}

export function covLegend() {
  return el('ul', { class: 'covlegend' }, COVERAGE.map((c) => el('li', {}, [
    covChip(c.key, null, { title: false }),
    el('dfn', { text: c.short }),
  ])));
}

// ------------------------------------------------------------ stage badges --

export const STAGES = {
  1: { n: '1', name: 'Stage 1', kind: 'free · deterministic', cls: '1',
       say: 'Regex, checksums, lexicons. Sub-millisecond, runs on 100% of traffic.' },
  2: { n: '2', name: 'Stage 2', kind: 'local model', cls: '2',
       say: 'A locally-run classifier or NLI cross-encoder. Runs only when stage 1 asked for a second look.' },
  3: { n: '3', name: 'Stage 3', kind: 'paid judge', cls: '3',
       say: 'A cloud API or an LLM judge. Last resort, and the only stage with a per-call price.' },
  4: { n: '◇', name: 'Offline', kind: 'never in the request path', cls: 'off',
       say: 'CI and red-team only. Counting it as runtime protection would be false.' },
};

export const stageMeta = (stage) => STAGES[Number(stage)] ?? {
  n: '?', name: `Stage ${stage}`, kind: 'unknown stage', cls: 'off',
  say: 'The gateway reported a stage this console does not know.' };

export function stageTag(stage, { withKind = false } = {}) {
  const m = stageMeta(stage);
  return el('span', { class: `stag stag--${m.cls}`, title: `${m.name} — ${m.say}` }, [
    el('span', { class: 'stag__n', text: m.n, 'aria-hidden': 'true' }),
    el('span', { text: withKind ? `${m.name} · ${m.kind}` : m.name }),
  ]);
}

// ------------------------------------------------------------------ layout --

export function pageHead(eyebrow, title, lede) {
  return el('header', { class: 'head' }, [
    el('p', { class: 'head__eyebrow', text: eyebrow }),
    el('h1', { class: 'head__title', text: title }),
    lede ? el('p', { class: 'head__lede', text: lede }) : null,
  ]);
}

export function rule(title, datum) {
  return el('div', { class: 'rule' }, [
    el('h2', { class: 'rule__t', text: title }),
    datum ? el('span', { class: 'rule__d', text: datum }) : null,
  ]);
}

export function field(label, control) {
  const id = control.id || `f${Math.random().toString(36).slice(2, 8)}`;
  control.id = id;
  return el('div', { class: 'field' }, [
    el('label', { class: 'eyebrow', for: id, text: label }),
    control,
  ]);
}

export function table(headers, rows) {
  return el('div', { class: 'tablewrap' }, [
    el('table', {}, [
      el('thead', {}, el('tr', {}, headers.map((h) => el('th', {
        scope: 'col', text: typeof h === 'string' ? h : h.label,
        style: typeof h === 'object' && h.width ? `width:${h.width}` : null,
      })))),
      el('tbody', {}, rows),
    ]),
  ]);
}

export function errorBox(where, err) {
  return el('div', { class: 'errorbox', role: 'alert' }, [
    el('strong', { text: `${where} failed. ` }),
    el('span', { text: 'Nothing is being shown for this panel rather than showing something that might be wrong. ' }),
    el('code', { text: String(err && err.message ? err.message : err) }),
  ]);
}

export const empty = (text) => el('p', { class: 'empty', text });

export function pill(text, cls = '') {
  return el('span', { class: `tag ${cls}`.trim(), text });
}

/** Round a score for display without pretending to precision we do not have. */
export const fmtScore = (s) =>
  (s === null || s === undefined) ? null : Number(s).toFixed(2);
