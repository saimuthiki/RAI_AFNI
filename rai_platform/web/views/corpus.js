// Corpus — run a configurable slice of the 11,369-record regression corpus and
// watch the guardrail decide, record by record.
//
// The sample size is the control this page is built around, not a setting hidden
// in an advanced panel. The corpus is 11,369 records; a Stage-2 pass costs about
// three seconds each. "Run the corpus" is nine hours. So the size box is the
// first thing on the page, it is bounded by the server's own cap, and it shows
// the projected runtime BEFORE you press Run — because the failure mode here is
// not a wrong answer, it is an operator who starts a forty-minute job by
// accident and reloads the tab three minutes in.
//
// The estimate starts from two measurements taken on this project (Stage 1 at
// 0.8 ms/record over 280 records; a warm Stage-2 request at 2,954 ms) and then
// REPLACES them with the ms/record the last real run on this host reported. An
// estimate that never learns from the machine it is running on is decoration.

import {
  el, clear, frag, pageHead, rule, field, statRow, table, errorBox, empty,
  pill, plural,
} from '../ui.js';
import { corpusSummary, corpusRunStream, state } from '../api.js';

// Measured on this project, not guessed — see the header. Superseded per stage
// by the real ms/record as soon as a run on this host reports one.
const SEED_MS = { 1: 0.8, 2: 3000, 3: 3000 };
const observed = new Map();

const msFor = (stage) => observed.get(stage) ?? SEED_MS[stage] ?? 1000;

function humanMs(ms) {
  if (ms < 1000) return `${ms < 10 ? ms.toFixed(1) : Math.round(ms)} ms`;
  if (ms < 90_000) return `${(ms / 1000).toFixed(1)} s`;
  if (ms < 5_400_000) return `${Math.round(ms / 60_000)} min`;
  return `${(ms / 3_600_000).toFixed(1)} h`;
}

const DECISION_TONE = { block: 'good', allow: 'hazard', flag: 'warn', error: 'hazard' };

function decisionChip(decision) {
  const d = String(decision || '').toLowerCase();
  return el('span', { class: `dchip dchip--${d || 'unknown'}`, text: d || '—' });
}

// A block on this corpus is a GOOD outcome and an allow is a bad one — every
// record in it is a prompt we would rather the model never answered. That is the
// inverse of the live view, where a block is the alarming colour, so the polarity
// is stated in the legend rather than left to the reader to infer from hue.
function agreeChip(row) {
  if (row.agrees === null || row.agrees === undefined) {
    return el('span', { class: 'dchip dchip--none', title:
      'No comparable baseline: either this record has never been recorded, or its '
      + 'baseline was taken on a different tier. Not the same as agreement.',
    text: 'no baseline' });
  }
  return row.agrees
    ? el('span', { class: 'dchip dchip--same', text: 'matches' })
    : el('span', { class: 'dchip dchip--drift', title:
        `baseline said ${row.expected_decision} (tier ${row.expected_tier || '?'})`,
      text: `drift · was ${row.expected_decision}` });
}

