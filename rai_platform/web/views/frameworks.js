// Frameworks — all 23 repositories, joined to the tenets they actually serve.
//
// The join is client-side and worth stating: /v1/phases gives the repo list and
// its adoption verdict, /v1/rails gives each rail's attribution. A rail's
// `repo` can name more than one source ("hai-guardrails-main + garak-main"),
// so it is split on " + " before matching — otherwise a compound attribution
// silently credits nothing.
//
// Two source strings in /v1/rails are not repositories at all: a cloud service
// and AFNI's own composed rails. They are shown in a separate block rather than
// quietly folded into the 23, because a hosted API is not a framework we vendored.

import { el, clear, pageHead, rule, table, stageTag, covChip, errorBox, pill, field } from '../ui.js';
import { phases, rails } from '../api.js';

// Phase 1 -> 2 -> 3 -> not adopted. Alphabetical sorting puts "Not adopted"
// first, which reads as though the skipped repos led the roadmap.
const phaseRank = (name) => {
  const m = /phase\s*([123])/i.exec(name);
  return m ? Number(m[1]) : 9;
};

const splitRepos = (s) => String(s || '').split('+').map((x) => x.trim()).filter(Boolean);

export async function render(root) {
  clear(root);
  root.append(pageHead(
    'Frameworks',
    'Twenty-three repositories, and what each one actually contributes',
    'One row per repository: the tenets its patterns serve, the cascade stages those '
    + 'rails sit in, the mechanism, and the roadmap verdict.',
  ));

  const loading = el('p', { class: 'empty', text: 'Reading /v1/phases and /v1/rails…' });
  root.append(loading);

  let ph; let rl;
  try { [ph, rl] = await Promise.all([phases(), rails()]); } catch (err) {
    loading.replaceWith(errorBox('Loading the framework table', err)); return;
  }
  loading.remove();

  // repo slug -> { entry, phase }
  const byRepo = new Map();
  for (const p of ph.phases) for (const r of p.repos) byRepo.set(r.repo, { ...r, phase: p.phase });

  // repo slug -> contributions
  const contrib = new Map();
  const foreign = new Map();
  for (const rail of rl.rails) {
    const parts = splitRepos(rail.repo);
    if (!parts.length) continue;
    for (const part of parts) {
      const bucket = byRepo.has(part) ? contrib : foreign;
      if (!bucket.has(part)) bucket.set(part, { tenets: new Set(), stages: new Set(), mechs: new Set(), rails: [] });
      const c = bucket.get(part);
      c.tenets.add(rail.tenet);
      c.stages.add(rail.stage);
      if (rail.mechanism) c.mechs.add(rail.mechanism.split(' - ')[0].split(' -')[0].trim());
      c.rails.push(rail);
    }
  }

  // ------------------------------------------------------------- controls ---
  const sel = el('select', {}, [
    el('option', { value: '', text: 'All phases' }),
    ...ph.phases.map((p) => el('option', { value: p.phase, text: p.phase })),
  ]);
  const tenetSel = el('select', {}, [
    el('option', { value: '', text: 'All tenets' }),
    ...[...new Set(rl.rails.map((r) => r.tenet))].sort().map((t) => el('option', { value: t, text: t })),
  ]);
  const tableSlot = el('div');

  const controls = el('div', { class: 'filters' }, [
    field('Phase', sel),
    field('Serves tenet', tenetSel),
    el('p', { class: 'micro mute', style: 'max-width:34ch', text:
      'Filtering never repaints a repo’s other facts — the phase tag and adoption '
      + 'verdict belong to the repo, not to the current filter.' }),
  ]);
  sel.addEventListener('change', draw);
  tenetSel.addEventListener('change', draw);

  root.append(rule('The 23 repositories', `${byRepo.size} in the roadmap`));
  root.append(controls, tableSlot);
  draw();

  // ---------------------------------------------------------- the foreign ---
  if (foreign.size) {
    root.append(rule('Cited sources that are not one of the 23', `${foreign.size}`));
    root.append(el('div', { class: 'card card__pad' }, [
      el('p', { class: 'small mute', style: 'max-width:78ch', text:
        'These strings appear as the source of a rail but are not repositories in the '
        + 'roadmap: a hosted API, and rails AFNI composed itself from several sources. '
        + 'They are kept out of the table above so the count of 23 stays the count of 23.' }),
      el('ul', { class: 'small', style: 'margin-top:1rem;display:grid;gap:.75rem' },
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
    const wantPhase = sel.value;
    const wantTenet = tenetSel.value;

    const rows = [...byRepo.values()]
      .filter((r) => !wantPhase || r.phase === wantPhase)
      .map((r) => ({ r, c: contrib.get(r.repo) }))
      .filter(({ c }) => !wantTenet || (c && c.tenets.has(wantTenet)))
      .sort((a, b) => phaseRank(a.r.phase) - phaseRank(b.r.phase)
        || a.r.display.localeCompare(b.r.display));

    clear(tableSlot);
    if (!rows.length) {
      tableSlot.append(el('p', { class: 'empty', text: 'No repository matches both filters.' }));
      return;
    }

    tableSlot.append(table(
      ['Repository', 'Phase', 'Adoption', 'Serves', 'Stages', 'Mechanism', 'In platform'],
      rows.map(({ r, c }) => el('tr', {}, [
        el('td', {}, [
          el('div', { style: 'font-weight:600', text: r.display }),
          el('div', { class: 'repo__slug', text: r.repo }),
        ]),
        el('td', { class: 't-nowrap' }, phaseTag(r.phase)),
        el('td', {}, [
          pill(r.adoption, adoptionClass(r.adoption)),
          r.conditional ? el('div', { style: 'margin-top:.25rem' }, pill('conditional', 'tag--conditional')) : null,
        ]),
        el('td', {}, c
          ? el('div', { class: 'repo__flags' }, [...c.tenets].sort().map((t) => pill(t)))
          : el('span', { class: 'mute micro', text: 'no rail cites it' })),
        el('td', { class: 't-nowrap' }, c
          ? el('div', { class: 'repo__flags' }, [...c.stages].sort().map((s) => stageTag(s)))
          : el('span', { class: 'mute micro', text: '—' })),
        el('td', { class: 't-mono' }, c ? [...c.mechs].sort().join(', ') : '—'),
        el('td', {}, [
          r.present_in_platform
            ? pill('present', 'tag--present')
            : pill('absent', 'tag--absent'),
          ...r.implemented_as.map((s) => el('div', { style: 'margin-top:.25rem' }, covChip(s))),
          r.present_in_platform && (r.adoption === 'Skip' || r.adoption === 'Bench for later')
            ? el('div', { class: 'micro', style: 'margin-top:.35rem;color:var(--hazard-ink)',
                text: 'pattern ported — not adopted' })
            : null,
        ]),
      ])),
    ));

    tableSlot.append(el('p', { class: 'micro mute', style: 'margin-top:.75rem;max-width:80ch', text:
      `${rows.length} of ${byRepo.size} repositories shown. “Present” means a rail cites the `
      + 'repo as the source of a pattern. It is provenance, not adoption, and not a dependency.' }));
  }
}

function phaseTag(phase) {
  const m = /phase\s*([123])/i.exec(phase);
  const cls = m ? `p${m[1]}` : 'none';
  return el('span', { class: `phase phase--${cls}` },
    el('span', { class: 'phase__tag', text: m ? `phase ${m[1]}` : 'not adopted' }));
}

function adoptionClass(a) {
  return {
    'Adopt now': 'tag--adopt',
    'Combine with another': 'tag--combine',
    'Bench for later': 'tag--bench',
    Skip: 'tag--skip',
  }[a] || '';
}
