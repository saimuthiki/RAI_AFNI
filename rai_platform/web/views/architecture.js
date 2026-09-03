// How it works — the request path, drawn.
//
// This view exists because the platform's two hardest ideas are both spatial and
// neither survives prose:
//
//   * the gateway is on BOTH sides of the model, and
//   * a stage runs only when the stage before it asked for it.
//
// Every number in the diagram is read from the running gateway — the stage rail
// counts, how many of them cannot judge on this host, the offline tier size. A
// static architecture picture goes stale the first time a rail moves stage; this
// one cannot, because it has no numbers of its own.

import {
  el, svg, clear, pageHead, rule, stageMeta, stageTag, adoptionTag, errorBox,
  statRow, plural, STAGES, judgeChain } from '../ui.js';
import { railsWithHealth, coverage, health } from '../api.js';

export async function render(root) {
  clear(root);
  root.append(pageHead(
    'How it works',
    'One gateway, two guardrails, three tiers you only pay for on demand',
    'Nothing on this page is drawn from a diagram file. The rail counts, the rails '
    + 'that cannot judge on this host, and the size of the offline tier are all read '
    + 'from the gateway that is answering right now.',
  ));

  const loading = el('p', { class: 'empty', text: 'Reading /v1/rails and /v1/coverage…' });
  root.append(loading);

  let inv; let cov;
  try {
    [inv, cov] = await Promise.all([railsWithHealth(), coverage()]);
  } catch (err) {
    loading.replaceWith(errorBox('Loading the architecture', err));
    return;
  }
  loading.remove();

  const h = health();
  const perStage = (n) => {
    const list = inv.byStage.get(n) || [];
    return { total: list.length, dead: list.filter((r) => r.available === false).length, list };
  };
  const s1 = perStage(1); const s2 = perStage(2); const s3 = perStage(3);
  const offlineCaps = cov.tenets.reduce((sum, t) => sum + (t.counts['offline-only'] || 0), 0);
  const gaps = cov.tenets.reduce((sum, t) => sum + (t.counts.gap || 0), 0);

  root.append(el('nav', { class: 'jump', 'aria-label': 'On this page' }, [
    el('a', { href: '#arch-directions', text: 'the two directions' }),
    el('a', { href: '#arch-cascade', text: 'the cascade engine' }),
    el('a', { href: '#arch-rules', text: 'the two rules that never bend' }),
    el('a', { href: '#arch-axes', text: 'a verdict is not a stage' }),
  ]));

  root.append(statRow([
    { label: 'Rails mounted', value: String(inv.rails.length),
      note: `${s1.total} at stage 1, ${s2.total} at stage 2, ${s3.total} at stage 3` },
    { label: 'Run on all traffic', value: String(s1.total),
      tone: 'good', note: 'stage 1 — free, sub-millisecond, zero third-party dependencies' },
    { label: 'Cannot judge here', value: String(inv.deadCount),
      tone: inv.deadCount ? 'hazard' : 'good',
      note: inv.deadCount
        ? 'mounted, invoked, and returning “could not judge” — fails closed without protecting'
        : 'every mounted rail can run on this host' },
    { label: 'Offline capabilities', value: String(offlineCaps),
      note: 'CI and red-team only. The engine refuses to mount these in a request path' },
    { label: 'Uncovered capabilities', value: String(gaps),
      tone: gaps ? 'warn' : 'good',
      note: gaps ? 'nothing looks at these at all — see Tenets' : 'no capability is unclaimed' },
  ]));

  // ------------------------------------------------------- the two lanes ----
  root.append(rule('The two directions', 'both are the same service'));
  root.append(el('p', { id: 'arch-directions', class: 'small mute', style: 'max-width:80ch;margin-bottom:var(--sp-4)' }, [
    el('span', { text: 'An application calls the gateway twice per turn: once with the '
      + 'prompt before spending a token on it, and once with the response before a person '
      + 'is allowed to read it. Both calls are ' }),
    el('code', { class: 'num', text: 'POST /v1/guard' }),
    el('span', { text: '; only the envelope’s ' }),
    el('code', { class: 'num', text: 'kind' }),
    el('span', { text: ' differs. Guarding one side and not the other is the most common way '
      + 'to deploy this wrong: a model that was never given a secret can still invent one, '
      + 'and a model that was given a clean prompt can still return a customer’s data.' }),
  ]));
  root.append(directionFigure());

  root.append(el('div', { class: 'axes', style: 'margin-top:var(--sp-4)' }, [
    el('div', { class: 'axis' }, [
      el('p', { class: 'axis__q', text: 'The direction gate' }),
      el('p', { class: 'axis__t', text: 'A rail declares which way it faces' }),
      el('p', { class: 'axis__say', text:
        'INPUT, OUTPUT, or BOTH. The engine skips the rails that do not apply, and BOTH is the '
        + 'default — narrowing a rail removes protection, so an absent declaration must never '
        + 'silently drop a check.' }),
      el('p', { class: 'small mute', text:
        'Two whole tenets are output-side only, and that is a fact about the world rather than a '
        + 'gap: Explainability validates a model’s output against the caller’s contract, and a '
        + 'prompt has no such contract. Hallucination is a property of a generated answer — a '
        + 'user cannot invent an import or refuse. Every PII, secret and toxicity rail stays '
        + 'BOTH: an SSN leaving the model is worse than one arriving.' }),
    ]),
    el('div', { class: 'axis' }, [
      el('p', { class: 'axis__q', text: 'Why it matters more than it sounds' }),
      el('p', { class: 'axis__t', text: 'Skipped is not unjudged' }),
      el('p', { class: 'axis__say', text:
        'A rail that does not apply has not failed to look — there was nothing for it to look at. '
        + 'So it is recorded as skipped, and skipped can never feed the fail-closed rule.' }),
      el('p', { class: 'small mute', text:
        'Had a direction mismatch fed the unjudged list instead, every client-facing request would '
        + 'have blocked on the output-side rails: a total outage dressed up as caution. Run a '
        + 'prompt and then a response in the live view and watch the rail counts move — the split '
        + 'is observed there per request, not asserted here.' }),
    ]),
  ]));

  // -------------------------------------------------------- the cascade ----
  root.append(rule('The cascade engine', 'afni_rai/cascade/engine.py'));
  root.append(el('div', { id: 'arch-cascade' }, cascadeFigure({ s1, s2, s3, offlineCaps })));

  // ----------------------------------------------------------- the rules ---
  root.append(rule('The two rules that never bend', 'in the engine, not in the rails'));
  root.append(el('div', { id: 'arch-rules', class: 'axes' }, [
    el('div', { class: 'axis' }, [
      el('p', { class: 'axis__q', text: 'Rule one' }),
      el('p', { class: 'axis__t', text: 'Fail closed' }),
      el('p', { class: 'axis__say', text:
        'Anything that could not be fully judged is blocked. Unconditionally — there is '
        + 'no request field and no switch on any of these screens that relaxes it.' }),
      el('p', { class: 'small mute', text:
        'This is not caution for its own sake. NeMo Guardrails — mature, NVIDIA-maintained — '
        + 'ships a jailbreak rail that defaults to fail-open. If a rail author can ship that, '
        + 'the decision cannot live with rail authors. There are dozens of rails and one engine.' }),
    ]),
    el('div', { class: 'axis' }, [
      el('p', { class: 'axis__q', text: 'Rule two' }),
      el('p', { class: 'axis__t', text: 'Fail loud' }),
      el('p', { class: 'axis__say', text:
        'A rail that could not run adds its payload path to the unjudged list. It never '
        + 'reads as clean.' }),
      el('p', { class: 'small mute', text:
        'The Infosys toolkit’s dispatcher wraps each check in a broad try/except returning '
        + 'None — one timeout silently drops a check and the summary still says pass. That is '
        + 'the exact failure a governance layer exists to prevent, so a raising rail here '
        + 'becomes “could not judge”.' }),
    ]),
  ]));

  root.append(el('p', { class: 'notcomparable', style: 'margin-top:var(--sp-4)' }, [
    el('b', { text: '“Could not judge” outranks any finding. ' }),
    el('span', { text: 'A finding means something looked and had an opinion. An unjudged path '
      + 'means nothing looked at all, so no claim about that content exists in either '
      + 'direction. That is why the live view puts the coverage gap above the verdict.' }),
  ]));

  // --------------------------------------------------- verdict vs stage ---
  root.append(rule('A verdict is not a stage', 'two axes, no relationship'));
  root.append(el('div', { id: 'arch-axes' }, axesFigure()));

  if (h) {
    root.append(rule('This host, right now', h.status || 'unknown'));
    root.append(el('section', { class: 'card card__pad stack stack--tight' }, [
      el('p', { class: 'small', style: 'max-width:80ch', text: inv.deadCount
        ? `${plural(inv.deadCount, 'mounted rail')} cannot run here. They stay mounted on `
          + 'purpose: a rail that vanished when its weights were missing would let the '
          + 'gateway read as fully armed. Instead they run, return “could not judge”, and '
          + 'fail closed — visibly.'
        : 'Every mounted rail can run on this host. The cascade is at full strength.' }),
      el('div', { class: 'ledger' }, [1, 2, 3].map((n) => {
        const p = perStage(n);
        const m = stageMeta(n);
        // No strike-through here: this ledger reports health, not spend, and a
        // struck "0 of 3 can judge" reads as though the sentence were cancelled.
        return el('div', { class: 'lcell', data: { paid: 'yes' } }, [
          el('div', { class: 'lcell__top' }, [stageTag(n),
            el('span', { class: 'lcell__verdict', text: p.dead ? `${p.dead} down` : 'all up' })]),
          el('p', { class: 'lcell__what',
            style: p.dead === p.total && p.total ? 'color:var(--hazard-ink)' : null,
            text: `${p.total - p.dead} of ${p.total} rails can judge` }),
          el('p', { class: 'lcell__cost', text: `${m.cost} · ${m.latency}` }),
        ]);
      })),
      inv.deadCount ? el('ul', { class: 'chipwrap' },
        inv.rails.filter((r) => r.available === false).map((r) => el('li', {
          class: 'railchip railchip--dead', text: r.name,
          title: r.unavailable_reason || 'reported unavailable',
        }))) : null,
      el('p', { class: 'micro mute', text: `judge provider: ${judgeChain(h.judge_provider)}`
        + `  ·  reveal_subject: ${h.reveal_subject ? 'ON — matched values are echoed' : 'off — fingerprints only'}`
        + `  ·  protocol ${h.protocol_version || '?'}` }),
    ]));
  }
}

