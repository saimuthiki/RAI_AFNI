// The gateway client.
//
// Two jobs beyond plain fetch:
//
//  1. NORMALISE. The gateway's JSON is authored on the Python side; the same
//     facts can arrive as `{tenets: {...}}`, `{by_tenet: {...}}` or a bare
//     tenet-keyed object, and a per-tenet block can be a row list, a counts map,
//     or both. Rather than guess one shape and render blank on the others, every
//     reader here accepts the plausible shapes and reduces them to one internal
//     form. Anything genuinely unrecognised raises, so the panel shows an error
//     instead of an empty state that reads as "all clear".
//
//  2. STAY HONEST ABOUT WHERE DATA CAME FROM. `state.source` is either 'gateway'
//     or 'fixtures', it is surfaced in the top bar and in a page-wide banner,
//     and the streaming view refuses to describe a fixture run as a judgement.

import { FIXTURES } from './demo-fixtures.js';

export const state = {
  base: '',            // same-origin by default: the gateway's own static mount
  source: 'unknown',   // 'gateway' | 'fixtures' | 'unknown'
  health: null,
};

const listeners = new Set();
export const onSourceChange = (fn) => { listeners.add(fn); return () => listeners.delete(fn); };
const announce = () => listeners.forEach((fn) => fn(state));

function setSource(source, detail = null) {
  if (state.source === source && state.health === detail) return;
  state.source = source;
  state.health = detail;
  announce();
}

/** The parsed /healthz body, or null when the gateway did not answer with one.
 *  Views read this rather than re-fetching: one probe, one truth. */
export const health = () =>
  (state.source === 'gateway' && state.health && typeof state.health === 'object')
    ? state.health : null;

/** /healthz reports rails that are mounted but cannot run, as strings shaped
 *  "rail.name: why". /v1/rails does NOT carry that fact — its `available` field
 *  is null for every rail — so without this join the console would render 32
 *  healthy-looking rails on a gateway that can only run 25. Parse it once here
 *  rather than in each view.
 *  -> Map<railName, reason> */
export function unavailableRails() {
  const h = health();
  const out = new Map();
  for (const line of [].concat(h?.rails_unavailable ?? [])) {
    const s = String(line);
    const cut = s.indexOf(':');
    if (cut === -1) { out.set(s.trim(), 'reported unavailable'); continue; }
    out.set(s.slice(0, cut).trim(), s.slice(cut + 1).trim());
  }
  return out;
}

/** Judge rails with no configured judge are a second, different failure: the
 *  rail can run, there is simply nothing to call. Kept separate from the map
 *  above so the console does not report one cause as the other. */
export const judgelessRails = () =>
  new Set([].concat(health()?.judge_rails_without_a_judge ?? []).map(String));

/** Query string wins, so the console can be pointed at a gateway on another
 *  port while being served by `python3 -m http.server`. */
export function readBaseFromLocation() {
  const p = new URLSearchParams(location.search);
  const api = p.get('api');
  if (api) state.base = api.replace(/\/$/, '');
  if (p.get('fixtures') === '1') setSource('fixtures', 'forced by ?fixtures=1');
  return state.base;
}

const url = (path) => `${state.base}${path}`;

async function getJSON(path, { timeout = 8000 } = {}) {
  const ctl = new AbortController();
  const timer = setTimeout(() => ctl.abort(), timeout);
  try {
    const res = await fetch(url(path), {
      headers: { accept: 'application/json' }, signal: ctl.signal,
    });
    if (!res.ok) throw new Error(`${path} → HTTP ${res.status} ${res.statusText}`);
    return await res.json();
  } finally {
    clearTimeout(timer);
  }
}

/** Probe /healthz once. Everything else keys off the answer. */
export async function probe() {
  if (new URLSearchParams(location.search).get('fixtures') === '1') {
    setSource('fixtures', 'forced by ?fixtures=1');
    return state;
  }
  try {
    const body = await getJSON('/healthz', { timeout: 4000 });
    setSource('gateway', body && typeof body === 'object' ? body : { ok: true });
  } catch (err) {
    setSource('fixtures', String(err.message || err));
  }
  return state;
}

