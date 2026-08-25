// Tenets — capability coverage per tenet, and the rails mounted under it.
//
// The one thing this view must never do is let a tenet read as "green" when its
// rails cannot actually run. So the summary line is not a percentage: it is the
// count that runs today, stated next to the count that does not, with a warning
// banner on any tenet whose runtime cover is zero.

import {
  el, clear, pageHead, rule, covChip, covBar, covLegend, COVERAGE,
  stageTag, errorBox, empty,
} from '../ui.js';
import { coverage, rails } from '../api.js';

export async function render(root) {
  clear(root);
  root.append(pageHead(
    'Tenets',
    'Seven tenets, sixty-five capabilities, five honest states',
    'A capability is covered only when a rail exists, its dependencies are present, '
    + 'and it sits in the request path. The other four states each mean “not protecting '
    + 'you right now”, for four different reasons.',
  ));

  const loading = el('p', { class: 'empty', text: 'Reading /v1/coverage and /v1/rails…' });
  root.append(loading);

  let cov; let rl;
  try {
    [cov, rl] = await Promise.all([coverage(), rails()]);
  } catch (err) {
    loading.replaceWith(errorBox('Loading tenet coverage', err));
    return;
  }
  loading.remove();

  const railsByTenet = new Map();
  for (const r of rl.rails) {
    if (!railsByTenet.has(r.tenet)) railsByTenet.set(r.tenet, []);
    railsByTenet.get(r.tenet).push(r);
  }

  // ---------------------------------------------------------- the totals ----
  const totals = Object.fromEntries(COVERAGE.map((c) => [c.key, 0]));
  for (const t of cov.tenets) for (const c of COVERAGE) totals[c.key] += t.counts[c.key] || 0;
  const grand = Object.values(totals).reduce((a, b) => a + b, 0);
  const live = totals.implemented;

  root.append(el('section', { class: 'card card__pad' }, [
    el('div', { class: 'tenet__top' }, [
      el('p', { class: 'eyebrow', text: 'All tenets' }),
      el('span', { class: 'tenet__n', text: `${grand} capabilities` }),
    ]),
    el('p', { style: 'margin-top:.5rem;font:650 var(--t-h2)/1.15 var(--sans);letter-spacing:-.03em',
      text: `${live} of ${grand} run today.` }),
    el('p', { class: 'small mute', style: 'margin-top:.25rem;max-width:70ch', text:
      `The remaining ${grand - live} break down as follows. Rolling them into one `
      + '“covered” number would be the single most misleading thing this console could do.' }),
    el('div', { style: 'margin-top:1rem' }, covBar(totals)),
    el('div', { class: 'tenet__chips', style: 'margin-top:.75rem' },
      COVERAGE.map((c) => covChip(c.key, totals[c.key]))),
    el('div', { style: 'margin-top:1.25rem;padding-top:1rem;border-top:1px solid var(--line-soft)' }, [
      el('p', { class: 'eyebrow', text: 'What the five states mean' }),
      el('dl', { class: 'attr', style: 'margin-top:.75rem' }, COVERAGE.map((c) => el('div', {}, [
        el('dt', { text: c.key }),
        el('dd', { class: 'micro mute', text: c.say }),
      ]))),
    ]),
  ]));

  // ------------------------------------------------------------ per tenet ---
  root.append(rule('By tenet', `${cov.tenets.length} tenets`));

  for (const t of cov.tenets) {
    const runtime = t.counts.implemented || 0;
    const mounted = (railsByTenet.get(t.tenet) || []);
    const requestPath = mounted.filter((r) => r.stage >= 1 && r.stage <= 3);

    const card = el('section', { class: 'card card__pad tenet', style: 'margin-bottom:1rem' }, [
      el('div', { class: 'tenet__top' }, [
        el('h3', { class: 'tenet__name', text: t.tenet }),
        el('span', { class: 'tenet__n',
          text: `${runtime}/${t.total} run today · ${requestPath.length} of ${mounted.length} rails in the request path` }),
      ]),
      covBar(t.counts),
      el('div', { class: 'tenet__chips' },
        COVERAGE.filter((c) => t.counts[c.key]).map((c) => covChip(c.key, t.counts[c.key]))),
    ]);

    // The honesty rail. Three failure modes worth shouting about, in order of
    // how badly a green-looking tenet would mislead.
    const dead = mounted.filter((r) => r.available === false);
    if (dead.length) {
      card.append(el('p', { class: 'warnline' }, [
        el('span', { text: '▲' }),
        el('span', {}, [
          el('b', { text: `${dead.length} of this tenet’s ${mounted.length} rails cannot run right now. ` }),
          document.createTextNode(
            `${dead.map((r) => r.name).join(', ')} — mounted, so they report “could not judge”, `
            + 'which fails closed on client-facing traffic without protecting anything. The '
            + 'counts above are the registry’s view; this line is the running gateway’s.'),
        ]),
      ]));
    }
    if (runtime === 0) {
      card.append(el('p', { class: 'warnline' }, [
        el('span', { text: '▲' }),
        el('span', {}, [
          el('b', { text: 'Nothing under this tenet runs at request time. ' }),
          document.createTextNode(
            `All ${t.total} capabilities sit in dependency-missing, cloud-not-configured, `
            + 'offline-only or gap. There are rails, and they are real work, but a request '
            + 'passing through the gateway right now is not checked against this tenet at all.'),
        ]),
      ]));
    } else if (!dead.length && (t.counts['dependency-missing'] || 0) > 0) {
      // Only when the live rail list did not already say it — the two lines
      // carry the same warning from two sources, and printing both is noise.
      card.append(el('p', { class: 'warnline' }, [
        el('span', { text: '▲' }),
        el('span', {}, [
          el('b', { text: `${t.counts['dependency-missing']} rail(s) here cannot run. ` }),
          document.createTextNode('They are mounted, so they report “could not judge” and '
            + 'fail closed on client-facing traffic — which blocks requests without '
            + 'protecting anything. Installing the missing library or weights is what turns '
            + 'this into cover.'),
        ]),
      ]));
    }

    if (t.capabilities.length) {
      card.append(el('p', { class: 'eyebrow', style: 'margin-top:1rem', text: 'Capabilities' }));
      card.append(el('div', { class: 'caps' }, t.capabilities.map((c) => el('div', { class: 'cap' }, [
        el('div', {}, [
          el('div', { class: 'cap__name', text: c.name }),
          c.rail ? el('div', { class: 'cap__rail', text: `${c.rail}${c.repo ? ` ← ${c.repo}` : ''}` }) : null,
        ]),
        el('div', { class: 't-nowrap' }, covChip(c.status)),
        el('div', { class: 'cap__note', text: c.note || '' }),
      ]))));
    } else {
      card.append(el('p', { class: 'micro mute', style: 'margin-top:1rem', text:
        '/v1/coverage returned counts for this tenet but no per-capability rows, '
        + 'so only the totals above can be shown.' }));
    }

    // Rails grouped by cascade stage.
    card.append(el('p', { class: 'eyebrow', style: 'margin-top:1.5rem', text: 'Rails, by cascade stage' }));
    if (!mounted.length) {
      card.append(empty('No rails reported for this tenet.'));
    } else {
      const byStage = new Map();
      for (const r of mounted) {
        if (!byStage.has(r.stage)) byStage.set(r.stage, []);
        byStage.get(r.stage).push(r);
      }
      const groups = [...byStage.keys()].sort((a, b) => a - b);
      card.append(el('div', { class: 'grid', style: 'margin-top:.75rem' }, groups.map((s) => {
        const list = byStage.get(s).sort((a, b) => a.name.localeCompare(b.name));
        return el('div', {}, [
          el('div', { style: 'display:flex;align-items:center;gap:.6rem;flex-wrap:wrap' }, [
            stageTag(s, { withKind: true }),
            el('span', { class: 'micro mute', text: `${list.length} rail${list.length === 1 ? '' : 's'}` }),
          ]),
          el('div', { class: 'railgroup', style: 'margin-top:.5rem' }, list.map((r) => el('div', {
            class: `railrow${r.available === false ? ' railrow--dead' : ''}`,
          }, [
            el('span', { class: 'conf__k', data: { kind: r.confidence_kind || 'unknown' },
              text: r.confidence_kind || 'unknown' }),
            el('div', {}, [
              el('div', { class: 'railrow__name' }, [
                el('span', { text: r.name }),
                r.available === false
                  ? el('span', { class: 'cannotrun', style: 'margin-left:.5rem', text: 'cannot run' })
                  : null,
              ]),
              r.available === false && r.unavailable_reason
                ? el('div', { class: 'railrow__why', text: r.unavailable_reason }) : null,
              el('div', { class: 'railrow__mech', text:
                [r.tool, r.mechanism].filter(Boolean).join(' · ') || '—' }),
              r.repo ? el('div', { class: 'railrow__mech', text: `from ${r.repo}` }) : null,
            ]),
          ]))),
          s === 4
            ? el('p', { class: 'micro mute', style: 'margin-top:.5rem', text:
                'Offline rails are refused by the cascade engine, so nothing here defends a live request.' })
            : null,
        ]);
      })));
    }

    root.append(card);
  }

  root.append(el('div', { class: 'card card__pad', style: 'margin-top:1.5rem' }, [
    el('p', { class: 'eyebrow', text: 'Legend' }),
    el('div', { style: 'margin-top:.75rem' }, covLegend()),
    el('p', { class: 'micro mute', style: 'margin-top:.75rem;max-width:74ch', text:
      'The pip meter carries the same ordering as the colour, so the five states stay '
      + 'distinguishable without relying on hue.' }),
  ]));
}