/* ==========================================================================
   FIGURE 1 — the two directions, in the same HTML vocabulary as the live rig
   ========================================================================== */

const flowNode = (eyebrow, name, say, cls = '') => el('div', { class: `node ${cls}`.trim() }, [
  el('p', { class: 'node__eyebrow', text: eyebrow }),
  el('p', { class: 'node__name', text: name }),
  say ? el('p', { class: 'node__say', text: say }) : null,
]);

const flowLink = (label, flow = 'live') => el('div', { class: 'link', data: { flow } }, [
  el('span', { class: 'link__line', 'aria-hidden': 'true' }),
  el('span', { class: 'link__lab', text: label }),
]);

function directionFigure() {
  const guard = (which) => el('div', { class: 'guard', 'aria-hidden': 'false', style: 'cursor:default' }, [
    el('p', { class: 'node__eyebrow', text: which === 'in' ? 'Input guardrail' : 'Output guardrail' }),
    el('p', { class: 'node__name', text: which === 'in' ? 'Judge the prompt' : 'Judge the response' }),
    el('p', { class: 'node__say', text: which === 'in'
      ? 'runs before your app spends a token'
      : 'runs before a person reads a word' }),
    el('p', { class: 'guard__ep', text: which === 'in'
      ? 'kind = step/request' : 'kind = step/response' }),
    el('p', { class: 'guard__ep', text: 'the same 32 rails, the same cascade' }),
  ]);

  return el('section', { class: 'rig', role: 'img',
    'aria-label': 'Caller to input guardrail to the model to output guardrail to the person. '
      + 'Both guardrails are the same gateway, called twice.' }, [
    flowNode('Caller', 'Your AFNI app', 'chatbot, agent, summariser', 'node--end'),
    flowLink('prompt'),
    guard('in'),
    flowLink('cleared prompt'),
    flowNode('AI system', 'The model', 'unguarded on its own', 'node--model'),
    flowLink('raw response'),
    guard('out'),
    flowLink('cleared answer'),
    flowNode('Person', 'Your customer', 'sees only what cleared', 'node--end'),
    el('p', { class: 'rig__foot' }, [
      el('span', {}, [el('b', { text: 'Neither box trusts the other. ' }),
        'A prompt that cleared the way in says nothing about the response coming back, so '
        + 'the output call re-judges from scratch against the same cascade.']),
    ]),
  ]);
}