/** Fetch, or fall back to the snapshot — and record which happened. */
async function fetchOrFixture(path, fixtureKey) {
  if (state.source !== 'fixtures') {
    try {
      return { data: await getJSON(path), live: true };
    } catch (err) {
      setSource('fixtures', `${path}: ${err.message || err}`);
    }
  }
  return { data: structuredClone(FIXTURES[fixtureKey]), live: false };
}

// -------------------------------------------------------------- normalising --

const COV_KEYS = ['implemented', 'dependency-missing', 'cloud-not-configured',
  'offline-only', 'gap'];

const zeroCounts = () => Object.fromEntries(COV_KEYS.map((k) => [k, 0]));

function unwrap(body, keys) {
  if (!body || typeof body !== 'object') throw new Error('response was not a JSON object');
  for (const k of keys) if (body[k] && typeof body[k] === 'object') return body[k];
  return body;
}

/** -> { tenets: [{ tenet, counts, total, capabilities }], totals, live }
 *
 *  The gateway's own shape is `{totals, tenets: [{tenet, counts, rows}]}`; the
 *  branches below also accept a tenet-keyed object and a bare row list, because
 *  a console that renders blank when a key is renamed is worse than one that
 *  reads two shapes.
 */
export async function coverage() {
  const { data, live } = await fetchOrFixture('/v1/coverage', 'coverage');
  const block = unwrap(data, ['tenets', 'by_tenet', 'coverage']);

  // Normalise both containers to [[name, block], ...].
  const pairs = Array.isArray(block)
    ? block.map((b) => [b.tenet ?? b.name ?? '(unnamed tenet)', b])
    : Object.entries(block);

  const tenets = [];
  for (const [tenet, raw] of pairs) {
    if (!raw || typeof raw !== 'object') continue;
    let rows = null;
    if (Array.isArray(raw)) rows = raw;
    else if (Array.isArray(raw.rows)) rows = raw.rows;
    else if (Array.isArray(raw.capabilities)) rows = raw.capabilities;

    let counts = null;
    const rawCounts = raw.counts && typeof raw.counts === 'object' ? raw.counts : null;
    if (rawCounts) {
      counts = zeroCounts();
      for (const k of COV_KEYS) counts[k] = Number(rawCounts[k] ?? rawCounts[k.replace(/-/g, '_')] ?? 0);
    } else if (!rows && COV_KEYS.some((k) => k in raw)) {
      counts = zeroCounts();
      for (const k of COV_KEYS) counts[k] = Number(raw[k] ?? 0);
    }

    const capabilities = (rows || []).map((r) => {
      const attr = r.attribution || r.attributed_to || null;
      return {
        name: r.capability ?? r.name ?? r.aspect ?? '(unnamed capability)',
        status: r.status ?? r.state ?? r.coverage ?? 'gap',
        note: r.note ?? r.reason ?? '',
        rail: attr?.rail ?? r.rail ?? null,
        repo: attr?.repo ?? attr?.source_repo ?? r.repo ?? null,
        tool: attr?.tool ?? attr?.display_name ?? null,
        stage: attr?.stage ?? r.stage ?? null,
      };
    });

    if (!counts) {
      counts = zeroCounts();
      for (const c of capabilities) if (c.status in counts) counts[c.status] += 1;
    }

    tenets.push({
      tenet, counts, capabilities,
      total: Object.values(counts).reduce((a, b) => a + b, 0),
    });
  }

  if (!tenets.length) throw new Error('/v1/coverage carried no tenets this console could read');
  return { tenets, totals: data?.totals ?? null, live };
}

/** -> [{ name, tenet, stage, repo, tool, mechanism, confidence_kind, evidence, capability }] */
export async function rails() {
  const { data, live } = await fetchOrFixture('/v1/rails', 'rails');
  const list = Array.isArray(data) ? data
    : Array.isArray(data?.rails) ? data.rails
    : Object.values(data || {}).find(Array.isArray);
  if (!Array.isArray(list)) throw new Error('/v1/rails did not carry a list of rails');

  return {
    live,
    rails: list.map((r) => {
      const a = r.attribution || r.attributed_to || {};
      return {
        name: r.name ?? r.rail ?? a.rail ?? '(unnamed rail)',
        tenet: r.tenet ?? a.tenet ?? 'unattributed',
        stage: Number(r.stage ?? a.stage ?? 0) || 0,
        repo: a.repo ?? a.source_repo ?? r.repo ?? null,
        tool: a.tool ?? a.display_name ?? r.tool ?? null,
        mechanism: a.mechanism ?? r.mechanism ?? null,
        confidence_kind: a.confidence_kind ?? r.confidence_kind ?? null,
        evidence: a.evidence ?? r.evidence ?? null,
        capability: a.capability ?? r.capability ?? null,
        stage_label: r.stage_label ?? null,
        // `available: null` means the gateway did not say. Only an explicit
        // false is treated as "cannot run" — absence of news is not good news,
        // but it is also not evidence of failure.
        available: r.available === undefined ? null : r.available,
        unavailable_reason: r.unavailable_reason ?? null,
      };
    }),
  };
}

