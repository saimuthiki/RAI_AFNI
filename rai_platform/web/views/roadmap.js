// Roadmap — the 90-day adoption plan against what is actually wired.
//
// Three readings of this page have gone wrong before, so all three are answered
// structurally rather than in a footnote:
//
//  1. PHASE IS NOT STAGE. A phase is a calendar window; a stage is what one
//     request costs. They used to be drawn in the same three colours, which is
//     the single best way to guarantee the confusion. Phases now wear a 90-day
//     bracket in ink and carry a day range; no stage hue appears on this page.
//
//  2. "Named in a phase" is not "adopted in a phase". Phase 1 names Deepchecks,
//     Guardrails AI and Agentic Security; none of the three is adopted. Those
//     arrive as notes[], so they are rendered as a first-class MENTIONS block
//     above the repo list — the caveat has to come before what it qualifies.
//
//  3. `present_in_platform` is not adoption. A repo reads present when a rail
//     cites it as the source of a pattern. Three un-adopted repos are present
//     because their regexes were read and reimplemented. Wherever that flag is
//     true on a not-adopted repo, this view says so in words.

import {
  el, clear, pageHead, rule, covChip, errorBox, empty, pill, phaseTag, phaseNumber,
  phaseWindow, stageTag, statRow, plural,
} from '../ui.js';
import { phases } from '../api.js';

const ADOPTION_CLASS = {
  'Adopt now': 'tag--adopt',
  'Combine with another': 'tag--combine',
  'Bench for later': 'tag--bench',
  Skip: 'tag--skip',
};