/* ==========================================================================
   FIGURE 2 — the cascade engine, as SVG
   Coordinates are fixed; the strings are not. Every count comes from the live
   gateway, and the boxes are sized to hold the longest of them.
   ========================================================================== */

/* --------------------------------------------------------------------------
   Geometry. SVG text does not wrap, so every string below is measured against
   the box that holds it: the mono face runs ~7.2px per character at 12px and
   ~6.6px at 11px, and the column is 560px wide with 16px gutters. Anything that
   would not fit was shortened rather than left to overlap — an architecture
   diagram whose labels collide is worse than a paragraph.
   -------------------------------------------------------------------------- */

const W = 1120;
const COLX = 290;                 // main column left edge
const COLW = 560;
const COLR = COLX + COLW;         // 850
const CX = COLX + COLW / 2;       // 570
const PAD = 16;
const BYPASS = 1060;              // the "no, we are done" rail down the right
const OFFX = 20;
const OFFW = 230;

function box(x, y, w, h, cls = '') {
  return svg('rect', { x, y, width: w, height: h, rx: 7, class: `d-box ${cls}`.trim() });
}
function txt(x, y, text, cls = 'd-body', anchor = 'start') {
  return svg('text', { x, y, class: cls, 'text-anchor': anchor, text });
}
function edge(points, cls = '') {
  return svg('polyline', { points, class: `d-edge ${cls}`.trim() });
}
/** Arrowheads as polygons, not markers: `context-stroke` is not universally
 *  supported, and a marker that ignores its line's colour is worse than none. */