/** rails() plus the /healthz verdict on each one, and the per-stage totals the
 *  live view needs to say "22 of 22 rails invoked" rather than just "22". */
export async function railsWithHealth() {
  const { rails: list, live } = await rails();
  const dead = unavailableRails();
  const judgeless = judgelessRails();
  const out = list.map((r) => {
    const why = dead.get(r.name) ?? null;
    return {
      ...r,
      available: why ? false : r.available,
      unavailable_reason: why ?? r.unavailable_reason,
      judgeless: judgeless.has(r.name),
    };
  });
  const byStage = new Map();
  for (const r of out) {
    if (!byStage.has(r.stage)) byStage.set(r.stage, []);
    byStage.get(r.stage).push(r);
  }
  return { rails: out, byStage, live, deadCount: out.filter((r) => r.available === false).length };
}

/** -> { groups: [{ adoption, repos: [...] }], unlinkable: [...] }
 *
 *  Replaced `phases()`, which read `/v1/phases` and grouped the same
 *  repositories by 90-day adoption window. The window is gone; the adoption
 *  verdict is the grouping. */
export async function repositories() {
  const { data, live } = await fetchOrFixture('/v1/repositories', 'repositories');
  const block = unwrap(data, ['repositories', 'inventory']) ?? data;
  const groups = [].concat(block.groups ?? []).map((g) => ({
    adoption: g.adoption ?? 'unknown',
    repos: [].concat(g.repos ?? []).map((r) => ({
      repo: r.repo ?? '',
      display: r.display ?? r.repo ?? '(unnamed)',
      adoption: r.adoption ?? g.adoption ?? 'unknown',
      conditional: Boolean(r.conditional),
      why: r.why ?? '',
      implemented_as: [].concat(r.implemented_as ?? []),
      present_in_platform: Boolean(r.present_in_platform),
    })),
  })).filter((g) => g.repos.length);
  if (!groups.length) {
    throw new Error('/v1/repositories carried no repositories this console could read');
  }
  return { groups, unlinkable: [].concat(block.unlinkable ?? []), live };
}

// ---------------------------------------------------------------- streaming --

/** Build a GuardEvent. Field names follow guard-event.schema.json exactly -
 *  the gateway sets `extra="forbid"`, so an extra key is a 422, not a shrug. */
export function buildEvent({ text, kind }) {
  const isResponse = kind === 'response';
  const stepId = `console-${Date.now().toString(36)}`;
  return {
    kind: isResponse ? 'step/response' : 'step/request',
    step_id: stepId,
    agent_id: 'rai-console',
    agent_type: 'operator-console',
    agent_workspace: 'console',
    agent_user: 'operator',
    llm_protocol: 'openai.chat',
    payload: isResponse
      ? { choices: [{ index: 0, message: { role: 'assistant', content: text } }] }
      : { messages: [{ role: 'user', content: text }] },
  };
}

/** Classify one SSE payload object without assuming a field name for the type. */
export function classify(obj) {
  const t = String(obj?.event ?? obj?.type ?? obj?.kind ?? '').toLowerCase();
  if (t.includes('done') || t === 'end' || t === 'complete') return 'done';
  if (t.includes('verdict') || obj?.verdict || obj?.explanation) return 'verdict';
  if (t.includes('stage') || obj?.stage !== undefined) return 'stage';
  if (t.includes('error') || obj?.error) return 'error';
  return 'unknown';
}

