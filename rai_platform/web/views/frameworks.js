// Frameworks — all 23 reviewed repositories, joined to the tenets they serve.
//
// The join is client-side and worth stating plainly: /v1/repositories gives the
// repo list and its adoption verdict, /v1/rails gives each rail's attribution. A
// rail's `repo` can name more than one source ("hai-guardrails-main + garak-main"),
// so it is split on "+" before matching — otherwise a compound attribution
// silently credits nothing and a contributing repo reads as unused.
//
// Two source strings in /v1/rails are not repositories at all: a hosted cloud
// service, and rails AFNI composed itself from several vocabularies. They get
// their own block rather than being folded into the 23, because a managed API is
// not a framework anybody vendored, and the count of 23 has to stay 23.

import {
  el, clear, pageHead, rule, table, stageTag, adoptionTag, adoptionRank, covChip,
  errorBox, pill, field, statRow, plural,
} from '../ui.js';
import { repositories, railsWithHealth } from '../api.js';
const splitRepos = (s) => String(s || '').split('+').map((x) => x.trim()).filter(Boolean);

/** Mechanism strings are written for a human reading one rail
 *  ("Keyword/Regex - length, regex_match, valid_choices, …"). In a table column
 *  the useful part is the family, so take the head and dedupe — otherwise one
 *  repo's cell reads "Keyword/Regex, Keyword/Regex + Shannon entropy gate,
 *  Keyword/Regex + n-gram", which is three ways of saying regex. */
const mechFamily = (m) => String(m || '').split(/\s+[-+]\s+/)[0].trim();

/** The tenet names are long and this column holds up to seven of them. The full
 *  name rides along as a title; nothing is hidden, it is abbreviated. */
const TENET_SHORT = {
  'Explainability & Transparency': 'Explainability',
  'Profanity / Content Safety': 'Content Safety',
  'Hallucination / Reliability': 'Hallucination',
  'Fairness & Bias': 'Fairness',
};
const shortTenet = (t) => TENET_SHORT[t] || t;