function head(x, y, dir = 'down') {
  const s = 5.5;
  const pts = dir === 'down' ? `${x - s},${y - s * 1.7} ${x + s},${y - s * 1.7} ${x},${y}`
    : dir === 'left' ? `${x + s * 1.7},${y - s} ${x + s * 1.7},${y + s} ${x},${y}`
      : `${x - s * 1.7},${y - s} ${x - s * 1.7},${y + s} ${x},${y}`;
  return svg('polygon', { points: pts, class: 'd-head' });
}
/** A decision. A diamond wide enough to hold this much text stops being a
 *  diamond, so the question lives in a full-width bar with the lozenge as its
 *  bullet — and no text is ever left floating over a connector. */
function gateBar(y, question) {
  const h = 34;
  return svg('g', {}, [
    box(COLX, y, COLW, h, 'd-gate'),
    svg('polygon', {
      points: `${COLX + 26},${y + 7} ${COLX + 37},${y + 17} ${COLX + 26},${y + 27} ${COLX + 15},${y + 17}`,
      class: 'd-lozenge',
    }),
    txt(COLX + 46, y + 21, question, 'd-body'),
  ]);
}
function stageBar(y, n, count, dead) {
  const m = STAGES[n];
  const h = 66;
  const g = svg('g', {}, [
    box(COLX, y, COLW, h, `d-box--s${n}`),
    txt(COLX + PAD, y + 24, `STAGE ${n}`, `d-mono-big d-s${n}`),
    txt(COLX + 108, y + 24, `${count} rails`, 'd-body'),
    txt(COLR - PAD, y + 24, m.cost, 'd-lab', 'end'),
    txt(COLX + PAD, y + 43, m.mechanismLine, 'd-body'),
    txt(COLX + PAD, y + 59, m.runs, 'd-lab'),
  ]);
  if (dead) {
    g.append(txt(COLR - PAD, y + 59, `${dead} of ${count} cannot judge here`, 'd-lab d-haz', 'end'));
    g.append(svg('rect', { x: COLX, y: y + h - 4, width: COLW, height: 4, rx: 2, class: 'd-box--haz' }));
  }
  return g;
}

// One-line mechanism strings, measured to fit the column.
STAGES[1].mechanismLine = 'regex · checksums · lexicons · unicode · schema checks';
STAGES[2].mechanismLine = 'a locally-run classifier or NLI cross-encoder';
STAGES[3].mechanismLine = 'a cloud API or an LLM-as-judge';
STAGES[4].mechanismLine = 'red-team, fairness metrics, drift, SHAP';