export async function render(root) {
  clear(root);
  root.append(pageHead(
    'Corpus',
    'Regression corpus',
    '11,369 adversarial prompts, tagged by tenet and by OWASP LLM Top 10, with a '
    + 'recorded baseline. Pick a sample size, pick how far up the cascade to run it, '
    + 'and watch every record get judged. The corpus is the asset — it is what turns '
    + '“the guardrail works” into a number you can re-measure after every change.',
  ));

  if (state.source === 'fixtures') {
    root.append(el('div', { class: 'errorbox', role: 'alert' }, [
      el('strong', { text: 'The gateway is not answering, so there is nothing to run. ' }),
      el('span', { text:
        'This page has no fixture mode on purpose: a replayed pass rate is not a '
        + 'measurement, and a corpus run that did not happen must not be able to '
        + 'produce a number that looks like one. Start the gateway and press Retry '
        + 'in the top bar.' }),
    ]));
    return;
  }

  const loading = el('p', { class: 'empty', text: 'Reading /v1/corpus…' });
  root.append(loading);

  let sum;
  try { sum = await corpusSummary(); } catch (err) {
    loading.replaceWith(errorBox('Loading the corpus index', err)); return;
  }
  loading.remove();

  const cap = Number(sum.max_sample) || 500;
  const outputs = (sum.directions || []).find((d) => d.direction === 'output');

  root.append(statRow([
    { label: 'Records', value: sum.records.toLocaleString(),
      note: 'built from harmdataset.xlsx, deduplicated, normalised and labelled' },
    { label: 'With a baseline', value: sum.baselined.toLocaleString(),
      tone: sum.baselined ? 'good' : 'warn',
      note: sum.baselined
        ? 'only these can drift — the rest have never been recorded'
        : 'nothing recorded yet, so nothing can drift; run baseline.py --write' },
    { label: 'Run cap', value: cap.toLocaleString(), unit: 'per run',
      note: 'server-side (AFNI_CORPUS_MAX_SAMPLE) — a bigger pass belongs offline' },
    { label: 'Output-direction', value: (outputs ? outputs.records : 0).toLocaleString(),
      note: 'affirmative completions — what a jailbroken model would have said' },
    // Deliberately NOT "allowed"/"blocked". Those two words already mean a
    // verdict everywhere else in this console, and a stat reading "paid judge:
    // blocked" invites the reader to think a prompt was blocked by it.
    { label: 'Stage 3 on this host', value: sum.cloud_allowed ? 'enabled' : 'off',
      tone: sum.cloud_allowed ? 'warn' : 'good',
      note: sum.cloud_allowed
        ? 'AFNI_CORPUS_ALLOW_CLOUD is set — Stage 3 will send prompts to a third party'
        : 'these are real harmful prompts; Stage 3 would ship them to a vendor' },
  ]));

  // ------------------------------------------------------------- controls ----
  root.append(rule('Choose a sample', `cap ${cap.toLocaleString()} records per run`));

  const modeSel = el('select', {}, [
    el('option', { value: 'flat', text: 'N records, drawn across the whole corpus' }),
    el('option', { value: 'tenet', text: 'N per tenet — stratified' }),
    el('option', { value: 'range', text: 'Records N to M — exact positions' }),
  ]);

  // The positional range. 1-based and INCLUSIVE, matching how a person counts:
  // 10 to 20 is eleven records. Deliberately separate controls from the size
  // slider, because a range is a different intent - it asks for SPECIFIC
  // records rather than a representative handful, and it ignores the seed.
  // `sum.records` is the corpus size. NOT `total` - that is declared inside the
  // run function and is the size of the current run, so using it here was a
  // temporal-dead-zone ReferenceError before the first run.
  const corpusSize = Number(sum.records) || 0;
  const startNum = el('input', { type: 'number', min: '1', max: String(corpusSize),
    value: '1', class: 'sizer__num' });
  const endNum = el('input', { type: 'number', min: '1', max: String(corpusSize),
    value: String(Math.min(20, corpusSize)), class: 'sizer__num' });
  const rangeRow = el('div', { class: 'rangerow', hidden: true }, [
    el('label', { class: 'eyebrow', text: 'From record' }), startNum,
    el('label', { class: 'eyebrow', text: 'to' }), endNum,
    el('span', { class: 'micro mute', id: 'rangecount' }),
  ]);
  const rangeCount = rangeRow.querySelector('#rangecount');

  function rangeSize() {
    const a = Math.max(1, Number(startNum.value) || 1);
    const b = Math.max(a, Number(endNum.value) || a);
    return b - a + 1;   // inclusive
  }
  const sizeRange = el('input', { type: 'range', min: '1', max: String(cap),
    value: String(Math.min(50, cap)), class: 'sizer__range' });
  const sizeNum = el('input', { type: 'number', min: '1', max: String(cap),
    value: String(Math.min(50, cap)), class: 'sizer__num' });

  const stageSel = el('select', {}, [
    el('option', { value: '1', text: 'Stage 1 only — free, deterministic' }),
    el('option', { value: '2', text: 'Stage 1 + 2 — adds the local models' }),
    el('option', { value: '3', text: 'Stage 1 + 2 + 3 — adds the paid judge',
      disabled: !sum.cloud_allowed }),
  ]);
  stageSel.value = '1';

  const tenetSel = el('select', {}, [
    el('option', { value: '', text: `All tenets — ${sum.records.toLocaleString()}` }),
    ...(sum.tenets || []).map((t) => el('option', { value: t.tenet,
      text: `${t.tenet} — ${t.records.toLocaleString()}` })),
  ]);
  const owaspSel = el('select', {}, [
    el('option', { value: '', text: 'All OWASP categories' }),
    ...(sum.owasp || []).map((o) => el('option', { value: o.code,
      text: `${o.code} — ${o.records.toLocaleString()}` })),
  ]);
  const dirSel = el('select', {}, [
    el('option', { value: '', text: 'Both directions' }),
    ...(sum.directions || []).map((d) => el('option', { value: d.direction,
      text: `${d.direction} — ${d.records.toLocaleString()}` })),
  ]);
  const seedSel = el('select', {}, [
    el('option', { value: '0', text: 'Deterministic (seed 0) — comparable run to run' }),
    el('option', { value: '-1', text: 'Random — for exploring, not for regression' }),
  ]);

  const runBtn = el('button', { class: 'btn', text: 'Run sample' });
  const stopBtn = el('button', { class: 'btn btn--quiet', text: 'Stop', disabled: true });
  const projection = el('p', { class: 'sizer__eta' });

  // Keep slider and number box in step, both clamped to the server's cap. The
  // clamp is here as well as server-side so nobody composes a selection the
  // gateway will refuse only after they commit to it.
  const clampSize = (raw) => Math.min(Math.max(parseInt(raw, 10) || 1, 1), cap);
  function setSize(raw) {
    const v = clampSize(raw);
    sizeRange.value = String(v);
    sizeNum.value = String(v);
    paintProjection();
  }
  sizeRange.addEventListener('input', () => setSize(sizeRange.value));
  sizeNum.addEventListener('change', () => setSize(sizeNum.value));
  stageSel.addEventListener('change', paintProjection);
  modeSel.addEventListener('change', () => { paintMode(); paintProjection(); });
  tenetSel.addEventListener('change', paintProjection);
  startNum.addEventListener('input', paintRange);
  endNum.addEventListener('input', paintRange);

  function tenetBuckets() {
    const chosen = tenetSel.value;
    if (chosen) return 1;
    return (sum.tenets || []).length || 1;
  }

  function plannedSize() {
    if (modeSel.value === 'range') return rangeSize();
    const n = clampSize(sizeNum.value);
    return modeSel.value === 'tenet' ? n * tenetBuckets() : n;
  }

  function paintMode() {
    const ranged = modeSel.value === 'range';
    // The slider and the range boxes are the same decision expressed two ways,
    // so exactly one of them is on screen. Showing both invites someone to set
    // a size AND a range and wonder which won.
    sizer.hidden = ranged;
    rangeRow.hidden = !ranged;
    drawField.hidden = ranged;
    if (ranged) { paintRange(); return; }
    const stratified = modeSel.value === 'tenet';
    // Per-tenet multiplies, so the same number means a much larger run. Cap the
    // per-bucket box accordingly rather than letting the server reject it.
    const perCap = stratified ? Math.max(1, Math.floor(cap / tenetBuckets())) : cap;
    sizeRange.max = String(perCap);
    sizeNum.max = String(perCap);
    if (clampSize(sizeNum.value) > perCap) setSize(perCap);
    sizeLabel.textContent = stratified ? 'Records per tenet' : 'Records';
  }

  function paintRange() {
    const n = rangeSize();
    const over = n > cap;
    clear(rangeCount).append(frag([
      el('strong', { class: over ? 'eta--warn' : null, text: plural(n, 'record') }),
      el('span', { text: ' — the range is inclusive, so ' }),
      el('span', { class: 't-mono', text:
        `${Math.max(1, Number(startNum.value) || 1)} to `
        + `${Math.max(1, Number(endNum.value) || 1)}` }),
      el('span', { text: ` is ${n}, not ${Math.max(0, n - 1)}.` }),
      over ? el('span', { class: 'eta--warn', text:
        ` One run is capped at ${cap.toLocaleString()} — narrow the range or use `
        + 'corpus/baseline.py offline.' }) : null,
    ]));
    runBtn.disabled = over;
    paintProjection();
  }

  function paintProjection() {
    const stage = Number(stageSel.value);
    const n = plannedSize();
    const per = msFor(stage);
    const learnt = observed.has(stage);
    // frag() drops the nulls; DOM append() would stringify one into the literal
    // word "null" in the middle of the sentence.
    clear(projection).append(frag([
      el('strong', { text: plural(n, 'record') }),
      el('span', { text: ` at Stage ${stage} ≈ ` }),
      el('strong', { class: n * per > 120_000 ? 'eta--long' : null, text: humanMs(n * per) }),
      el('span', { class: 'mute', text:
        ` · ${per < 10 ? per.toFixed(1) : Math.round(per).toLocaleString()} ms per record, `
        + (learnt ? 'measured on this host by the last run'
          : 'measured on this project — will be replaced by this host’s own number '
            + 'after one run') }),
      n * per > 600_000
        ? el('span', { class: 'eta--warn', text:
          ' — that is over ten minutes of held-open request. Consider Stage 1, a '
          + 'smaller sample, or corpus/baseline.py offline.' })
        : null,
    ]));
  }

  const sizeLabel = el('label', { class: 'eyebrow', text: 'Records' });
  const sizer = el('div', { class: 'sizer' }, [
    el('div', { class: 'sizer__head' }, [sizeLabel, projection]),
    el('div', { class: 'sizer__row' }, [sizeRange, sizeNum]),
  ]);

  // Held in a variable so range mode can hide it: a range ignores the seed, and
  // leaving the Draw control on screen tells the reader it does not.
  const drawField = field('Draw', seedSel);

  root.append(el('div', { class: 'panel' }, [
    sizer,
    rangeRow,
    el('div', { class: 'filters filters--corpus' }, [
      field('Sampling', modeSel),
      field('Cascade ceiling', stageSel),
      field('Tenet', tenetSel),
      field('OWASP category', owaspSel),
      field('Direction', dirSel),
      drawField,
    ]),
    el('div', { class: 'panel__actions' }, [
      runBtn, stopBtn,
      el('span', { class: 'micro mute', text:
        'Every prompt is shown truncated to 120 characters. Cite the record id, not '
        + 'the text — see corpus/WARNING.md.' }),
    ]),
  ]));

  paintMode();
  paintProjection();

  // -------------------------------------------------------------- results ----
  const progress = el('div', { class: 'runbar', hidden: true });
  const tally = el('dl', { class: 'stats stats--tight', hidden: true });
  const finding = el('div', { hidden: true });
  const results = el('div');
  root.append(progress, tally, finding, results);

  let ctl = null;

  runBtn.addEventListener('click', async () => {
    if (ctl) return;
    ctl = new AbortController();
    runBtn.disabled = true;
    stopBtn.disabled = false;
    clear(results);
    clear(finding);
    finding.hidden = true;

    const stage = Number(stageSel.value);
    const n = clampSize(sizeNum.value);
    const ranged = modeSel.value === 'range';
    const request = {
      max_stage: stage,
      // A range is not sampled, so no seed is sent: the server ignores it for a
      // range, and sending one would suggest it changed which records ran.
      ...(ranged ? {} : { seed: Number(seedSel.value) }),
      ...(ranged
        ? { start: Math.max(1, Number(startNum.value) || 1),
            end: Math.max(1, Number(endNum.value) || 1) }
        : modeSel.value === 'tenet' ? { per_tenet: n } : { limit: n }),
      ...(tenetSel.value ? { tenet: tenetSel.value } : {}),
      ...(owaspSel.value ? { owasp: owaspSel.value } : {}),
      ...(dirSel.value ? { direction: dirSel.value } : {}),
    };

    const rows = [];
    const counts = new Map();
    let total = 0;
    let started = performance.now();
    let stats = null;

    const bar = el('div', { class: 'runbar__fill' });
    const barText = el('p', { class: 'runbar__text', text: 'starting…' });
    clear(progress).append(el('div', { class: 'runbar__track' }, bar), barText);
    progress.hidden = false;
    tally.hidden = false;

    function paintTally() {
      const done = rows.length;
      const drift = rows.filter((r) => r.agrees === false).length;
      const compared = rows.filter((r) => r.agrees !== null && r.agrees !== undefined).length;
      const blocked = counts.get('block') || 0;
      clear(tally).append(...[
        { label: 'Judged', value: `${done.toLocaleString()}${total ? ` / ${total.toLocaleString()}` : ''}` },
        { label: 'Blocked', value: blocked.toLocaleString(), tone: 'good',
          note: done ? `${((blocked / done) * 100).toFixed(1)}% of what has run` : null },
        { label: 'Allowed', value: (counts.get('allow') || 0).toLocaleString(),
          tone: (counts.get('allow') || 0) > blocked ? 'hazard' : 'plain',
          note: 'on this corpus an allow is a miss, not a pass' },
        { label: 'Flagged', value: (counts.get('flag') || 0).toLocaleString(), tone: 'warn' },
        { label: 'Drift', value: compared ? `${drift} / ${compared}` : '—',
          tone: drift ? 'hazard' : 'good',
          note: compared ? 'against the recorded baseline, same tier only'
            : 'nothing comparable in this sample' },
        { label: 'Errors', value: (counts.get('error') || 0).toLocaleString(),
          tone: (counts.get('error') || 0) ? 'hazard' : 'plain',
          note: 'the cascade raised — a broken check, not a caught prompt' },
      ].map((s) => statRow([s]).firstChild));
    }

    const onEvent = (kind, obj) => {
      if (kind === 'start') {
        total = Number(obj.total) || 0;
        started = performance.now();
        barText.textContent = `${total.toLocaleString()} records · ${obj.selection} · tier ${obj.tier}`;
        if (obj.note) {
          finding.hidden = false;
          clear(finding).append(el('div', { class: 'notebox' }, [
            el('strong', { text: 'The request was modified. ' }),
            el('span', { text: String(obj.note) }),
          ]));
        }
        paintTally();
      } else if (kind === 'row') {
        const row = obj.row;
        rows.push(row);
        counts.set(row.decision, (counts.get(row.decision) || 0) + 1);
        const pct = total ? (rows.length / total) * 100 : 0;
        bar.style.width = `${pct.toFixed(1)}%`;
        const perMs = (performance.now() - started) / rows.length;
        const left = total > rows.length ? (total - rows.length) * perMs : 0;
        barText.textContent =
          `${rows.length.toLocaleString()} / ${total.toLocaleString()}`
          + ` · ${humanMs(perMs)} per record`
          + (left ? ` · about ${humanMs(left)} left` : ' · done');
        if (rows.length % 10 === 0 || rows.length === total) paintTally();
      } else if (kind === 'summary') {
        stats = obj.stats;
      } else if (kind === 'error') {
        barText.textContent = `stream error: ${obj.error}`;
      }
    };

    try {
      await corpusRunStream(request, onEvent, { signal: ctl.signal });
    } catch (err) {
      if (err.name !== 'AbortError') {
        results.append(errorBox('The corpus run', err));
        progress.hidden = true;
      }
    } finally {
      const aborted = ctl.signal.aborted;
      ctl = null;
      runBtn.disabled = false;
      stopBtn.disabled = true;
      paintTally();
      if (stats && stats.ms_per_record) {
        observed.set(stage, stats.ms_per_record);
        paintProjection();
      }
      if (rows.length) {
        if (aborted) barText.textContent += ' · stopped early';
        renderFinding(finding, rows, stats, stage, aborted);
        renderRows(results, rows, stats);
      } else if (!aborted) {
        results.append(empty('The run produced no rows.'));
      }
    }
  });

  stopBtn.addEventListener('click', () => { if (ctl) ctl.abort(); });
}

