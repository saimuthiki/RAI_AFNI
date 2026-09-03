// Before and after — the guardrails-off versus guardrails-on number.
//
// AFNI asked for a demonstrable attack success rate with the guardrails off and
// on, to show as a demo. This is that, and it is a LADDER rather than a pair,
// because "off versus on" hides the question the build actually turns on: which
// tier is doing the work, and what does it cost per request.
//
// Three things this screen must not let a viewer misread:
//
//   1. THE OFF ARM IS A DEFINITION. With no guardrail there is no decision and
//      every message reaches the model. It is 100% by construction, not a
//      measurement, and it is labelled that way — a bar chart with an
//      unlabelled 100% invites the reading "we measured 100% attack success".
//   2. THIS MEASURES DELIVERY, NOT COMPLIANCE. A prompt that reaches a
//      well-aligned model and gets refused is counted here as delivered. The
//      caveat sits next to the headline, not in a footnote.
//   3. A RUNG WITH A MISSING RAIL IS A FLOOR. On a host without the model
//      weights the Stage-2 rung looks like a measurement and is not one, so it
//      is marked and the missing rails are named.
//
// Rendered as a section of the Corpus screen rather than its own nav item: it
// runs the same corpus under the same server-side cap, and a second tab that
// needed the same explanation of what the corpus is would be a worse demo.

import {
  el, clear, rule, statRow, errorBox, pill, plural,
} from '../ui.js';
import { corpusCompare } from '../api.js';

const pct = (v) => (v == null ? '—' : `${(v * 100).toFixed(1)}%`);
const ms = (v) => (v == null ? '—' : `${Number(v).toFixed(2)} ms`);
const signed = (v) => {
  const n = Number(v ?? 0);
  if (Math.abs(n) < 0.005) return 'no change';
  return `${n > 0 ? '+' : '−'}${Math.abs(n).toFixed(2)} ms`;
};

export function section(sum) {
  const cap = Number(sum.max_sample) || 500;
  const wrap = el('section', { class: 'beforeafter' });

  wrap.append(rule('Before and after', 'the number for a demo'));
  wrap.append(el('p', {
    class: 'mediapara',
    text: 'Run the same records with no guardrail, then with Stage 1, then with '
      + 'Stage 1 and 2. The same records at every rung — re-drawing the sample '
      + 'per rung would make the difference between two rungs partly a sampling '
      + 'artefact, and on a corpus that is 42% content-safety a re-draw can move '
      + 'a rate by several points on its own.',
  }));

  const size = el('input', {
    type: 'number', min: '1', max: String(cap), value: '200',
    class: 'knob__in', id: 'ba-size',
  });
  const stage = el('select', { id: 'ba-stage' }, [
    el('option', { value: '1', text: 'Top rung: Stage 1 — free, sub-millisecond' }),
    el('option', { value: '2', text: 'Top rung: Stage 1 + 2 — adds the local models', selected: true }),
  ]);
  const strat = el('input', { type: 'checkbox', id: 'ba-strat' });
  const pipe = el('input', { type: 'checkbox', id: 'ba-pipe' });
  const run = el('button', { class: 'btn', text: 'Run the comparison' });
  const out = el('div', { class: 'baout' });

  run.addEventListener('click', async () => {
    const n = Math.max(1, Math.min(cap, Number(size.value) || 200));
    const body = { seed: 0, max_stage: Number(stage.value), pipeline: pipe.checked };
    if (strat.checked) body.per_tenet = Math.max(1, Math.round(n / 7));
    else body.limit = n;

    run.disabled = true;
    const was = run.textContent;
    run.textContent = 'Running every rung…';
    clear(out);
    out.append(el('p', {
      class: 'empty',
      text: `Judging ${n} records at each rung. It arrives complete rather than `
        + 'streamed: half a ladder invites comparing a finished rung against an '
        + 'unfinished one, which is a comparison of two sample sizes.',
    }));
    try {
      const data = await corpusCompare(body);
      clear(out);
      out.append(result(data));
    } catch (err) {
      clear(out);
      out.append(errorBox('POST /v1/corpus/compare', err));
    } finally {
      run.textContent = was;
      run.disabled = false;
    }
  });

  wrap.append(el('div', { class: 'bacontrols' }, [
    el('div', { class: 'field' }, [
      el('label', { class: 'eyebrow', for: 'ba-size', text: 'Records per rung' }),
      size,
    ]),
    el('div', { class: 'field' }, [
      el('label', { class: 'eyebrow', for: 'ba-stage', text: 'How far up' }),
      stage,
    ]),
    el('label', { class: 'mediapick__opt' }, [
      strat,
      el('span', {
        text: 'Stratified — an equal share per tenet. Prefer this for a headline '
          + 'number: an unstratified draw mostly measures content safety.',
      }),
    ]),
    el('label', { class: 'mediapick__opt' }, [
      pipe,
      el('span', {
        text: 'Also estimate end-to-end attack success, with no model, by '
          + 'composing the input guardrail against the prompts and the output '
          + 'guardrail against the corpus’s own affirmative completions. Costs '
          + 'a second ladder.',
      }),
    ]),
    run,
  ]));
  wrap.append(out);
  return wrap;
}

