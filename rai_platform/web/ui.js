// DOM helpers and the shared vocabulary of the console: coverage chips, stage
// badges, claim-strength scales, phase brackets, tables. Everything here is
// pure — it takes data and returns nodes.
//
// TWO VISUAL LANGUAGES ARE KEPT APART ON PURPOSE, because conflating them is
// the mistake this console exists to prevent:
//
//   CASCADE STAGE (1 / 2 / 3 / offline) is a *cost* axis. It answers "what did
//   this one request pay for". It wears numerals in coloured chips.
//
//   ROADMAP PHASE (0-30 / 30-60 / 60-90 days) is a *calendar* axis. It answers
//   "when do we adopt this repository". It wears a day bracket, in ink only,
//   with no hue of its own — so a phase marker can never be misread as a stage.
//
// Nothing in this file gives phases a stage colour, and nothing gives stages a
// day range. See `phaseTag` and `stageTag`.

/** Create an element. `a` may hold attributes, `class`, `text`, `data`, `on`.
 *  There is deliberately no `html` escape hatch: every string this console
 *  renders comes from the gateway, and a guardrail console that injects
 *  detector output as markup would be its own injection sink. Everything goes
 *  through textContent. */
export function el(tag, a = {}, kids = []) {
  const node = document.createElement(tag);
  return dress(node, a, kids);
}

const SVGNS = 'http://www.w3.org/2000/svg';

/** The same contract for SVG. createElementNS is required — createElement('rect')
 *  makes an unknown HTML element that renders nothing inside an <svg>. Same
 *  rule as `el`: no html escape hatch, text goes through textContent. */
export function svg(tag, a = {}, kids = []) {
  return dress(document.createElementNS(SVGNS, tag), a, kids);
}

function dress(node, a, kids) {
  for (const [k, v] of Object.entries(a)) {
    if (v === null || v === undefined || v === false) continue;
    if (k === 'class') node.setAttribute('class', v);
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

/** Plural without the "1 findings" tell. */
export const plural = (n, one, many = `${one}s`) => `${n} ${n === 1 ? one : many}`;

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
    title: `${counts[c.key]} × ${c.key} (of ${total})`,
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
       cost: 'free', latency: 'sub-millisecond', runs: '100% of requests',
       say: 'Regex, checksums, lexicons. Sub-millisecond, runs on 100% of traffic.' },
  2: { n: '2', name: 'Stage 2', kind: 'local model', cls: '2',
       cost: 'free once installed', latency: 'seconds on CPU', runs: 'borderline only',
       say: 'A locally-run classifier or NLI cross-encoder. Runs only when stage 1 asked for a second look.' },
  3: { n: '3', name: 'Stage 3', kind: 'paid judge', cls: '3',
       cost: 'metered — per call', latency: '1–5 s', runs: 'last resort',
       say: 'A cloud API or an LLM judge. Last resort, and the only stage with a per-call price.' },
  4: { n: '◇', name: 'Offline', kind: 'never in the request path', cls: 'off',
       cost: 'CI budget', latency: 'unbounded', runs: 'never in a request',
       say: 'CI and red-team only. Counting it as runtime protection would be false.' },
};

export const stageMeta = (stage) => STAGES[Number(stage)] ?? {
  n: '?', name: `Stage ${stage}`, kind: 'unknown stage', cls: 'off',
  cost: 'unknown', latency: 'unknown', runs: 'unknown',
  say: 'The gateway reported a stage this console does not know.' };

export function stageTag(stage, { withKind = false } = {}) {
  const m = stageMeta(stage);
  return el('span', { class: `stag stag--${m.cls}`, title: `${m.name} — ${m.say}` }, [
    el('span', { class: 'stag__n', text: m.n, 'aria-hidden': 'true' }),
    el('span', { text: withKind ? `${m.name} · ${m.kind}` : m.name }),
  ]);
}

// -------------------------------------------------------- roadmap phases ---
// A phase is a calendar window, so it is drawn as one: a 90-day track with the
// phase's own slice filled. No stage hue is used here, and no numeral chip —
// the two axes must not be able to trade costumes.

const PHASE_WINDOWS = {
  1: { from: 0, to: 30, label: 'days 0–30' },
  2: { from: 30, to: 60, label: 'days 30–60' },
  3: { from: 60, to: 90, label: 'days 60–90' },
};

export function phaseNumber(name) {
  const m = /phase\s*([123])/i.exec(String(name || ''));
  return m ? Number(m[1]) : null;
}

export const phaseWindow = (n) => PHASE_WINDOWS[n] ?? null;

/** The phase bracket. `n === null` means "not adopted" — no window at all,
 *  drawn as an empty track so it reads as off-calendar rather than as day 0. */