export function normalizeStage(obj) {
  const src = obj?.stage_trace ?? obj?.trace ?? obj;
  const stage = Number(src.stage ?? src.stage_number ?? obj.stage ?? 0) || 0;
  const railsRun = [].concat(src.rails_run ?? src.ran_rails ?? []);
  const railsSkipped = [].concat(src.rails_skipped ?? src.skipped ?? []);
  const unjudged = [].concat(src.unjudged ?? src.unjudged_paths ?? []);

  // The gateway sends `stage_findings` as the count and `findings` as the list
  // accumulated so far. Reading the list as a count would print NaN, and reading
  // it as this stage's own count would over-report every stage after the first.
  const findings = Number(
    src.stage_findings ?? src.finding_count
    ?? (Array.isArray(src.findings) ? src.findings.length : src.findings)
    ?? 0,
  ) || 0;

  return {
    stage,
    railsRun,
    railsSkipped,
    unjudged,
    findings,
    latency_ms: src.stage_latency_ms ?? src.latency_ms ?? null,
    elapsed_ms: src.elapsed_ms ?? null,
    short_circuited: Boolean(src.short_circuited ?? src.short_circuit),
    // Whether this stage asked for the next one. This is the escalation decision
    // itself, so it is worth showing rather than inferring from what ran next.
    will_escalate: src.will_escalate === undefined ? null : Boolean(src.will_escalate),
    // Prefer the gateway's own word for it; fall back to "did any rail run".
    ran: src.ran === undefined ? railsRun.length > 0 : Boolean(src.ran),
  };
}

export function normalizeVerdict(obj) {
  const verdict = obj?.verdict ?? obj?.result ?? {};
  const ex = obj?.explanation ?? verdict?.explanation ?? {};

  // The fingerprint lives on the wire verdict's findings, not on the
  // explanation's. Join them so the UI can show the fingerprint instead of
  // asking for the matched value — which it must never do. The key is the same
  // identity the engine dedupes on: category + path + span + detector.
  const fpByKey = new Map();
  for (const f of [].concat(verdict.findings ?? [])) {
    if (!f || !f.fp) continue;
    fpByKey.set(`${f.category}|${f.path}|${f.start}|${f.end}|${f.detector}`, f.fp);
  }
  const LOC = /^(.*?)\s+chars\s+(\d+)-(\d+)$/;

  const findings = (list) => [].concat(list ?? []).map((f) => {
    const m = f.location ? LOC.exec(f.location) : null;
    const rail = f.attributed_to?.rail ?? f.attribution?.rail ?? null;
    const key = m ? `${f.category}|${m[1]}|${m[2]}|${m[3]}|${rail}` : null;
    return {
      entity: f.entity ?? f.category ?? 'unknown',
      category: f.category ?? null,
      action: f.action ?? null,
      score: f.score ?? null,
      location: f.location ?? null,
      sentence: f.sentence ?? '',
      attr: f.attributed_to ?? f.attribution ?? null,
      fp: f.fp ?? (key ? fpByKey.get(key) ?? null : null),
    };
  });

  const blocked_by = findings(ex.blocked_by);
  const also_flagged = findings(ex.also_flagged);
  const could_not_judge = [].concat(ex.could_not_judge ?? verdict.unjudged ?? []);

  return {
    decision: ex.decision ?? verdict.decision ?? 'unknown',
    stages_run: ex.stages_run ?? null,
    latency_ms: ex.latency_ms ?? verdict.latency_ms ?? null,
    could_not_judge,
    blocked_by,
    also_flagged,
    modifications: verdict.modifications?.spans ?? verdict.modifications ?? [],
    event_id: verdict.event_id ?? null,
    provider: verdict.provider ?? null,
  };
}

/**
 * POST to /v1/guard/stream and hand each parsed `data:` object to `onEvent`.
 * EventSource cannot POST, so this reads the body stream directly.
 * Returns { live: true } when the gateway answered.
 */
