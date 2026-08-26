// Boot, routing, and the two pieces of global honesty: the connection pill and
// the fixtures banner. Both exist so nobody can mistake a replay for a
// judgement, or a stale panel for a live one.

import { probe, readBaseFromLocation, state, onSourceChange } from './api.js';
import { el, clear } from './ui.js';

import * as live from './views/live.js';
import * as architecture from './views/architecture.js';
import * as tenets from './views/tenets.js';
import * as rails from './views/rails.js';
import * as roadmap from './views/roadmap.js';
import * as frameworks from './views/frameworks.js';

const VIEWS = { live, architecture, tenets, rails, roadmap, frameworks };
// The route name is a URL slug; the tab title is prose. "Architecture" is the
// slug, "How it works" is what the nav calls it, and the two should agree.
const TITLES = {
  live: 'Live check', architecture: 'How it works', tenets: 'Tenets',
  rails: 'Rails', roadmap: 'Roadmap', frameworks: 'Frameworks',
};
const DEFAULT = 'live';

const view = document.getElementById('view');
const nav = document.querySelectorAll('.nav__item');
const conn = document.getElementById('conn');
const banner = document.getElementById('fixture-banner');
const why = document.getElementById('fixture-why');
const healthBox = document.getElementById('health');

// ------------------------------------------------------------------- theme --
// prefers-color-scheme is respected in both directions; the toggle only sets an
// explicit override, and "system" clears it again.

const THEME_KEY = 'afni-rai-theme';
const themeBtn = document.getElementById('theme');
const themeLabel = document.getElementById('theme-label');
const CYCLE = ['system', 'dark', 'light'];

function applyTheme(mode) {
  if (mode === 'system') document.documentElement.removeAttribute('data-theme');
  else document.documentElement.setAttribute('data-theme', mode);
  themeLabel.textContent = `Theme: ${mode}`;
  themeBtn.setAttribute('aria-pressed', String(mode !== 'system'));
  try { localStorage.setItem(THEME_KEY, mode); } catch { /* private window */ }
}

let theme = 'system';
try { theme = localStorage.getItem(THEME_KEY) || 'system'; } catch { /* private window */ }
if (!CYCLE.includes(theme)) theme = 'system';
applyTheme(theme);

themeBtn.addEventListener('click', () => {
  theme = CYCLE[(CYCLE.indexOf(theme) + 1) % CYCLE.length];
  applyTheme(theme);
});

// -------------------------------------------------------------- connection --

function paintConnection() {
  const live_ = state.source === 'gateway';
  const label = conn.querySelector('.conn__text');
  const status = live_ && state.health && typeof state.health === 'object'
    ? String(state.health.status || '') : '';
  const degraded = status && status.toLowerCase() !== 'ok' && status.toLowerCase() !== 'healthy';
  conn.className = `conn conn--${live_ ? (degraded ? 'degraded' : 'live')
    : state.source === 'fixtures' ? 'fixtures' : 'unknown'}`;
  label.textContent = live_
    ? `Gateway live${degraded ? ` · ${status}` : ''}${state.base ? ` · ${state.base}` : ''}`
    : state.source === 'fixtures' ? 'Demo fixtures — gateway not answering'
      : 'Checking gateway…';

  banner.hidden = state.source !== 'fixtures';
  if (state.source === 'fixtures') {
    why.textContent = 'The gateway is not answering, so every panel is drawn from a static '
      + 'snapshot of the capability registry and the live check replays a scripted run. '
      + 'Nothing here is a judgement of anything you type.'
      + (state.health ? ` (${state.health})` : '');
  }
}

document.getElementById('retry').addEventListener('click', async () => {
  const url = new URL(location.href);
  url.searchParams.delete('fixtures');
  if (url.href !== location.href) { location.href = url.href; return; }
  state.source = 'unknown';
  paintConnection();
  await probe();
  paintConnection();
  paintHealth();
  route();
});

// ------------------------------------------------------------------ health --
// /healthz reports rails that are mounted but cannot run. A console that showed
// "gateway live" and stopped there would be describing a gateway that is only
// partly defending anything.