function cascadeFigure({ s1, s2, s3, offlineCaps }) {
  const H = 830;
  const d = svg('svg', {
    class: 'diagram', viewBox: `0 0 ${W} ${H}`, role: 'img',
    'aria-label': 'The cascade. A request enters, stage 1 runs on everything, and stages 2 '
      + 'and 3 run only when the stage before them asked. Both "we are done" exits leave by '
      + 'a rail on the right, straight to the decision. An unjudged path on client-facing '
      + 'traffic fails closed. The offline tier sits outside the request path entirely, and '
      + 'the engine constructor refuses to mount one.',
  });

  // entry
  d.append(box(COLX, 8, COLW, 44));
  d.append(txt(COLX + PAD, 27, 'POST /v1/guard   ·   POST /v1/guard/stream'));
  d.append(txt(COLX + PAD, 43, 'a full GuardEvent — OpenGuardrails v0.8', 'd-lab'));

  d.append(edge(`${CX},52 ${CX},68`), head(CX, 74));
  d.append(box(COLX, 74, COLW, 44));
  d.append(txt(COLX + PAD, 93, 'Walk the payload for judgeable text'));
  d.append(txt(COLX + PAD, 109, 'transport metadata keys are skipped', 'd-lab'));

  // stage 1
  d.append(edge(`${CX},118 ${CX},134`), head(CX, 140));
  d.append(stageBar(140, 1, s1.total, s1.dead));

  // gate 1 -> bypass
  d.append(edge(`${CX},206 ${CX},222`), head(CX, 228));
  d.append(gateBar(228, 'a blocking finding, or did a rail ask for a second opinion?'));
  d.append(edge(`${COLR},245 ${BYPASS},245 ${BYPASS},538 ${COLR + 8},538`));
  d.append(txt(BYPASS - 10, 238, 'clean or blocked → done', 'd-lab', 'end'));

  // stage 2
  d.append(edge(`${CX},262 ${CX},278`), head(CX, 284));
  d.append(txt(CX + 12, 277, 'escalate', 'd-lab'));
  d.append(stageBar(284, 2, s2.total, s2.dead));

  d.append(edge(`${CX},350 ${CX},366`), head(CX, 372));
  d.append(gateBar(372, 'still borderline after a local model has looked?'));
  d.append(edge(`${COLR},389 ${BYPASS},389`));
  d.append(txt(BYPASS - 10, 382, 'decided → done', 'd-lab', 'end'));

  // stage 3
  d.append(edge(`${CX},406 ${CX},422`), head(CX, 428));
  d.append(txt(CX + 12, 421, 'escalate', 'd-lab'));
  d.append(stageBar(428, 3, s3.total, s3.dead));

  // decide
  d.append(edge(`${CX},494 ${CX},510`), head(CX, 516));
  d.append(box(COLX, 516, COLW, 44));
  d.append(txt(COLX + PAD, 535, 'Dedupe the findings, then decide'));
  d.append(txt(COLX + PAD, 551, 'only action:block findings are named as the cause', 'd-lab'));
  d.append(head(COLR + 6, 538, 'left'));

  // fail-closed gate
  d.append(edge(`${CX},560 ${CX},576`), head(CX, 582));
  d.append(gateBar(582, 'any payload path unjudged AND the traffic client-facing?'));

  const LX = COLX + 130; const RX = COLR - 130;
  d.append(edge(`${CX},616 ${CX},628 ${LX},628 ${LX},632`), head(LX, 638));
  d.append(edge(`${CX},616 ${CX},628 ${RX},628 ${RX},632`), head(RX, 638));
  d.append(txt(LX + 10, 625, 'yes', 'd-lab', 'end'));
  d.append(txt(RX - 10, 625, 'no', 'd-lab'));

  d.append(box(COLX, 638, 260, 48, 'd-box--haz'));
  d.append(txt(COLX + 12, 658, 'BLOCK — fail closed', 'd-body d-haz'));
  d.append(txt(COLX + 12, 675, 'it could not look, so it refuses', 'd-lab'));

  d.append(box(COLR - 260, 638, 260, 48));
  d.append(txt(COLR - 248, 658, 'allow, or block on a finding'));
  d.append(txt(COLR - 248, 675, 'something looked and had an opinion', 'd-lab'));

  // explanation + audit
  d.append(edge(`${LX},686 ${LX},700 ${CX},700`));
  d.append(edge(`${RX},686 ${RX},700 ${CX},700`));
  d.append(edge(`${CX},700 ${CX},710`), head(CX, 716));
  d.append(box(COLX, 716, COLW, 44));
  d.append(txt(COLX + PAD, 735, 'Attach the explanation'));
  d.append(txt(COLX + PAD, 751, 'which repo · confidence AND its kind · entity · payload path', 'd-lab'));

  d.append(edge(`${CX},760 ${CX},774`), head(CX, 780));
  d.append(box(COLX, 780, COLW, 30, 'd-box--deep'));
  d.append(txt(CX, 799, 'audit store — fingerprints only, never the matched value', 'd-lab', 'middle'));

  // the offline tier, outside everything
  d.append(box(OFFX, 140, OFFW, 190, 'd-box--off'));
  d.append(txt(OFFX + 16, 168, 'OFFLINE TIER', 'd-mono-big'));
  d.append(txt(OFFX + 16, 190, `${offlineCaps} capabilities`));
  d.append(txt(OFFX + 16, 210, 'garak · PyRIT · promptfoo', 'd-lab'));
  d.append(txt(OFFX + 16, 226, 'DeepEval · Fairlearn', 'd-lab'));
  d.append(txt(OFFX + 16, 242, 'AIF360 · SHAP', 'd-lab'));
  d.append(txt(OFFX + 16, 274, 'Cascade.__init__ RAISES'));
  d.append(txt(OFFX + 16, 294, 'if you mount one of these', 'd-lab'));
  d.append(txt(OFFX + 16, 310, 'in the request path.', 'd-lab'));
  // No arrowhead on this one, and a severed marker at its midpoint: the offline
  // tier is related to the cascade and connected to it by nothing at all.
  const mid = (OFFX + OFFW + COLX - 8) / 2;
  d.append(edge(`${OFFX + OFFW},173 ${COLX - 8},173`, 'd-edge--off'));
  d.append(svg('path', { d: `M${mid - 4},169 l8,8 M${mid + 4},169 l-8,8`, class: 'd-edge--off d-sever' }));

  return el('figure', { class: 'figure' }, [
    el('div', { class: 'figure__scroll', tabindex: '0', role: 'region',
      'aria-label': 'The cascade engine, scrollable' }, d),
    el('figcaption', {}, [
      el('b', { text: 'The two exits on the right are the product. ' }),
      el('span', { text: 'A clean stage 1 and a confident stage-1 block both leave by the '
        + 'same rail, straight to the decision — no local model, no paid judge, nothing '
        + 'billed. Running all three tiers on every request is not defence in depth; it is '
        + 'paying three times for one answer.' }),
    ]),
  ]);
}