// One SSE reader, shared by every streaming endpoint. Extracted rather than
// copied because the fiddly parts — CRLF-tolerant frame splitting, multi-line
// `data:` folding, the trailing partial frame after the reader closes — are
// exactly the parts that get subtly wrong in the second copy, and a stream that
// drops its last frame drops the verdict.
async function sseStream(path, body, onEvent, { signal, classify: kindOf } = {}) {
  const res = await fetch(url(path), {
    method: 'POST',
    headers: { 'content-type': 'application/json', accept: 'text/event-stream' },
    body: JSON.stringify(body),
    signal,
  });
  if (!res.ok) {
    // The gateway answers a rejected corpus selection with a JSON body that
    // explains itself (the sample cap, the empty filter). Surfacing "HTTP 422"
    // and throwing that away would leave the operator guessing at a number the
    // server already told us.
    let detail = `HTTP ${res.status} ${res.statusText}`;
    try {
      const err = await res.json();
      if (err && err.message) detail = err.message;
    } catch { /* not JSON — keep the status line */ }
    throw new Error(`${path} → ${detail}`);
  }
  if (!res.body) throw new Error(`${path} returned no readable body`);

  const reader = res.body.getReader();
  const dec = new TextDecoder();
  let buf = '';

  const flushFrame = (frame) => {
    const data = frame.split('\n')
      .filter((l) => l.startsWith('data:'))
      .map((l) => l.slice(5).trimStart())
      .join('\n');
    if (!data || data === '[DONE]') { if (data) onEvent('done', {}); return; }
    let obj;
    try { obj = JSON.parse(data); } catch { onEvent('error', { error: `unparseable SSE data: ${data.slice(0, 200)}` }); return; }
    onEvent(kindOf ? kindOf(obj) : String(obj.event || 'message'), obj);
  };

  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buf += dec.decode(value, { stream: true });
    let cut;
    // SSE frames are separated by a blank line; tolerate CRLF.
    while ((cut = buf.search(/\r?\n\r?\n/)) !== -1) {
      const frame = buf.slice(0, cut);
      buf = buf.slice(cut + buf.slice(cut).match(/^\r?\n\r?\n/)[0].length);
      if (frame.trim()) flushFrame(frame);
    }
  }
  if (buf.trim()) flushFrame(buf);
  return { live: true };
}

export async function guardStream(event, onEvent, { signal } = {}) {
  return sseStream('/v1/guard/stream', event, onEvent, { signal, classify });
}

// ------------------------------------------------------------------ corpus --
// The regression corpus is 11,369 records and a Stage-2 pass is 1-3 s each, so
// the sample size is a control, not a detail. `corpusSummary()` feeds the picker
// the counts needed to choose one — including the server's own cap, which the UI
// must not let anyone exceed only to be refused after they hit Run.

export const corpusSummary = () => getJSON('/v1/corpus', { timeout: 15000 });

/** Guardrails off vs on, on the same records.
 *
 *  Not streamed, unlike a corpus run, and the reason is that this is a LADDER:
 *  a partially-drawn ladder invites reading a Stage-2 rung that has not finished
 *  against a Stage-1 rung that has, which is a comparison of two different
 *  sample sizes. It arrives complete or not at all.
 *
 *  No timeout for the same reason `moderateMedia` has none: the ladder judges
 *  every record two or three times, so a 200-record Stage-2 comparison is
 *  minutes of held-open socket by design.
 */
export async function corpusCompare(body) {
  const res = await fetch(url('/v1/corpus/compare'), {
    method: 'POST',
    headers: { 'content-type': 'application/json', accept: 'application/json' },
    body: JSON.stringify(body),
  });
  let parsed = null;
  try { parsed = await res.json(); } catch { /* not JSON */ }
  if (!res.ok) {
    throw new Error(parsed && parsed.message
      ? parsed.message
      : `POST /v1/corpus/compare → HTTP ${res.status} ${res.statusText}`);
  }
  return parsed;
}

// ---------------------------------------------------------- topic policy --
// The topic catalogue plus this deployment's selection. The catalogue is
// compiled in; the selection lives in a JSON file on the server.

export const topicPolicy = () => getJSON('/v1/topics', { timeout: 10000 });

/** Save the optional topic selection.
 *
 *  The one WRITE this console makes. It reads the JSON error body on failure,
 *  because the useful part of a 422 here is the message - "cannot promote X to
 *  blocking without also enabling it" - and "HTTP 422" tells an operator
 *  nothing about which box to untick.
 */
export async function saveTopicPolicy({ enabled, blocking }) {
  const res = await fetch(url('/v1/topics'), {
    method: 'PUT',
    headers: { 'content-type': 'application/json', accept: 'application/json' },
    body: JSON.stringify({ enabled, blocking }),
  });
  let body = null;
  try { body = await res.json(); } catch { /* not JSON */ }
  if (!res.ok) {
    throw new Error(body && body.message
      ? body.message
      : `PUT /v1/topics → HTTP ${res.status} ${res.statusText}`);
  }
  return body;
}