// --------------------------------------------------------------------------- //
// What the run means                                                          //
// --------------------------------------------------------------------------- //
// Computed from the rows in front of us, never asserted in advance. The
// headline this corpus produced on its first run — 279 of 280 harmful prompts
// allowed at Stage 1 — is a finding about what pattern matching can and cannot
// see, and it is only worth stating when the numbers on screen say it.

function renderFinding(host, rows, stats, stage, aborted) {
  const done = rows.length;
  const allowed = rows.filter((r) => r.decision === 'allow').length;
  const blocked = rows.filter((r) => r.decision === 'block').length;
  const drift = rows.filter((r) => r.agrees === false).length;
  const rate = allowed / done;

  const kids = [];

  if (rate > 0.8) {
    kids.push(el('div', { class: 'notebox notebox--hazard' }, [
      el('strong', { text:
        `${allowed.toLocaleString()} of ${done.toLocaleString()} harmful prompts were ALLOWED.` }),
      el('p', { text:
        stage === 1
          ? 'This is the expected — and important — result at Stage 1. Stage 1 matches '
            + 'patterns: PII shapes, credential formats, injection phrasings, a profanity '
            + 'lexicon. Harmful intent written in ordinary English has no pattern to '
            + 'match, so the entire free tier is blind to it. Do not present Stage 1 as '
            + 'harm protection; it is data-loss and attack-pattern protection.'
          : 'At this ceiling that is a real gap, not a property of the tier. Read the '
            + 'allowed rows below and check which rails were even eligible — a rail that '
            + 'cannot load on this host still runs and still returns “could not judge”.' }),
      el('p', { class: 'mute', text:
        'Re-run the same sample at a higher ceiling to see what the paid tier buys. The '
        + 'seed is fixed, so the two runs are directly comparable.' }),
    ]));
  } else if (blocked / done > 0.5) {
    kids.push(el('div', { class: 'notebox notebox--good' }, [
      el('strong', { text:
        `${blocked.toLocaleString()} of ${done.toLocaleString()} were blocked.` }),
      el('p', { text:
        'Read the “blocked by” breakdown before celebrating: a single lexical rail '
        + 'accounting for most of the blocks means this sample is measuring one rail, '
        + 'not the cascade.' }),
    ]));
  }

  if (drift) {
    kids.push(el('div', { class: 'notebox notebox--warn' }, [
      el('strong', { text: `${plural(drift, 'record')} changed verdict since the baseline.` }),
      el('p', { text:
        'A changed verdict is not automatically a regression. Read them, decide whether '
        + 'the new behaviour is correct, and only then re-record the baseline with '
        + 'corpus/baseline.py --write. A tool that updates its own expectations cannot '
        + 'detect anything.' }),
      stats && stats.drifted_ids && stats.drifted_ids.length
        ? el('code', { class: 'ev__cite', text: stats.drifted_ids.join('  ') }) : null,
    ]));
  }

  if (stats && stats.unjudged) {
    kids.push(el('div', { class: 'notebox notebox--warn' }, [
      el('strong', { text: `${plural(stats.unjudged, 'record')} came back unjudged.` }),
      el('p', { text:
        'A rail was asked and could not answer — usually missing model weights. That '
        + 'fails closed, which is safe, but it protects nothing: the record was not '
        + 'actually inspected.' }),
    ]));
  }

  if (aborted) {
    kids.push(el('div', { class: 'notebox notebox--warn' }, [
      el('strong', { text: 'Stopped early. ' }),
      el('span', { text:
        'These numbers describe the records that ran, not the sample you selected, so '
        + 'they are not comparable to a completed run of the same size.' }),
    ]));
  }

  if (!kids.length) return;
  host.hidden = false;
  clear(host).append(...kids);
}