export async function render(root) {
  clear(root);
  root.append(pageHead(
    'Frameworks',
    'Twenty-three repositories read at source level, sixteen still in the build',
    'One row per repository: its adoption verdict, which tenets its patterns serve, the '
    + 'cascade stages those rails sit in, and the mechanism. Being present here is '
    + 'provenance — it means a rail cites this repo as the source of a pattern, not that '
    + 'the platform depends on it.',
  ));

  const loading = el('p', { class: 'empty',
    text: 'Reading /v1/repositories and /v1/rails…' });
  root.append(loading);

  let ph; let inv;
  try { [ph, inv] = await Promise.all([repositories(), railsWithHealth()]); } catch (err) {
    loading.replaceWith(errorBox('Loading the framework table', err)); return;
  }
  loading.remove();

  // repo slug -> entry
  const byRepo = new Map();
  for (const g of ph.groups) for (const r of g.repos) byRepo.set(r.repo, r);

  // repo slug -> what it contributes
  const contrib = new Map();
  const foreign = new Map();
  for (const rail of inv.rails) {
    for (const part of splitRepos(rail.repo)) {
      const bucket = byRepo.has(part) ? contrib : foreign;
      if (!bucket.has(part)) {
        bucket.set(part, { tenets: new Set(), stages: new Set(), mechs: new Set(), rails: [], dead: 0 });
      }
      const c = bucket.get(part);
      c.tenets.add(rail.tenet);
      c.stages.add(rail.stage);
      if (rail.mechanism) c.mechs.add(mechFamily(rail.mechanism));
      c.rails.push(rail);
      if (rail.available === false) c.dead += 1;
    }
  }

  // Two different, both-true counts, and they are NOT the same number.
  //   present_in_platform (16) — the registry can trace something here, runtime
  //     rail or offline capability alike.
  //   cited by a mounted rail (12) — the stricter test: a rail in the running
  //     cascade names it. Fairlearn is in the first and not the second, which is
  //     correct: batch fairness jobs are real work and are not in a request path.
  // Printing only one of them would misstate the platform in one direction or
  // the other, so both are printed and labelled.
  const present = [...byRepo.values()].filter((r) => r.present_in_platform).length;
  const cited = [...byRepo.keys()].filter((k) => contrib.has(k)).length;
  const adopted = [...byRepo.values()].filter((r) => r.adoption === 'Adopt now').length;
  const notAdopted = [...byRepo.values()]
    .filter((r) => r.adoption === 'Skip' || r.adoption === 'Bench for later').length;

  root.append(statRow([
    { label: 'Reviewed', value: String(byRepo.size),
      note: 'vendored and read at source level, so every ported pattern can cite its line' },
    { label: 'Contributing', value: String(present), tone: 'good',
      note: 'the registry traces a rail or a capability back to this repo' },
    { label: 'Cited by a live rail', value: String(cited),
      note: 'the stricter test — a rail in the running cascade names it as its source' },
    { label: 'Adopt now', value: String(adopted),
      note: 'the verdict on the repo, not its implementation status' },
    { label: 'Not adopted', value: String(notAdopted), tone: 'warn',
      note: 'benched or skipped — supply chain, no per-request API, or simply too thin' },
  ]));

  // ------------------------------------------------------------- controls ---
  const sel = el('select', {}, [
    el('option', { value: '', text: 'All verdicts' }),
    ...ph.groups.map((g) => el('option', { value: g.adoption, text: g.adoption })),
  ]);
  const tenetSel = el('select', {}, [
    el('option', { value: '', text: 'All tenets' }),
    ...[...new Set(inv.rails.map((r) => r.tenet))].sort().map((t) => el('option', { value: t, text: t })),
  ]);
  const tableSlot = el('div');

  const controls = el('div', { class: 'filters' }, [
    field('Adoption', sel),
    field('Serves tenet', tenetSel),
    el('p', { class: 'micro mute', style: 'max-width:36ch;align-self:center', text:
      'Filtering never repaints a repo’s other facts — the verdict and what cites it '
      + 'belong to the repository, not to the current filter.' }),
  ]);
  sel.addEventListener('change', draw);
  tenetSel.addEventListener('change', draw);

  root.append(rule('The 23 repositories', `${byRepo.size} in the review`));
  root.append(controls, tableSlot);
  draw();

  // ---------------------------------------------------------- the foreign ---
  if (foreign.size) {
    root.append(rule('Cited sources that are not one of the 23', String(foreign.size)));
    root.append(el('div', { class: 'card card__pad' }, [
      el('p', { class: 'small mute', style: 'max-width:80ch', text:
        'These strings appear as the source of a rail but are not repositories in the review: '
        + 'a hosted API, and rails AFNI composed itself from several vocabularies. They are '
        + 'kept out of the table above so the count of 23 stays the count of 23.' }),
      el('ul', { class: 'small', style: 'margin-top:var(--sp-4);display:grid;gap:var(--sp-3)' },
        [...foreign.entries()].map(([name, c]) => el('li', {}, [
          el('div', { class: 'repo__name', text: name }),
          el('div', { class: 'repo__flags', style: 'margin-top:.35rem' }, [
            ...[...c.stages].sort().map((s) => stageTag(s)),
            ...[...c.tenets].sort().map((t) => pill(t)),
          ]),
        ]))),
    ]));
  }

  function draw() {
    const wantAdoption = sel.value;
    const wantTenet = tenetSel.value;

    const rows = [...byRepo.values()]
      .filter((r) => !wantAdoption || r.adoption === wantAdoption)
      .map((r) => ({ r, c: contrib.get(r.repo) }))
      .filter(({ c }) => !wantTenet || (c && c.tenets.has(wantTenet)))
      .sort((a, b) => adoptionRank(a.r.adoption) - adoptionRank(b.r.adoption)
        || a.r.display.localeCompare(b.r.display));

    clear(tableSlot);
    if (!rows.length) {
      tableSlot.append(el('p', { class: 'empty', text: 'No repository matches both filters.' }));
      return;
    }

    const tbl = table(
      [{ label: 'Repository', width: '13rem' }, { label: 'Verdict', width: '9rem' },
        'Serves', 'Stages', 'Mechanism', 'In the build'],
      rows.map(({ r, c }) => el('tr', {}, [
        el('td', {}, [
          el('div', { style: 'font-weight:650', text: r.display }),
          el('div', { class: 'repo__slug', text: r.repo }),
          c ? el('div', { class: 'micro mute', text: plural(c.rails.length, 'rail') }) : null,
        ]),
        el('td', {}, [
          adoptionTag(r.adoption),
          r.conditional ? el('div', { style: 'margin-top:.25rem' }, pill('conditional', 'tag--conditional')) : null,
        ]),
        el('td', {}, c
          ? el('div', { class: 'repo__flags' }, [...c.tenets].sort().map((t) => {
              const tag = pill(shortTenet(t));
              tag.title = t;
              return tag;
            }))
          : el('span', { class: 'mute micro', text: 'no rail cites it' })),
        el('td', { class: 't-nowrap' }, c
          ? el('div', { class: 'repo__flags' }, [...c.stages].sort().map((s) => stageTag(s)))
          : el('span', { class: 'mute micro', text: '—' })),
        el('td', { class: 't-mono' }, c ? [...c.mechs].sort().join(', ') : '—'),
        el('td', {}, [
          r.present_in_platform
            ? pill('contributing', 'tag--present')
            : pill('nothing cites it', 'tag--absent'),
          ...r.implemented_as.map((s) => el('div', { style: 'margin-top:.25rem' },
            covChip(s, null, { short: true }))),
          c && c.dead
            ? el('div', { style: 'margin-top:.35rem' },
                el('span', { class: 'cannotrun', text: `${c.dead} rail${c.dead === 1 ? '' : 's'} down` }))
            : null,
          r.present_in_platform && (r.adoption === 'Skip' || r.adoption === 'Bench for later')
            ? el('div', { class: 'micro', style: 'margin-top:.35rem;color:var(--hazard-ink)',
                text: 'pattern ported — not adopted' })
            : null,
        ]),
      ])),
    );
    tbl.querySelector('table').classList.add('fw');
    tableSlot.append(tbl);

    tableSlot.append(el('p', { class: 'micro mute', style: 'margin-top:var(--sp-3);max-width:82ch', text:
      `${rows.length} of ${byRepo.size} repositories shown. A verdict is about the `
      + 'repository and carries no cascade stage — an adopted repository routinely backs '
      + 'a Stage-3 rail. “Contributing” means a rail cites the repo as the source of a '
      + 'pattern: provenance, not adoption, and not a dependency.' }));
  }
}
