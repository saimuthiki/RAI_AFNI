// Sensitivity — the threshold knobs.
//
// The one screen that answers "how strict is this?" with numbers instead of
// adjectives, and the one place a claim has to be made carefully:
//
//   LOWERING A THRESHOLD DOES NOT FIND MORE HARM. It lowers the bar for calling
//   something harm. The detector's ranking of inputs is completely unchanged.
//   What changes is that more legitimate work gets refused — and a guardrail
//   that refuses legitimate work gets switched off by the business inside a
//   fortnight, which is a far worse outcome than a threshold at 0.7.
//
// So "Maximum sensitivity" is offered, because it was asked for and it is
// genuinely useful for a red-team demonstration, and it is labelled as exactly
// that rather than dressed up as the safe default.
//
// Three layers, and this screen is the middle one:
//   1. the code ships every default, cited to the repository it came from;
//   2. this screen overrides them per deployment;
//   3. a REQUEST can never set one — a caller who could raise a threshold could
//      route around the guardrail.

import {
  el, clear, pageHead, rule, statRow, errorBox, pill, plural, fmtScore,
} from '../ui.js';
import { thresholds, saveThresholds, state } from '../api.js';

const DIRECTION_NOTE = {
  'lower-is-stricter': null,
  envelope: 'Half of a matched pair. Moving one without the other changes what '
    + 'the envelope means, so presets leave both alone.',
  'not-a-detection': 'This measures the model’s own behaviour, not a user’s. '
    + 'Lowering it makes nothing stricter — it makes more answers get called '
    + 'refusals. Presets leave it alone.',
};