export async function render(root) {
  clear(root);
  root.append(pageHead(
    'Roadmap',
    'A 90-day plan, and what of it is actually running',
    'Four buckets, twenty-three repositories, and three labels that mean less than '
    + 'they look like they mean. Read the two-axis note first if you have ever said '
    + '“phase 2” meaning “stage 2”.',
  ));

  const loading = el('p', { class: 'empty', text: 'Reading /v1/phases…' });
  root.append(loading);

  let data;
  try { data = await phases(); } catch (err) {
    loading.replaceWith(errorBox('Loading the roadmap', err)); return;
  }
  loading.remove();

  // --------------------------------------------------- phase is not stage ---
  root.append(el('div', { class: 'axes' }, [
    el('div', { class: 'axis' }, [
      el('p', { class: 'axis__q', text: 'This page’s axis' }),
      el('p', { class: 'axis__t', text: 'Phase — a calendar window' }),
      el('div', { class: 'axis__ex' }, ['Phase 1', 'Phase 2', 'Phase 3'].map((p) => phaseTag(p))),
      el('p', { class: 'axis__say', text:
        'When a repository gets adopted, across ninety days. One repository, one phase. '
        + 'It says nothing at all about what a request costs.' }),
    ]),
    el('div', { class: 'axis' }, [
      el('p', { class: 'axis__q', text: 'A different axis entirely' }),
      el('p', { class: 'axis__t', text: 'Stage — what one request pays' }),
      el('div', { class: 'axis__ex' }, [1, 2, 3].map((n) => stageTag(n))),
      el('p', { class: 'axis__say', text:
        'How far up the cost ladder one request had to climb. A Phase-1 repository '
        + 'routinely backs a Stage-3 rail; the two numbers are unrelated and are drawn '
        + 'in different shapes so they cannot be swapped by eye.' }),
    ]),
  ]));

  // ------------------------------------------------------------- the board --
  const totals = { repos: 0, present: 0, presentButNot: 0, adopt: 0 };
  for (const ph of data.phases) {
    totals.repos += ph.repos.length;
    for (const r of ph.repos) {
      if (r.present_in_platform) totals.present += 1;
      if (r.adoption === 'Adopt now') totals.adopt += 1;
      if (r.present_in_platform && (r.adoption === 'Skip' || r.adoption === 'Bench for later')) {
        totals.presentButNot += 1;
      }
    }
  }

  root.append(rule('The plan', `${totals.repos} repositories reviewed`));
  root.append(timeline(data.phases));

  root.append(statRow([
    { label: 'Reviewed', value: String(totals.repos), note: 'read at source level, not from a README' },
    { label: 'Contributing', value: String(totals.present), tone: 'good',
      note: 'the registry traces a rail or a capability back to this repo' },
    { label: 'Adopt-now verdicts', value: String(totals.adopt),
      note: 'across all three phases' },
    { label: 'Present, never adopted', value: String(totals.presentButNot), tone: 'warn',
      note: 'pattern read and reimplemented in AFNI-owned code — not a dependency' },
  ]));

  // A standing explainer, because two of the three misreadings are one glance away.
  root.append(el('section', { class: 'card card__pad', style: 'margin-top:var(--sp-4)' }, [
    el('p', { class: 'eyebrow', text: 'Read these three labels carefully' }),
    el('dl', { class: 'attr', style: 'margin-top:var(--sp-3)' }, [
      el('div', {}, [
        el('dt', { text: 'present in platform' }),
        el('dd', { class: 'small', text:
          'A rail somewhere cites this repo as the source of a pattern. That is provenance, '
          + 'not a dependency, and it is not adoption. Repos marked “Skip” or “Bench” can be '
          + 'present because their regexes or validator shapes were read and ported into '
          + 'AFNI-owned rails.' }),
      ]),
      el('div', {}, [
        el('dt', { text: 'mentions' }),
        el('dd', { class: 'small', text:
          'A phase can name a repo without adopting it — to log a licence question, a '
          + 'supply-chain compromise or a data-residency risk. Those are listed separately '
          + 'under each phase and must not be counted as adoptions.' }),
      ]),
      el('div', {}, [
        el('dt', { text: 'implemented as' }),
        el('dd', { class: 'small', text:
          'The coverage states this repo backs in the running platform. A repo can be '
          + 'adopted and still back nothing but offline-only cover, which is not runtime '
          + 'protection.' }),
      ]),
    ]),
  ]));

  // ----------------------------------------------------------- per phase ----
  let unlinkable = [];

  for (const ph of data.phases) {
    const n = phaseNumber(ph.phase);
    const w = phaseWindow(n);
    const adopted = ph.repos.filter((r) => r.adoption === 'Adopt now').length;

    root.append(el('div', { class: 'rule', style: 'margin-top:var(--sp-6)' }, [
      el('h2', { class: 'rule__t', text: n ? `Phase ${n}` : 'Reviewed and not adopted' }),
      el('span', { class: 'rule__d', text: w ? w.label.replace('–', ' to ') : 'off the calendar' }),
    ]));
    root.append(el('div', { style: 'display:flex;flex-wrap:wrap;gap:var(--sp-4);align-items:center;margin-bottom:var(--sp-3)' }, [
      phaseTag(ph.phase),
      el('span', { class: 'micro mute', text:
        `${plural(ph.repos.length, 'repository', 'repositories')} · ${adopted} adopt-now · `
        + `${ph.repos.filter((r) => r.present_in_platform).length} contributing today` }),
    ]));

    // The mentions block sits ABOVE the repo list on purpose: it changes how the
    // list below should be read.
    if (ph.notes.length) {
      root.append(el('div', { class: 'card card__pad', style: 'margin-bottom:var(--sp-3)' }, [
        el('p', { class: 'notes__t', text: 'This phase names these without adopting them' }),
        el('ul', { class: 'notes', style: 'margin-top:var(--sp-2)' },
          ph.notes.map((x) => el('li', {}, el('span', { text: x })))),
      ]));
    }

    if (!ph.repos.length) { root.append(empty('No repositories in this bucket.')); continue; }

    const card = el('section', { class: 'card' });
    for (const r of ph.repos) {
      const notAdopted = r.adoption === 'Skip' || r.adoption === 'Bench for later';
      card.append(el('article', { class: 'repo' }, [
        el('div', { class: 'repo__top' }, [
          el('h3', { class: 'repo__name', text: r.display }),
          el('span', { class: 'repo__slug', text: r.repo }),
        ]),
        el('div', { class: 'repo__flags' }, [
          pill(r.adoption, ADOPTION_CLASS[r.adoption] || ''),
          r.conditional ? pill('conditional — gated on something outside our control', 'tag--conditional') : null,
          r.present_in_platform
            ? pill('contributing today', 'tag--present')
            : pill('nothing cites it yet', 'tag--absent'),
          ...r.implemented_as.map((s) => covChip(s)),
        ]),
        el('p', { class: 'repo__why', text: r.why }),
        r.present_in_platform && notAdopted
          ? el('p', { class: 'ported' }, [
              el('b', { text: 'Present, not adopted. ' }),
              document.createTextNode(
                `This repo’s verdict is “${r.adoption}”. It reads as contributing because a rail `
                + 'cites it as the source of a pattern that was read and reimplemented in '
                + 'AFNI-owned code. Nothing here takes a dependency on it, and it is not running '
                + 'in the platform.'),
            ])
          : null,
        !r.present_in_platform && r.adoption === 'Adopt now'
          ? el('p', { class: 'warnline' }, [
              el('span', { text: '▲' }),
              el('span', {}, [
                el('b', { text: 'Adopt-now, and nothing links it yet. ' }),
                document.createTextNode(
                  'Either the work has not landed, or a capability it backs is registered without '
                  + 'attribution — in which case it is built but unlinkable. Check the unlinkable '
                  + 'list below before reading this as “not started”.'),
              ]),
            ])
          : null,
      ]));
    }
    root.append(card);

    if (ph.unlinkable?.length && !unlinkable.length) unlinkable = ph.unlinkable;
  }

  root.append(rule('The number that gets misquoted', ''));
  root.append(el('section', { class: 'card card__pad' }, [
    el('p', { class: 'kicker', text:
      `${totals.present} of ${totals.repos} repositories contribute to the running platform — `
      + `and ${totals.presentButNot} of those were never adopted.` }),
    el('p', { class: 'small mute', style: 'margin-top:var(--sp-3);max-width:80ch', text:
      'That second number is not “we adopted repos we said we would skip”. It is “we read '
      + 'their source, took the pattern, and wrote our own”. Safe Zone’s Go service is not '
      + 'running anywhere here; its structured-output checks were reimplemented in stdlib '
      + 'Python. The registry field is called present_in_platform rather than adopted for '
      + 'exactly this reason.' }),
  ]));

  if (unlinkable.length) {
    root.append(el('details', { class: 'card card__pad', style: 'margin-top:var(--sp-4)' }, [
      el('summary', { class: 'small', text:
        `${plural(unlinkable.length, 'capability', 'capabilities')} are registered with no `
        + 'attribution, so no repository can be linked to them' }),
      el('ul', { class: 'small mute', style: 'margin-top:var(--sp-3);display:grid;gap:.25rem' },
        unlinkable.map((u) => el('li', { class: 'num', text: u }))),
      el('p', { class: 'micro mute', style: 'margin-top:var(--sp-2);max-width:80ch', text:
        'These read as absent from every phase even though they are registered. The join runs '
        + 'through a rail’s attribution, so a capability registered without one cannot be '
        + 'traced back to the repo that inspired it — SHAP is the honest example: registered '
        + 'under Explainability as offline-only, with no attribution, so Phase 2 reads as '
        + 'missing it when the truth is “registered, unattributed”.' }),
    ]));
  }
}

