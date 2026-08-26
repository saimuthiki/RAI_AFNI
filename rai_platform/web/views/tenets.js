// Tenets — capability coverage per tenet, and the rails mounted under it.
//
// The one thing this view must never do is let a tenet read as green when its
// rails cannot actually run. So there is no percentage anywhere: the headline is
// the count that runs today stated beside the counts that do not, and any tenet
// with zero runtime cover says so in a sentence.
//
// The matrix at the top is deliberately NOT a heatmap. Five ordinal states
// across the columns are a categorical axis; shading each cell by its count
// would encode magnitude on an axis that has none, and would make "6
// implemented" and "6 gaps" look like the same fact. The numbers are the marks.
// Only the `gap` column is flagged, because it is the one state where the honest
// answer is "nothing looked".

import {
  el, clear, pageHead, rule, covChip, covBar, covLegend, COVERAGE, coverageMeta,
  stageTag, kindChip, errorBox, empty, table, statRow, plural,
} from '../ui.js';
import { coverage, railsWithHealth } from '../api.js';

export async function render(root) {
  clear(root);
  root.append(pageHead(
    'Tenets',
    'Seven tenets, sixty-five capabilities, five honest states',
    'A capability is covered only when a rail exists, its dependencies are present, and '
    + 'it sits in the request path. The other four states each mean “not protecting you '
    + 'right now” — for four different reasons, which is why one “covered” number would '
    + 'be the most misleading thing this console could print.',
  ));

  const loading = el('p', { class: 'empty', text: 'Reading /v1/coverage and /v1/rails…' });
  root.append(loading);

  let cov; let inv;
  try {
    [cov, inv] = await Promise.all([coverage(), railsWithHealth()]);
  } catch (err) {
    loading.replaceWith(errorBox('Loading tenet coverage', err));
    return;
  }
  loading.remove();

  const railsByTenet = new Map();
  for (const r of inv.rails) {
    if (!railsByTenet.has(r.tenet)) railsByTenet.set(r.tenet, []);
    railsByTenet.get(r.tenet).push(r);
  }

  const totals = Object.fromEntries(COVERAGE.map((c) => [c.key, 0]));
  for (const t of cov.tenets) for (const c of COVERAGE) totals[c.key] += t.counts[c.key] || 0;
  const grand = Object.values(totals).reduce((a, b) => a + b, 0);

  root.append(statRow([
    { label: 'Capabilities', value: String(grand), note: `across ${cov.tenets.length} tenets` },
    { label: 'Run today', value: String(totals.implemented), tone: 'good',
      note: 'a rail exists, its dependencies are here, and it is in the request path' },
    { label: 'Cannot run', value: String(totals['dependency-missing']), tone: 'hazard',
      note: 'the rail is mounted and returns “could not judge” — it blocks without protecting' },
    { label: 'Needs a credential', value: String(totals['cloud-not-configured']),
      note: 'only a paid managed service covers these, and none is configured' },
    { label: 'CI only', value: String(totals['offline-only']),
      note: 'real work, never reachable from a request — not runtime cover' },
    { label: 'Nothing looks', value: String(totals.gap), tone: totals.gap ? 'warn' : 'good',
      note: 'no rail implements these at all' },
  ]));

  // -------------------------------------------------------------- matrix ----
  root.append(rule('The whole picture', `${grand} capabilities`));
  root.append(coverageMatrix(cov, totals, grand));
  root.append(el('div', { class: 'card card__pad', style: 'margin-top:var(--sp-4)' }, [
    el('p', { class: 'eyebrow', text: 'The five states' }),
    el('div', { style: 'margin-top:var(--sp-3)' }, covLegend()),
    el('dl', { class: 'attr', style: 'margin-top:var(--sp-4)' }, COVERAGE.map((c) => el('div', {}, [
      el('dt', { text: c.key }),
      el('dd', { class: 'micro mute', text: c.say }),
    ]))),
    el('p', { class: 'micro mute', style: 'margin-top:var(--sp-3);max-width:80ch', text:
      'The pip meter carries the same ordering as the colour, so the five states stay '
      + 'distinguishable without relying on hue. Measured worst-case separation between '
      + 'adjacent states under protanopia is ΔE 9.7 — inside the floor band, which is why '
      + 'the pips and the text label are always present.' }),
  ]));

  // ------------------------------------------------------------ per tenet ---
  root.append(rule('By tenet', plural(cov.tenets.length, 'tenet')));

  for (const t of cov.tenets) {
    const runtime = t.counts.implemented || 0;
    const mounted = railsByTenet.get(t.tenet) || [];
    const requestPath = mounted.filter((r) => r.stage >= 1 && r.stage <= 3);
    const dead = mounted.filter((r) => r.available === false);

    const card = el('section', { class: 'card card__pad tenet', style: 'margin-bottom:var(--sp-4)' }, [
      el('div', { class: 'tenet__top' }, [
        el('h3', { class: 'tenet__name', text: t.tenet }),
        el('span', { class: 'tenet__n',
          text: `${runtime}/${t.total} run today · ${requestPath.length} of ${mounted.length} rails in the request path` }),
      ]),
      covBar(t.counts),
      el('div', { class: 'tenet__chips' },
        COVERAGE.filter((c) => t.counts[c.key]).map((c) => covChip(c.key, t.counts[c.key]))),
    ]);

    // The honesty rails, in order of how badly a green-looking tenet would
    // mislead. The first is the running gateway's view, not the registry's.
    if (dead.length) {
      card.append(el('p', { class: 'warnline' }, [
        el('span', { text: '▲' }),
        el('span', {}, [
          el('b', { text: `${dead.length} of this tenet’s ${mounted.length} rails cannot run on this host. ` }),
          document.createTextNode(
            `${dead.map((r) => r.name).join(', ')} — mounted, so they run and report “could not `
            + 'judge”, which fails closed on client-facing traffic without protecting anything. '
            + 'The counts above are the registry’s view; this line is the gateway’s.'),
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
      card.append(el('p', { class: 'warnline' }, [
        el('span', { text: '▲' }),
        el('span', {}, [
          el('b', { text: `${plural(t.counts['dependency-missing'], 'capability', 'capabilities')} here cannot be judged. ` }),
          document.createTextNode('The rail is mounted, so it returns “could not judge” and fails '
            + 'closed on client-facing traffic — which blocks requests without protecting '
            + 'anything. Installing the missing library or weights is what turns this into cover.'),
        ]),
      ]));
    }

    if (t.capabilities.length) {
      card.append(el('p', { class: 'eyebrow', style: 'margin-top:var(--sp-4)', text: 'Capabilities' }));
      card.append(el('div', { class: 'caps' }, t.capabilities.map((c) => el('div', { class: 'cap' }, [
        el('div', {}, [
          el('div', { class: 'cap__name', text: c.name }),
          c.rail ? el('div', { class: 'cap__rail', text: `${c.rail}${c.repo ? ` ← ${c.repo}` : ''}` }) : null,
        ]),
        el('div', { class: 't-nowrap' }, covChip(c.status)),
        el('div', { class: 'cap__note', text: c.note || '' }),
      ]))));
    } else {
      card.append(el('p', { class: 'micro mute', style: 'margin-top:var(--sp-4)', text:
        '/v1/coverage returned counts for this tenet but no per-capability rows, '
        + 'so only the totals above can be shown.' }));
    }

    // Rails grouped by cascade stage — cost order, not alphabetical. Folded,
    // because there is a whole view for rails now; the disclosure summary still
    // states the count and the number that cannot run, so nothing important is
    // behind the click.
    const railBox = el('details', { class: 'railfold', style: 'margin-top:var(--sp-5)' }, [
      el('summary', {}, [
        el('span', { class: 'eyebrow', text: 'Rails, by cascade stage' }),
        el('span', { class: 'railfold__n', text: `${plural(mounted.length, 'rail')}`
          + (dead.length ? ` · ${dead.length} cannot run` : '') }),
      ]),
    ]);
    card.append(railBox);
    if (!mounted.length) {
      railBox.append(empty('No rails reported for this tenet.'));
    } else {
      const byStage = new Map();
      for (const r of mounted) {
        if (!byStage.has(r.stage)) byStage.set(r.stage, []);
        byStage.get(r.stage).push(r);
      }
      railBox.append(el('div', { class: 'grid grid--2', style: 'margin-top:var(--sp-3)' },
        [...byStage.keys()].sort((a, b) => a - b).map((s) => {
          const list = byStage.get(s).sort((a, b) => a.name.localeCompare(b.name));
          return el('div', {}, [
            el('div', { style: 'display:flex;align-items:center;gap:.6rem;flex-wrap:wrap' }, [
              stageTag(s, { withKind: true }),
              el('span', { class: 'micro mute', text: plural(list.length, 'rail') }),
            ]),
            el('div', { class: 'railgroup', style: 'margin-top:var(--sp-2)' }, list.map((r) => el('div', {
              class: `railrow${r.available === false ? ' railrow--dead' : ''}`,
            }, [
              kindChip(r.confidence_kind || 'unknown'),
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
                r.repo ? el('div', { class: 'railrow__mech', text: `ported from ${r.repo}` }) : null,
              ]),
            ]))),
            s === 4
              ? el('p', { class: 'micro mute', style: 'margin-top:var(--sp-2)', text:
                  'Offline rails are refused by the cascade engine, so nothing here defends a live request.' })
              : null,
          ]);
        })));
    }

    root.append(card);
  }
}

/* ==========================================================================
   THE MATRIX
   ========================================================================== */

function coverageMatrix(cov, totals, grand) {
  const head = [
    'Tenet',
    ...COVERAGE.map((c) => ({ label: c.short })),
    'Total',
  ];

  const rows = cov.tenets.map((t) => el('tr', {}, [
    el('td', { class: 'mx__tenet', text: t.tenet }),
    ...COVERAGE.map((c) => {
      const n = t.counts[c.key] || 0;
      return el('td', {
        class: 'mx__n',
        data: { zero: n === 0 ? '1' : '0', flag: c.key === 'gap' && n > 0 ? 'hazard' : null },
        text: n === 0 ? '·' : String(n),
        title: n === 0 ? `no ${c.key} capabilities` : `${n} × ${c.key} — ${coverageMeta(c.key).say}`,
      });
    }),
    el('td', { class: 'mx__n mx__tot', text: String(t.total) }),
  ]));

  const tbl = table(head, rows);
  const t = tbl.querySelector('table');
  t.classList.add('mx');
  // The header cells for the five states carry the coverage chip, so the column
  // meaning travels with the column rather than living in a legend elsewhere.
  const ths = [...t.querySelectorAll('thead th')];
  COVERAGE.forEach((c, i) => {
    const th = ths[i + 1];
    if (!th) return;
    th.classList.add('mx__state');
    th.dataset.state = c.key;
    th.title = `${c.key} — ${coverageMeta(c.key).say}`;
    clear(th).append(
      el('span', { class: 'mx__rule', 'aria-hidden': 'true' }),
      el('span', { class: 'mx__short', text: c.short }),
      el('span', { class: 'mx__key', text: c.key }),
    );
  });
  t.append(el('tfoot', {}, el('tr', {}, [
    el('td', { text: 'All tenets' }),
    ...COVERAGE.map((c) => el('td', {
      class: 'mx__n', data: { flag: c.key === 'gap' && totals[c.key] > 0 ? 'hazard' : null },
      text: String(totals[c.key]),
    })),
    el('td', { class: 'mx__n mx__tot', text: String(grand) }),
  ])));
  return tbl;
}