export async function render(root) {
  clear(root);
  root.append(pageHead(
    'Sensitivity',
    'Every threshold, and the number in force',
    'A threshold is the score a detector has to reach before it counts. These '
    + 'are the shipped numbers, each one taken from the project it was ported '
    + 'from, and what this deployment has changed.',
  ));

  if (state.source === 'fixtures') {
    root.append(el('div', { class: 'notebox' }, [
      el('strong', { text: 'The gateway is not answering. ' }),
      el('span', {
        text: 'This screen changes server configuration, so it is read-only '
          + 'against fixtures — there is nothing to write to.',
      }),
    ]));
  }

  const loading = el('p', { class: 'empty', text: 'Reading /v1/thresholds…' });
  root.append(loading);

  let data;
  try {
    data = await thresholds();
  } catch (err) {
    loading.remove();
    root.append(errorBox('GET /v1/thresholds', err));
    return;
  }
  loading.remove();

  root.append(statRow([
    { label: 'Tunable', value: String(data.counts.tunable) },
    {
      label: 'Overridden here',
      value: String(data.counts.overridden),
      tone: data.counts.overridden ? 'warn' : null,
      note: data.counts.overridden
        ? 'The rest are the shipped defaults.'
        : 'Everything is on the shipped default.',
    },
    {
      label: 'Applies',
      value: 'next request',
      note: 'No restart. The store does not cache, on purpose.',
    },
  ]));

  root.append(el('div', { class: 'notebox notebox--stop' }, [
    el('strong', { text: 'Read this before dragging anything down. ' }),
    el('span', { text: data.honesty || '' }),
  ]));

  if (Array.isArray(data.problems) && data.problems.length) {
    root.append(el('div', { class: 'errorbox', role: 'alert' }, [
      el('strong', {
        text: `${plural(data.problems.length, 'value')} in the saved file `
          + 'was rejected and is NOT in force: ',
      }),
      el('ul', {}, data.problems.map((p) => el('li', { text: p }))),
    ]));
  }

  // ---- the editor ---------------------------------------------------------
  // One state object for the whole screen. Save is disabled until it differs
  // from what the server returned, so an operator can never save a no-op and
  // conclude the endpoint did nothing.
  const saved = new Map();
  const current = new Map();
  for (const row of data.thresholds) {
    if (row.overridden) saved.set(row.key, row.effective);
    current.set(row.key, row.effective);
  }

  const status = el('p', { class: 'micro', text: '' });
  const save = el('button', { class: 'btn', text: 'Save', disabled: true });
  const revert = el('button', { class: 'btn btn--quiet', text: 'Discard changes', disabled: true });

  const dirty = () => {
    for (const row of data.thresholds) {
      const was = saved.has(row.key) ? saved.get(row.key) : row.shipped;
      if (Math.abs(current.get(row.key) - was) > 1e-9) return true;
    }
    // A row dropped back to its shipped value is a REMOVED override, which is
    // also a change — caught by the loop above, since `was` is the override.
    return false;
  };
  const refresh = () => {
    const d = dirty();
    save.disabled = !d;
    revert.disabled = !d;
    status.textContent = d
      ? 'Unsaved. Nothing has changed on the server yet.'
      : 'Matches the server.';
  };

  const rowNodes = new Map();
  const groupsWrap = el('div', { class: 'knobgroups' });
  for (const group of data.groups) {
    const rows = data.thresholds.filter((r) => r.group === group);
    if (!rows.length) continue;
    const list = el('div', { class: 'knoblist' });
    for (const row of rows) {
      const node = knobRow(row, current, refresh);
      rowNodes.set(row.key, node);
      list.append(node.el);
    }
    groupsWrap.append(el('section', { class: 'knobgroup' }, [
      el('div', { class: 'knobgroup__head' }, [
        el('h3', { class: 'knobgroup__t', text: group }),
        el('span', { class: 'micro', text: plural(rows.length, 'threshold') }),
      ]),
      group === 'Not a detection'
        ? el('p', {
          class: 'knobgroup__why',
          text: 'These three are not "how strict". They are excluded from every '
            + 'preset, because dragging them down with the rest would change '
            + 'what they measure rather than tighten anything.',
        })
        : null,
      list,
    ]));
  }

  root.append(rule('Presets', plural(data.presets.length, 'preset')));
  root.append(presets(data, current, rowNodes, refresh, save));

  root.append(rule('Every threshold', plural(data.counts.tunable, 'knob')));
  root.append(groupsWrap);

  root.append(el('div', { class: 'saverow' }, [save, revert, status]));

  const result = el('div', { class: 'saveresult' });
  root.append(result);

  revert.addEventListener('click', () => {
    for (const row of data.thresholds) {
      const was = saved.has(row.key) ? saved.get(row.key) : row.shipped;
      current.set(row.key, was);
      rowNodes.get(row.key).set(was);
    }
    refresh();
    clear(result);
  });

  save.addEventListener('click', async () => {
    // Only rows that DIFFER from shipped are sent. Sending all 24 would write a
    // file that pins every number, so a later change to a shipped default would
    // silently not reach this deployment.
    const body = {};
    for (const row of data.thresholds) {
      if (Math.abs(current.get(row.key) - row.shipped) > 1e-9) {
        body[row.key] = current.get(row.key);
      }
    }
    save.disabled = true;
    const was = save.textContent;
    save.textContent = 'Saving…';
    clear(result);
    try {
      const out = await saveThresholds({ thresholds: body });
      saved.clear();
      for (const [k, v] of Object.entries(body)) saved.set(k, v);
      for (const row of data.thresholds) {
        row.overridden = Object.prototype.hasOwnProperty.call(body, row.key);
        rowNodes.get(row.key).mark(row.overridden);
      }
      result.append(el('div', { class: 'notebox' }, [
        el('strong', { text: `Saved — ${plural(out.overridden, 'override')}. ` }),
        el('span', { text: out.note || '' }),
        el('p', { class: 'micro', text: `Written to ${out.policy_path}` }),
      ]));
    } catch (err) {
      result.append(errorBox('PUT /v1/thresholds', err));
    } finally {
      save.textContent = was;
      refresh();
    }
  });

  refresh();
}

