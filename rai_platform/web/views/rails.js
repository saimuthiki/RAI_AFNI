// Rails — all 32 detectors, one row each, with the line of source that was read.
//
// The tenets view answers "is this tenet covered". This one answers the question
// an engineer actually asks next: "what exactly is looking at my traffic, what
// mechanism does it use, where did it come from, and can it run right now."
//
// The `available` flag on /v1/rails is null for every rail — the gateway does not
// put it there. The truth is in /healthz's `rails_unavailable`, and api.js joins
// the two. Without that join this page would show 32 healthy rails on a host
// that can only run 25, which is the exact misreading the platform exists to
// prevent.

import {
  el, clear, pageHead, field, stageTag, kindChip, evidence,
  errorBox, empty, statRow, STAGES, KINDS,
} from '../ui.js';
import { railsWithHealth } from '../api.js';

export async function render(root) {
  clear(root);
  root.append(pageHead(
    'Rails',
    'Every detector, its mechanism, and the line it was ported from',
    'A rail declares its cascade stage; it does not get to invent one. Each row names '
    + 'the repository the pattern was read out of and the file:line that was actually '
    + 'opened — which is the difference between “llm-guard detects invisible text” and '
    + 'knowing which Unicode ranges it strips.',
  ));

  const loading = el('p', { class: 'empty', text: 'Reading /v1/rails…' });
  root.append(loading);

  let inv;
  try { inv = await railsWithHealth(); } catch (err) {
    loading.replaceWith(errorBox('Loading the rail index', err)); return;
  }
  loading.remove();

  const all = inv.rails.slice().sort((a, b) => a.stage - b.stage || a.name.localeCompare(b.name));
  const tenets = [...new Set(all.map((r) => r.tenet))].sort();

  root.append(statRow([
    { label: 'Rails mounted', value: String(all.length),
      note: [1, 2, 3].map((s) => `${(inv.byStage.get(s) || []).length} at stage ${s}`).join(' · ') },
    { label: 'Deterministic', value: String(all.filter((r) => r.confidence_kind === 'deterministic').length),
      tone: 'good',
      note: 'no model, no score, no per-call price — this is the tier that carries the traffic' },
    { label: 'Model-backed', value: String(all.filter((r) => ['classifier', 'entailment'].includes(r.confidence_kind)).length),
      note: 'a local classifier or NLI cross-encoder, run only when asked for' },
    { label: 'Judge-backed', value: String(all.filter((r) => r.confidence_kind === 'judge').length),
      tone: 'warn', note: 'the only rails with a per-call price' },
    { label: 'Cannot run here', value: String(inv.deadCount),
      tone: inv.deadCount ? 'hazard' : 'good',
      note: inv.deadCount
        ? 'mounted and invoked, returning “could not judge” — read the reason on each row'
        : 'every rail on this host can judge' },
  ]));

  // ------------------------------------------------------------- filters ----
  const stageSel = el('select', {}, [
    el('option', { value: '', text: 'All stages' }),
    ...[1, 2, 3, 4].filter((s) => (inv.byStage.get(s) || []).length)
      .map((s) => el('option', { value: String(s), text: `${STAGES[s].name} — ${STAGES[s].kind}` })),
  ]);
  const tenetSel = el('select', {}, [
    el('option', { value: '', text: 'All tenets' }),
    ...tenets.map((t) => el('option', { value: t, text: t })),
  ]);
  const kindSel = el('select', {}, [
    el('option', { value: '', text: 'All mechanisms' }),
    ...KINDS.filter((k) => all.some((r) => r.confidence_kind === k.key))
      .map((k) => el('option', { value: k.key, text: k.key })),
  ]);
  const deadOnly = el('input', { type: 'checkbox' });
  const q = el('input', { type: 'text', placeholder: 'rail, repo, mechanism…' });

  const list = el('div');
  const count = el('p', { class: 'micro mute', style: 'margin-top:var(--sp-3)' });

  const filters = el('div', { class: 'filters', style: 'margin-top:var(--sp-5)' }, [
    field('Search', q),
    field('Cascade stage', stageSel),
    field('Tenet', tenetSel),
    field('Mechanism', kindSel),
    el('div', { class: 'field' }, [
      el('span', { class: 'eyebrow', text: 'Health' }),
      el('label', { class: 'switch' }, [
        deadOnly,
        el('span', { class: 'switch__track', 'aria-hidden': 'true' }),
        el('span', { class: 'switch__text' }, [
          el('b', { text: 'Cannot run only' }),
          el('span', { text: 'the rails that report “could not judge”' }),
        ]),
      ]),
    ]),
  ]);

  [q, stageSel, tenetSel, kindSel, deadOnly].forEach((c) =>
    c.addEventListener(c === q ? 'input' : 'change', draw));

  root.append(filters, list, count);
  draw();

  root.append(el('section', { class: 'card card__pad', style: 'margin-top:var(--sp-5)' }, [
    el('p', { class: 'eyebrow', text: 'What the mechanism column means' }),
    el('dl', { class: 'attr', style: 'margin-top:var(--sp-3)' }, KINDS.map((k) => el('div', {}, [
      el('dt', { text: k.key }),
      el('dd', { class: 'micro mute', text: k.gloss }),
    ]))),
    el('p', { class: 'small mute', style: 'margin-top:var(--sp-3);max-width:80ch', text:
      'Thresholds are keyed per mechanism, not per tenet, for the same reason: '
      + 'safety.toxicity.classifier defaults to 0.5 and safety.toxicity.judge to 0.8, '
      + 'each the value its source shipped with. They are not interchangeable numbers.' }),
  ]));

  root.append(el('p', { class: 'notcomparable', style: 'margin-top:var(--sp-4)' }, [
    el('b', { text: 'One column is missing here, on purpose. ' }),
    el('span', { text: 'Each rail also declares a direction — input, output, or both — and the '
      + 'engine skips the ones that do not apply to the call in hand. GET /v1/rails does not '
      + 'carry that field yet, so this page will not guess at it: inventing a column the gateway '
      + 'never sent is how a console starts lying. The split is observable per request in the '
      + 'live view, which names every rail that did not apply and why.' }),
  ]));

  function draw() {
    const wantStage = stageSel.value;
    const wantTenet = tenetSel.value;
    const wantKind = kindSel.value;
    const needle = q.value.trim().toLowerCase();

    const rows = all.filter((r) => {
      if (wantStage && String(r.stage) !== wantStage) return false;
      if (wantTenet && r.tenet !== wantTenet) return false;
      if (wantKind && r.confidence_kind !== wantKind) return false;
      if (deadOnly.checked && r.available !== false) return false;
      if (!needle) return true;
      return [r.name, r.tenet, r.repo, r.tool, r.mechanism, r.capability]
        .filter(Boolean).join(' ').toLowerCase().includes(needle);
    });

    clear(list);
    if (!rows.length) {
      list.append(empty('No rail matches these filters.'));
      count.textContent = '';
      return;
    }
    list.append(el('div', { class: 'rails' }, rows.map(railCard)));
    const dead = rows.filter((r) => r.available === false).length;
    count.textContent = `${rows.length} of ${all.length} rails shown`
      + (dead ? ` · ${dead} cannot judge on this host` : '');
  }
}