const LIST_LABELS = {
  rails_unavailable: 'rails mounted but unable to run',
  judge_rails_without_a_judge: 'judge rails with no judge configured',
  tenets_not_loaded: 'tenets that failed to load',
};

function paintHealth() {
  const h = state.source === 'gateway' && state.health && typeof state.health === 'object'
    ? state.health : null;
  if (!h) { healthBox.hidden = true; clear(healthBox); return; }

  const lists = Object.entries(LIST_LABELS)
    .map(([key, label]) => [label, [].concat(h[key] ?? [])])
    .filter(([, items]) => items.length);
  const absent = [].concat(h.dependencies_absent ?? []).filter((d) => d && d.present === false);
  const degraded = String(h.status || '').toLowerCase() !== 'ok'
    && String(h.status || '').toLowerCase() !== 'healthy';

  if (!degraded && !lists.length && !absent.length) { healthBox.hidden = true; clear(healthBox); return; }

  const mounted = h.rails_mounted ?? null;
  const cannotRun = [].concat(h.rails_unavailable ?? []).length;

  clear(healthBox).append(
    el('div', { class: 'health__top' }, [
      el('span', { class: 'health__word', text: h.status || 'degraded' }),
      el('span', {}, [
        el('strong', { text: cannotRun
          ? `${cannotRun} of ${mounted ?? '?'} mounted rails cannot judge on this host. `
          : 'The gateway reports itself degraded. ' }),
        el('span', { class: 'mute', text:
          'They stay mounted, run, and return “could not judge” — which fails closed without '
          + 'protecting anything.' }),
      ]),
      el('span', { class: 'health__cfg mute',
        text: `judge provider: ${h.judge_provider || 'none'} · reveal_subject: ${h.reveal_subject ? 'ON' : 'off'}` }),
    ]),
    el('details', {}, [
      el('summary', { text: 'What exactly is missing' }),
      el('dl', { class: 'health__lists' }, [
        ...lists.map(([label, items]) => el('div', {}, [
          el('dt', { text: `${label} (${items.length})` }),
          el('dd', {}, el('ul', {}, items.map((i) => el('li', { text: String(i) })))),
        ])),
        absent.length ? el('div', {}, [
          el('dt', { text: `python modules absent (${absent.length})` }),
          el('dd', {}, el('ul', {}, absent.map((d) => el('li', {
            text: `${d.module} — powers ${d.powers || 'unstated'}` })))),
        ]) : null,
      ]),
    ]),
  );
  healthBox.hidden = false;
}

onSourceChange(() => { paintConnection(); paintHealth(); });

// ------------------------------------------------------------------ router --

function currentName() {
  const name = (location.hash || '').replace(/^#\/?/, '').split('?')[0];
  return VIEWS[name] ? name : DEFAULT;
}

let token = 0;

async function route() {
  const name = currentName();
  const mine = ++token;

  nav.forEach((a) => {
    if (a.dataset.view === name) a.setAttribute('aria-current', 'page');
    else a.removeAttribute('aria-current');
  });
  document.title = `${TITLES[name] || name} · AFNI Responsible AI`;

  clear(view);
  try {
    await VIEWS[name].render(view);
  } catch (err) {
    if (mine !== token) return;
    clear(view).append(el('div', { class: 'errorbox', role: 'alert' }, [
      el('strong', { text: 'This view failed to render. ' }),
      el('code', { text: String(err && err.stack ? err.stack : err) }),
    ]));
  }
  if (mine === token) window.scrollTo({ top: 0, behavior: 'instant' });
}

window.addEventListener('hashchange', route);

// -------------------------------------------------------------------- boot --

readBaseFromLocation();
paintConnection();
paintHealth();
// replaceState rather than assigning location.hash: assigning would fire
// hashchange and render the default view twice.
if (!location.hash) history.replaceState(null, '', `#/${DEFAULT}`);
await probe();
paintConnection();
paintHealth();
await route();