// --------------------------------------------------------------------------- //
// The rows                                                                    //
// --------------------------------------------------------------------------- //

function renderRows(host, rows, stats) {
  clear(host);

  const blockedBy = (stats && stats.blocked_by) || {};
  const byRail = Object.entries(blockedBy).sort((a, b) => b[1] - a[1]);

  host.append(rule('What ran', stats
    ? `${stats.sample.toLocaleString()} records · ${stats.selection} · `
      + `${humanMs(stats.elapsed_ms)} · ${stats.ms_per_record} ms each`
    : `${rows.length.toLocaleString()} records`));

  if (byRail.length) {
    host.append(el('div', { class: 'byrail' }, byRail.map(([railName, n]) => el(
      'span', { class: 'byrail__item' }, [
        el('code', { text: railName }),
        el('span', { class: 'byrail__n', text: String(n) }),
      ]))));
  } else {
    host.append(el('p', { class: 'empty', text:
      'Nothing blocked anything in this sample. That is a result, not an empty state.' }));
  }

  // Filters over the result set. "Allowed" is first because on this corpus the
  // allowed rows are the interesting ones — they are the misses.
  const FILTERS = [
    ['allowed', 'Allowed (misses)', (r) => r.decision === 'allow'],
    ['blocked', 'Blocked', (r) => r.decision === 'block'],
    ['flagged', 'Flagged', (r) => r.decision === 'flag'],
    ['drift', 'Drift', (r) => r.agrees === false],
    ['unjudged', 'Unjudged', (r) => r.unjudged],
    ['errors', 'Errors', (r) => r.decision === 'error'],
    ['all', 'Everything', () => true],
  ];
  const active = new Set(['allowed']);
  const chips = el('div', { class: 'chipset' });
  const body = el('div');
  const count = el('p', { class: 'micro mute' });

  function paint() {
    const preds = FILTERS.filter(([k]) => active.has(k)).map(([, , f]) => f);
    const shown = preds.length
      ? rows.filter((r) => preds.some((f) => f(r)))
      : rows;
    count.textContent = `${shown.length.toLocaleString()} of ${rows.length.toLocaleString()} rows`;
    clear(body).append(shown.length
      ? table(
        [{ label: 'Record', width: '13rem' }, 'Prompt (truncated)',
          { label: 'Tenet', width: '11rem' }, { label: 'OWASP', width: '6rem' },
          { label: 'Decision', width: '6rem' }, { label: 'Caught by', width: '12rem' },
          { label: 'Baseline', width: '11rem' }],
        shown.map((r) => el('tr', { data: { tone: DECISION_TONE[r.decision] || 'plain' } }, [
          el('td', {}, el('code', { class: 'rid', text: r.id.replace(/^afni-corpus-/, '') })),
          el('td', {}, [
            el('span', { text: r.prompt }),
            r.direction === 'output'
              ? pill('output', 'tag--combine') : null,
          ]),
          el('td', { text: r.tenet || '—' }),
          el('td', {}, (r.owasp || []).length
            ? frag(r.owasp.map((c) => pill(c))) : document.createTextNode('—')),
          el('td', {}, decisionChip(r.decision)),
          el('td', {}, r.blocking_rail
            ? el('div', {}, [
              el('code', { text: r.blocking_rail }),
              r.blocking_category
                ? el('p', { class: 'micro mute', text: r.blocking_category }) : null,
            ])
            : r.error
              ? el('code', { class: 'err', text: r.error })
              : document.createTextNode('—')),
          el('td', {}, agreeChip(r)),
        ])))
      : empty('No rows match those filters.'));
  }

  for (const [key, label, pred] of FILTERS) {
    const n = rows.filter(pred).length;
    const btn = el('button', {
      class: 'chip', 'aria-pressed': String(active.has(key)),
      text: `${label} · ${n.toLocaleString()}`,
    });
    btn.addEventListener('click', () => {
      if (key === 'all') { active.clear(); active.add('all'); }
      else {
        active.delete('all');
        if (active.has(key)) active.delete(key); else active.add(key);
        if (!active.size) active.add('all');
      }
      chips.querySelectorAll('.chip').forEach((b, i) => b.setAttribute(
        'aria-pressed', String(active.has(FILTERS[i][0]))));
      paint();
    });
    chips.append(btn);
  }

  host.append(chips, count, body);
  paint();
}