// --------------------------------------------------------------------------- //
function presets(data, current, rowNodes, refresh, save) {
  const wrap = el('div', { class: 'presets' });
  for (const spec of data.presets) {
    const btn = el('button', {
      class: `preset preset--${spec.name}`,
      type: 'button',
    }, [
      el('span', { class: 'preset__t', text: spec.label }),
      el('span', {
        class: 'preset__n',
        text: spec.touches
          ? `sets ${plural(spec.touches, 'threshold')}`
          : 'clears every override',
      }),
      el('span', { class: 'preset__why', text: spec.why }),
    ]);
    btn.addEventListener('click', () => {
      // Applied to the FORM, not to the server. A preset that wrote straight
      // through would leave an operator no chance to see what it did to the
      // twenty-one rows before committing to it.
      for (const row of data.thresholds) {
        const value = spec.touches && row.direction === 'lower-is-stricter'
          ? presetValue(spec, row)
          : row.shipped;
        current.set(row.key, value);
        rowNodes.get(row.key).set(value);
      }
      refresh();
      save.focus();
    });
    wrap.append(btn);
  }
  wrap.append(el('p', {
    class: 'micro presets__foot',
    text: 'A preset fills the form in. Nothing reaches the server until you '
      + 'press Save, so you can see all '
      + `${data.counts.tunable} rows it changed first. It skips `
      + `${data.preset_excludes.join(', ')} — see the last group for why.`,
  }));
  return wrap;
}

/** Recompute a preset's value client-side, matching `sensitivity.preset_overrides`.
 *
 *  Duplicated arithmetic, and the duplication is deliberate rather than lazy:
 *  the alternative is a round trip per preset click to a WRITE endpoint, which
 *  would mean the only way to preview a preset is to apply it. The factor and
 *  floor come from the server in the presets payload, so a change to either one
 *  reaches this screen without a code change here.
 */
function presetValue(spec, row) {
  const factor = Number(spec.factor ?? 1);
  const floor = Number(spec.floor ?? 0);
  return Math.min(1, Math.max(floor, Math.round(row.shipped * factor * 100) / 100));
}

// --------------------------------------------------------------------------- //
function knobRow(row, current, refresh) {
  const input = el('input', {
    type: 'number', min: '0', max: '1', step: '0.05',
    class: 'knob__in', value: String(row.effective),
    'aria-label': `${row.label} threshold`,
  });
  const badge = el('span', { class: 'knob__scope' });
  const shipped = el('span', {
    class: 'knob__shipped',
    text: `shipped ${fmtScore(row.shipped)}`,
  });

  const mark = (overridden) => {
    badge.textContent = overridden ? 'overridden' : 'shipped';
    badge.className = `knob__scope ${overridden ? 'knob__scope--over' : ''}`;
  };
  mark(row.overridden);

  input.addEventListener('input', () => {
    const raw = Number(input.value);
    // Clamped here rather than trusted: a number input still accepts a typed
    // 1.7 in every browser, and the gateway would reject the save with a 422
    // that names a row the operator has already scrolled past.
    const value = Number.isFinite(raw) ? Math.min(1, Math.max(0, raw)) : row.shipped;
    current.set(row.key, value);
    mark(Math.abs(value - row.shipped) > 1e-9);
    refresh();
  });

  const reset = el('button', {
    class: 'btn btn--quiet knob__reset', type: 'button', text: 'Shipped',
    title: `Back to ${fmtScore(row.shipped)}`,
  });
  reset.addEventListener('click', () => {
    input.value = String(row.shipped);
    current.set(row.key, row.shipped);
    mark(false);
    refresh();
  });

  const note = DIRECTION_NOTE[row.direction];
  const node = el('div', { class: 'knob' }, [
    el('div', { class: 'knob__head' }, [
      el('strong', { class: 'knob__label', text: row.label }),
      row.noisy ? pill('noisy', 'tag--flag') : null,
      badge,
    ]),
    el('code', { class: 'knob__key', text: row.key }),
    el('p', { class: 'knob__judges', text: row.judges }),
    note ? el('p', { class: 'knob__warn', text: note }) : null,
    el('div', { class: 'knob__ctl' }, [input, shipped, reset]),
  ]);

  return {
    el: node,
    mark,
    set(value) {
      input.value = String(value);
      mark(Math.abs(value - row.shipped) > 1e-9);
    },
  };
}