export function phaseTag(name, { withDays = true } = {}) {
  const n = phaseNumber(name);
  const w = phaseWindow(n);
  const track = el('span', { class: 'pbr__track', 'aria-hidden': 'true' },
    w ? el('span', {
      class: 'pbr__fill',
      style: `left:${(w.from / 90) * 100}%;width:${((w.to - w.from) / 90) * 100}%`,
    }) : null);
  return el('span', {
    class: `pbr${n ? '' : ' pbr--none'}`,
    title: n
      ? `Roadmap phase ${n} — ${w.label} of the 90-day adoption plan. A phase is a calendar window, not a cascade stage.`
      : 'Reviewed and not adopted. Outside the 90-day plan.',
  }, [
    el('span', { class: 'pbr__lab', text: n ? `Phase ${n}` : 'Not adopted' }),
    track,
    withDays ? el('span', { class: 'pbr__days', text: w ? w.label : 'no window' }) : null,
  ]);
}

// ------------------------------------------------------- claim strength ----
// A confidence number means nothing without its mechanism. These four are an
// ordering of how soft the claim is, so the scale shows position — never a
// filled bar, which would read as "more is better".

export const KINDS = [
  { key: 'deterministic', word: 'exact',
    gloss: 'exact match or checksum. No model, no score — it either matched or it did not.' },
  { key: 'classifier', word: 'classifier',
    gloss: 'a locally-run trained model’s probability, on that model’s own scale.' },
  { key: 'entailment', word: 'entailment',
    gloss: 'an NLI cross-encoder’s entailment score against a supplied source.' },
  { key: 'judge', word: 'judge',
    gloss: 'a language model’s self-reported score. The softest of the four.' },
];

const KIND_BY_KEY = new Map(KINDS.map((k) => [k.key, k]));
export const kindMeta = (k) => KIND_BY_KEY.get(k) ?? {
  key: k || 'unknown', word: k || 'unknown',
  gloss: 'the gateway did not say what kind of number this is, so it cannot be compared with anything.' };

/** Small chip naming the mechanism class. Used wherever a score appears. */
export function kindChip(kind) {
  const m = kindMeta(kind);
  return el('span', { class: 'conf__k', data: { kind: m.key }, text: m.key, title: m.gloss });
}

/** The claim block: the number, its kind, and the position of that kind on the
 *  softness scale. The scale is a marker, not a fill. */
export function claim(score, kind) {
  const m = kindMeta(kind);
  const deterministic = m.key === 'deterministic';
  const value = deterministic ? 'exact'
    : (score === null || score === undefined) ? 'no score'
      : Number(score).toFixed(2);

  return el('div', { class: 'claim', data: { kind: m.key } }, [
    el('div', { class: 'claim__top' }, [
      el('span', { class: `claim__v${deterministic ? ' claim__v--word' : ''}`, text: value }),
      kindChip(m.key),
    ]),
    el('ol', { class: 'claim__scale', 'aria-hidden': 'true' }, KINDS.map((k) => el('li', {
      class: k.key === m.key ? 'on' : '', data: { k: k.key }, title: k.gloss,
    }, [
      el('i', {}),
      el('span', { text: k.word }),
    ]))),
    el('p', { class: 'claim__gloss', text: m.gloss }),
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

/** A row of hard numbers. `tone` may be 'good' | 'warn' | 'hazard' | null, and
 *  it is always accompanied by the `note` text — never colour alone. */
export function statRow(stats) {
  return el('dl', { class: 'stats' }, stats.filter(Boolean).map((s) => el('div', {
    class: 'stat', data: { tone: s.tone || 'plain' },
  }, [
    el('dt', { text: s.label }),
    el('dd', {}, [
      el('span', { class: 'stat__v', text: String(s.value) }),
      s.unit ? el('span', { class: 'stat__u', text: s.unit }) : null,
    ]),
    s.note ? el('p', { class: 'stat__note', text: s.note }) : null,
  ])));
}

export function table(headers, rows) {
  return el('div', { class: 'tablewrap', tabindex: '0', role: 'region',
    'aria-label': 'Scrollable table' }, [
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

/** Evidence strings are long by design — they name every file and line that was
 *  read. Show the first citation, keep the rest one click away. */
export function evidence(text) {
  const s = String(text || '').trim();
  if (!s) return null;
  const parts = s.split(/;\s*/).filter(Boolean);
  const head = parts[0];
  const box = el('div', { class: 'ev' }, [
    el('span', { class: 'ev__lab', text: 'source read' }),
    el('code', { class: 'ev__cite', text: head }),
  ]);
  if (parts.length > 1) {
    box.append(el('details', { class: 'ev__more' }, [
      el('summary', { text: `${parts.length - 1} more citation${parts.length === 2 ? '' : 's'}` }),
      el('ul', {}, parts.slice(1).map((p) => el('li', {}, el('code', { text: p })))),
    ]));
  }
  return box;
}