function railCard(r) {
  const kind = r.confidence_kind || 'unknown';
  return el('article', { class: `railcard${r.available === false ? ' railcard--dead' : ''}` }, [
    el('div', { class: 'railcard__id' }, [
      stageTag(r.stage),
      el('p', { class: 'railcard__name', text: r.name }),
      el('p', { class: 'micro mute', text: r.tenet }),
      r.available === false ? el('span', { class: 'cannotrun', text: 'cannot run' }) : null,
      r.judgeless && r.available !== false
        ? el('span', { class: 'cannotrun', text: 'no judge' }) : null,
    ]),
    el('div', { class: 'railcard__mid' }, [
      r.tool ? el('p', { class: 'railcard__tool', text: r.tool }) : null,
      el('p', { class: 'railcard__mech', text: r.mechanism || 'mechanism not reported' }),
      el('p', { class: 'railcard__repo', text: r.repo ? `ported from ${r.repo}` : 'unattributed' }),
      kindChip(kind),
      r.available === false
        ? el('p', { class: 'railrow__why', text: `${r.unavailable_reason || 'reported unavailable'} — it is mounted, `
            + 'so it runs and returns “could not judge”, which fails closed on client-facing traffic '
            + 'without protecting anything.' })
        : null,
    ]),
    el('div', { class: 'railcard__right' }, [
      r.capability ? el('p', { class: 'micro mute', text: `covers: ${r.capability}` }) : null,
      evidence(r.evidence),
    ]),
  ]);
}