/* ==========================================================================
   FIGURE 3 — the two axes that keep getting confused
   ========================================================================== */

function axesFigure() {
  return el('div', { class: 'axes' }, [
    el('div', { class: 'axis' }, [
      el('p', { class: 'axis__q', text: 'Asked of one request' }),
      el('p', { class: 'axis__t', text: 'Cascade stage' }),
      el('div', { class: 'axis__ex' }, [1, 2, 3].map((n) => stageTag(n))),
      el('p', { class: 'axis__say', text:
        'How much this one request cost to judge. Set by the rail, from the source data, '
        + 'and short-circuited the moment an answer is confident.' }),
      el('dl', {}, [
        el('div', {}, [el('dt', { text: 'unit' }), el('dd', { text: 'a rail' })]),
        el('div', {}, [el('dt', { text: 'axis' }), el('dd', { text: 'cost and latency' })]),
        el('div', {}, [el('dt', { text: 'changes' }), el('dd', { text: 'per request, live' })]),
        el('div', {}, [el('dt', { text: 'drawn as' }), el('dd', { text: 'a numbered chip, in the stage’s own hue' })]),
      ]),
    ]),
    el('div', { class: 'axis' }, [
      el('p', { class: 'axis__q', text: 'Asked of one repository' }),
      el('p', { class: 'axis__t', text: 'Adoption verdict' }),
      el('div', { class: 'axis__ex' },
        ['Adopt now', 'Combine with another', 'Bench for later', 'Skip']
          .map((a) => adoptionTag(a))),
      el('p', { class: 'axis__say', text:
        'Whether a reviewed repository is in the build, and on what terms. It says nothing '
        + 'about what any request pays, and an adopted repo can back a Stage-3 rail. There '
        + 'is deliberately no calendar on this axis: the platform is built in one pass, not '
        + 'in phases.' }),
      el('dl', {}, [
        el('div', {}, [el('dt', { text: 'unit' }), el('dd', { text: 'a repository' })]),
        el('div', {}, [el('dt', { text: 'axis' }), el('dd', { text: 'is it in the build' })]),
        el('div', {}, [el('dt', { text: 'changes' }), el('dd', { text: 'when the verdict does' })]),
        el('div', {}, [el('dt', { text: 'drawn as' }), el('dd', { text: 'a word, in ink — no stage hue at all' })]),
      ]),
    ]),
  ]);
}
