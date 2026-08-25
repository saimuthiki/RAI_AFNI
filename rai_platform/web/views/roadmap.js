// Roadmap — the phase board, with the two distinctions that get misread.
//
//  1. "named in a phase" is not "adopted in a phase". Phase 1 mentions
//     Deepchecks, Guardrails AI and Agentic Security; none of the three is
//     adopted. Those mentions arrive as `notes[]`, so the notes are rendered as
//     a first-class block labelled MENTIONS — not as a footnote.
//
//  2. `present_in_platform` is not "adopted". A repo shows present when a rail
//     cites it as the source of a pattern. Three un-adopted repos are present
//     because their regexes were ported. Anywhere that flag is true on a
//     not-adopted repo, this view says so in words.

import {
  el, clear, pageHead, rule, covChip, errorBox, empty, pill,
} from '../ui.js';
import { phases } from '../api.js';

const phaseClass = (name) => {
  const m = /phase\s*([123])/i.exec(name);
  return m ? `p${m[1]}` : 'none';
};

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
    'What each phase adopts — and what it only mentions',
    'Four buckets, twenty-three repositories, and one distinction that a naïve read '
    + 'of the roadmap prose gets wrong.',
  ));

  const loading = el('p', { class: 'empty', text: 'Reading /v1/phases…' });
  root.append(loading);

  let data;
  try { data = await phases(); } catch (err) { loading.replaceWith(errorBox('Loading the roadmap', err)); return; }
  loading.remove();

  // A standing explainer, because both misreadings are one glance away.
  root.append(el('section', { class: 'card card__pad' }, [
    el('p', { class: 'eyebrow', text: 'Read these two labels carefully' }),
    el('dl', { class: 'attr', style: 'margin-top:.75rem' }, [
      el('div', {}, [
        el('dt', { text: 'present in platform' }),
        el('dd', { class: 'small', text:
          'A rail somewhere cites this repo as the source of a pattern. That is '
          + 'provenance, not a dependency, and it is NOT adoption. Repos marked '
          + '“Skip” or “Bench” can be present because their regexes or validator '
          + 'shapes were read and ported into AFNI-owned rails.' }),
      ]),
      el('div', {}, [
        el('dt', { text: 'mentions' }),
        el('dd', { class: 'small', text:
          'A phase can name a repo without adopting it — to log a licence question, '
          + 'a supply-chain compromise or a data-residency risk. Those are listed '
          + 'separately under each phase and must not be counted as adoptions.' }),
      ]),
      el('div', {}, [
        el('dt', { text: 'implemented as' }),
        el('dd', { class: 'small', text:
          'The coverage states this repo backs in the running platform. A repo can '
          + 'be adopted and still back nothing but offline-only cover.' }),
      ]),
    ]),
  ]));

  const totals = { repos: 0, present: 0, presentButNot: 0 };
  // The same list rides on every phase, so it is collected and shown once.
  let unlinkable = [];

  for (const ph of data.phases) {
    const cls = phaseClass(ph.phase);
    const adopted = ph.repos.filter((r) => r.adoption === 'Adopt now').length;
    totals.repos += ph.repos.length;

    root.append(el('div', { class: `phase phase--${cls}`, style: 'margin-top:2rem' }, [
      el('div', { class: 'phase__head' }, [
        el('span', { class: 'phase__tag', text: cls === 'none' ? 'not adopted' : `phase ${cls[1]}` }),
        el('h2', { class: 'phase__name', text: ph.phase }),
        el('span', { class: 'rule__d', style: 'margin-left:auto', text:
          `${ph.repos.length} repos · ${adopted} adopt-now` }),
      ]),
    ]));

    // The mentions block sits ABOVE the repo list on purpose: it is the caveat
    // that changes how the list below should be read.
    if (ph.notes.length) {
      root.append(el('div', { class: 'card card__pad', style: 'margin-top:.75rem' }, [
        el('p', { class: 'notes__t', text: 'This phase names these without adopting them' }),
        el('ul', { class: 'notes', style: 'margin-top:.5rem' },
          ph.notes.map((n) => el('li', {}, el('span', { text: n })))),
      ]));
    }

    if (!ph.repos.length) {
      root.append(empty('No repositories in this bucket.'));
      continue;
    }

    const card = el('section', { class: 'card', style: 'margin-top:.75rem' });
    for (const r of ph.repos) {
      const notAdopted = r.adoption === 'Skip' || r.adoption === 'Bench for later';
      if (r.present_in_platform) totals.present += 1;
      if (r.present_in_platform && notAdopted) totals.presentButNot += 1;

      card.append(el('article', { class: 'repo' }, [
        el('div', { class: 'repo__top' }, [
          el('h3', { class: 'repo__name', text: r.display }),
          el('span', { class: 'repo__slug', text: r.repo }),
        ]),
        el('div', { class: 'repo__flags' }, [
          pill(r.adoption, ADOPTION_CLASS[r.adoption] || ''),
          r.conditional ? pill('conditional — gated on something outside our control', 'tag--conditional') : null,
          r.present_in_platform
            ? pill('present in platform', 'tag--present')
            : pill('not present in platform', 'tag--absent'),
          ...r.implemented_as.map((s) => covChip(s)),
        ]),
        el('p', { class: 'repo__why', text: r.why }),
        r.present_in_platform && notAdopted
          ? el('p', { class: 'ported' }, [
              el('b', { text: 'Present, not adopted. ' }),
              document.createTextNode(
                `This repo’s verdict is “${r.adoption}”. It shows as present because a rail `
                + 'cites it as the source of a pattern that was read and reimplemented in '
                + 'AFNI-owned code. Nothing here takes a dependency on it, and it is not '
                + 'running in the platform.'),
            ])
          : null,
        !r.present_in_platform && r.adoption === 'Adopt now'
          ? el('p', { class: 'warnline' }, [
              el('span', { text: '▲' }),
              el('span', {}, [
                el('b', { text: 'Adopt-now, and nothing links it yet. ' }),
                document.createTextNode(
                  'Either the work has not landed, or a capability it backs is registered '
                  + 'without attribution — in which case it is built but unlinkable. Check '
                  + 'the unlinkable list below before reading this as “not started”.'),
              ]),
            ])
          : null,
      ]));
    }
    root.append(card);

    if (ph.unlinkable?.length && !unlinkable.length) unlinkable = ph.unlinkable;
  }

  root.append(rule('Across all four buckets', ''));
  root.append(el('section', { class: 'card card__pad' }, [
    el('p', { style: 'font:650 var(--t-h3)/1.3 var(--sans);letter-spacing:-.02em', text:
      `${totals.present} of ${totals.repos} repositories are present in the platform — `
      + `and ${totals.presentButNot} of those were never adopted.` }),
    el('p', { class: 'small mute', style: 'margin-top:.5rem;max-width:76ch', text:
      'That second number is the one that gets misquoted. It is not “we adopted repos we '
      + 'said we would skip”. It is “we read their source, took the pattern, and wrote our own”.' }),
  ]));

  if (unlinkable.length) {
    root.append(el('details', { class: 'card card__pad', style: 'margin-top:1rem' }, [
      el('summary', { class: 'small', text:
        `${unlinkable.length} capabilities are registered with no attribution, so no repo can be linked to them` }),
      el('ul', { class: 'small mute', style: 'margin-top:.75rem;display:grid;gap:.25rem' },
        unlinkable.map((u) => el('li', { class: 'num', text: u }))),
      el('p', { class: 'micro mute', style: 'margin-top:.5rem;max-width:76ch', text:
        'These read as absent from every phase even though they are registered. The join '
        + 'runs through a rail’s attribution, so a capability registered without one cannot '
        + 'be traced back to the repo that inspired it — it looks missing when it is not.' }),
    ]));
  }
}