// --------------------------------------------------------------------------- //
function result(data) {
  const wrap = el('div', { class: 'bares' });
  const arms = data.arms || [];
  const head = data.headline;

  if (head) {
    wrap.append(el('div', { class: 'verdict verdict--block' }, [
      el('span', { class: 'verdict__word', text: pct(head.off_delivery_rate) }),
      el('span', { class: 'verdict__why', text: head.sentence }),
    ]));
  }

  wrap.append(el('div', { class: 'notebox notebox--stop' }, [
    el('strong', { text: 'What this number is. ' }),
    el('span', { text: data.measures || '' }),
  ]));

  // The ladder, as bars. A bar per rung showing the share that reached the
  // model, so the shrinking is visible without reading three percentages.
  const bars = el('div', { class: 'ladder' });
  for (const arm of arms) {
    const share = arm.delivery_rate == null ? 0 : arm.delivery_rate;
    bars.append(el('div', { class: 'rung' }, [
      el('div', { class: 'rung__head' }, [
        el('strong', { text: arm.arm }),
        arm.arm === 'off'
          ? pill('by definition', 'tag--absent')
          : (arm.measured ? null : pill('floor — rails missing', 'tag--flag')),
        el('span', { class: 'rung__pct', text: pct(arm.delivery_rate) }),
      ]),
      el('div', { class: 'rung__track' }, [
        el('div', {
          class: `rung__fill ${arm.arm === 'off' ? 'rung__fill--off' : ''}`,
          style: `width:${(share * 100).toFixed(1)}%`,
        }),
      ]),
      el('p', { class: 'rung__label', text: arm.label }),
      el('dl', { class: 'rung__nums' }, [
        el('div', {}, [el('dt', { text: 'reached the model' }),
          el('dd', { text: `${arm.delivered_to_model} of ${arm.sample}` })]),
        el('div', {}, [el('dt', { text: 'stopped' }),
          el('dd', { text: String(arm.stopped) })]),
        el('div', {}, [el('dt', { text: 'rails' }),
          el('dd', { text: String(arm.rails) })]),
        el('div', {}, [el('dt', { text: 'median' }),
          el('dd', { text: ms(arm.median_ms_per_record) })]),
        el('div', {}, [el('dt', { text: 'p95' }),
          el('dd', { text: ms(arm.p95_ms_per_record) })]),
      ]),
      stoppedBy(arm),
    ]));
  }
  wrap.append(bars);

  wrap.append(el('p', {
    class: 'micro',
    text: 'Median and p95, not the mean. The mean is what a single record’s '
      + 'lazy model load distorts — one four-second load across eighty records '
      + 'reads as 44 ms each — and the p95 is the tail an SLO has to survive.',
  }));

  // ---- what each rung buys ----------------------------------------------
  if ((data.deltas || []).length) {
    wrap.append(el('h4', { class: 'mediares__h', text: 'What each rung buys' }));
    const list = el('ul', { class: 'findlist' });
    for (const d of data.deltas) {
      list.append(el('li', {}, [
        el('code', { text: `${d.from} → ${d.to}` }),
        el('span', {
          class: 'findlist__score',
          text: `+${d.extra_stopped} stopped (${pct(d.extra_stop_rate)})`,
        }),
        el('span', {
          class: 'findlist__det',
          // signed(), not a hardcoded "+": a rung can be FASTER at the median
          // than the one below it (Stage 1 short-circuits more records once its
          // rails run first), and "+-0.05 ms" is not a number anyone reads.
          text: `${signed(d.extra_median_ms)} at the median`,
        }),
      ]));
    }
    wrap.append(list);
    wrap.append(el('p', {
      class: 'micro',
      text: 'This is the number the cascade’s ordering lives or dies by. If a '
        + 'rung adds nothing over the one below it on this corpus, those rails '
        + 'are not earning their latency — and it would say so here.',
    }));
  }

  if (data.pipeline) wrap.append(pipeline(data.pipeline));

  for (const note of data.notes || []) {
    wrap.append(el('div', { class: 'notebox' }, [
      el('strong', { text: 'Note. ' }), el('span', { text: note }),
    ]));
  }
  return wrap;
}

function stoppedBy(arm) {
  const entries = Object.entries(arm.stopped_by || {});
  if (!entries.length) return el('p', { class: 'micro', text: 'Nothing stopped.' });
  entries.sort((a, b) => b[1] - a[1]);
  return el('ul', { class: 'rung__by' }, entries.slice(0, 6).map(([rail, n]) => el('li', {}, [
    el('code', { text: rail }),
    el('span', { class: 'findlist__score', text: String(n) }),
  ])));
}

function pipeline(p) {
  if (!p.available) {
    return el('div', { class: 'notebox' }, [
      el('strong', { text: 'End-to-end estimate unavailable. ' }),
      el('span', { text: p.why || '' }),
    ]);
  }
  const wrap = el('div', { class: 'pipeline' });
  wrap.append(el('h4', { class: 'mediares__h', text: 'End to end, without a model' }));
  wrap.append(el('p', {
    class: 'mediapara',
    text: 'The corpus carries both halves of an attack: the prompt, and — for '
      + 'the output-direction records — the affirmative completion a jailbroken '
      + 'model would have produced. So both guardrails can be measured against '
      + 'their own real input and composed: an attack succeeds only if the '
      + 'prompt gets past the input guardrail AND the harmful answer gets past '
      + 'the output guardrail.',
  }));
  wrap.append(statRow([
    { label: 'Prompt gets through', value: pct(p.prompt_gets_through),
      note: `${p.input_sample} input-direction records` },
    { label: 'Harmful answer gets through', value: pct(p.harmful_answer_gets_through),
      note: `${p.output_sample} affirmative completions` },
    { label: 'End to end', value: pct(p.end_to_end_success_rate),
      tone: 'warn', note: 'the product of the two' },
    { label: 'With no guardrail', value: pct(p.off_success_rate),
      note: 'by definition — both halves are delivered' },
  ]));
  wrap.append(el('div', { class: 'notebox notebox--stop' }, [
    el('strong', { text: 'It assumes two things. Read them before quoting it. ' }),
    el('ul', {}, (p.assumes || []).map((a) => el('li', { text: a }))),
  ]));
  return wrap;
}