/* ==========================================================================
   THE 90-DAY BOARD
   ========================================================================== */

function timeline(list) {
  const inPlan = list.filter((p) => phaseNumber(p.phase));
  const off = list.filter((p) => !phaseNumber(p.phase));

  const cell = (ph) => {
    const n = phaseNumber(ph.phase);
    const w = phaseWindow(n);
    const present = ph.repos.filter((r) => r.present_in_platform).length;
    const pct = ph.repos.length ? Math.round((present / ph.repos.length) * 100) : 0;
    return el('div', { class: `tlcell${n ? '' : ' tlcell--off'}` }, [
      el('p', { class: 'tlcell__days', text: w ? w.label : 'no window' }),
      el('p', { class: 'tlcell__lab', text: n ? `Phase ${n}` : 'Not adopted' }),
      el('p', {}, [
        el('span', { class: 'tlcell__n', text: `${present}/${ph.repos.length}` }),
        el('span', { class: 'micro mute', text: '  contributing' }),
      ]),
      el('div', { class: 'tlcell__meter', role: 'img',
        'aria-label': `${present} of ${ph.repos.length} repositories in this bucket contribute to the platform` },
        el('i', { style: `width:${pct}%` })),
      el('p', { class: 'tlcell__note', text: n
        ? `${ph.repos.filter((r) => r.adoption === 'Adopt now').length} adopt-now`
          + (ph.notes.length
            ? ` · ${plural(ph.notes.length, 'mention')}, none of them an adoption`
            : '')
        : 'reviewed, rejected. Some of their patterns were still read and ported.' }),
    ]);
  };

  return el('div', { class: 'tl' }, [
    el('div', { class: 'tl__scale', 'aria-hidden': 'true' }, [
      ...['day 0', 'day 30', 'day 60'].map((d) => el('div', { class: 'tl__tick' },
        el('span', { text: d }))),
      el('span', { class: 'tl__end', text: 'day 90' }),
    ]),
    el('div', { class: 'tl__win' }, inPlan.map(cell)),
    ...off.map((ph) => el('div', { style: 'margin-top:var(--sp-2)' }, cell(ph))),
  ]);
}