// -------------------------------------------------------- sensitivity --
// Threshold overrides. Unlike the topic policy these apply on the NEXT REQUEST:
// ThresholdStore does not cache, on purpose. The screen says so, and does not
// show a restart warning it would be wrong to show.

export const thresholds = () => getJSON('/v1/thresholds', { timeout: 10000 });

/** Save overrides, or apply a preset.
 *
 *  `thresholds` REPLACES the saved map rather than merging into it — a merge
 *  would make "remove this override" impossible to express.
 */
export async function saveThresholds(body) {
  const res = await fetch(url('/v1/thresholds'), {
    method: 'PUT',
    headers: { 'content-type': 'application/json', accept: 'application/json' },
    body: JSON.stringify(body),
  });
  let parsed = null;
  try { parsed = await res.json(); } catch { /* not JSON */ }
  if (!res.ok) {
    throw new Error(parsed && parsed.message
      ? parsed.message
      : `PUT /v1/thresholds → HTTP ${res.status} ${res.statusText}`);
  }
  return parsed;
}


// -------------------------------------------------------------- media --
// Image and video moderation. Separate routes from /v1/guard because a
// GuardEvent payload is strings and an image is not one — so an application
// that accepts uploads has to call these as well. `mediaStatus()` is what tells
// the screen whether the model is even installed.

export const mediaStatus = () => getJSON('/v1/media', { timeout: 10000 });

/** Send one image (or video) for moderation.
 *
 *  Base64 in a JSON body rather than multipart, matching the gateway: FastAPI's
 *  UploadFile needs python-multipart, and media is meant to be an optional extra
 *  that adds no hard dependency for deployments that never send an image.
 *
 *  Deliberately NOT routed through `getJSON`'s timeout. A video frame costs
 *  ~87 ms, so a 120-frame sample is ten seconds of held-open socket before a
 *  byte comes back, and a timeout tuned for an introspection route would abort
 *  a run that was working perfectly. The screen shows a pending state instead.
 */
export async function moderateMedia(kind, base64, options = {}) {
  const route = kind === 'video' ? '/v1/media/video' : '/v1/media/image';
  const body = kind === 'video'
    ? { video_base64: base64, ...options }
    : { image_base64: base64, ...options };
  const res = await fetch(url(route), {
    method: 'POST',
    headers: { 'content-type': 'application/json', accept: 'application/json' },
    body: JSON.stringify(body),
  });
  let parsed = null;
  try { parsed = await res.json(); } catch { /* not JSON */ }
  if (!res.ok) {
    // The useful part of a 422 here is the message — "image_base64 is not valid
    // base64" — and "HTTP 422" tells an operator nothing about what to fix.
    throw new Error(parsed && parsed.message
      ? parsed.message
      : `POST ${route} → HTTP ${res.status} ${res.statusText}`);
  }
  return parsed;
}


/** Run a sample, one callback per record as it is judged.
 *
 *  Streamed rather than awaited because a 200-record Stage-2 run is ten minutes.
 *  A fetch that returns nothing for ten minutes is indistinguishable from a hung
 *  gateway, and an operator watching an empty panel reloads the page — which
 *  abandons the run and wastes the ten minutes.
 */
export async function corpusRunStream(request, onEvent, { signal } = {}) {
  return sseStream('/v1/corpus/run/stream', request, onEvent, { signal });
}

/** Replay a fixture run with the same event sequence and rough timing, so the
 *  rendering path is exercised end to end. Never labelled a judgement. */
export async function guardStreamFixture(event, onEvent, { signal } = {}) {
  const script = FIXTURES.streams[pickScript(event)];
  for (const step of script) {
    if (signal?.aborted) throw new DOMException('aborted', 'AbortError');
    await new Promise((r) => setTimeout(r, step.after));
    onEvent(step.event, step.data);
  }
  return { live: false };
}

function pickScript(event) {
  const text = JSON.stringify(event.payload || '').toLowerCase();
  if (/\d{3}-?\d{2}-?\d{4}|ssn|sk-[a-z0-9]/.test(text)) return 'block_stage1';
  if (/ignore (all )?(previous|prior)|jailbreak|dan mode|system prompt/.test(text)) return 'escalate';
  return 'clean_unjudged';
}
