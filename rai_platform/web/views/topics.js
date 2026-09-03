// Topics — the one screen that CHANGES what the gateway blocks.
//
// Everything else in this console reads. This writes, so it is built to make
// three things impossible to miss:
//
//   1. The six ALWAYS topics are shown FIRST, locked, and visibly not
//      tick-boxes. An operator who cannot see them will assume nothing is
//      banned until they tick something, and will then be surprised that a
//      bomb-making request was already refused.
//   2. Flag and block are different, and the difference is money. A flagged
//      topic still reaches the model; a blocked one does not. The promote
//      control is a second, deliberate action per topic - never a bulk toggle.
//   3. A saved policy is NOT a live policy until restart. Said next to the
//      Save button, and again after saving, because somebody testing a topic
//      that is not yet armed will conclude the feature is broken.

import {
  el, clear, frag, pageHead, rule, statRow, errorBox, pill, plural,
} from '../ui.js';
import { topicPolicy, saveTopicPolicy, state } from '../api.js';

/** Group -> the copy that explains why a whole group exists. Written for
 *  somebody deciding, not somebody debugging. */
const GROUP_NOTE = {
  'Never': 'Compiled into the code and always on. These cannot be switched off '
    + 'from here — changing one is a code change and a code review, which is the '
    + 'point. They block outright.',
  'Regulated advice': 'Advice the business is not licensed to give. Leave a row '
    + 'OFF only if this application genuinely is that kind of service — a '
    + 'benefits helpdesk must be able to discuss medical leave.',
  'Commitments': 'Things an AI must not promise on AFNI’s behalf. An AI that '
    + 'promises a refund creates an expectation a person has to honour.',
  'Brand': 'No upside, real downside. Usually all on.',
  'Safety': 'Threats and abuse, including toward AFNI staff.',
  'Internal information': 'Reconnaissance and data belonging to somebody else. '
    + 'These are the rows most often a real attack rather than a confused '
    + 'customer.',
};

export async function render(root) {
  clear(root);
  root.append(pageHead(
    'Topics',
    'What this application will not discuss',
    'A fast, free word-and-phrase check that runs on every message in both '
    + 'directions. Six topics are always banned and compiled into the code. The '
    + 'other twenty-four are yours to choose, because “off-topic” differs per '
    + 'application.',
  ));

  if (state.source === 'fixtures') {
    root.append(el('div', { class: 'notebox' }, [
      el('strong', { text: 'The gateway is not answering. ' }),
      el('span', { text: 'This screen changes server configuration, so it is '
        + 'read-only against fixtures — there is nothing to write to.' }),
    ]));
  }

  const loading = el('p', { class: 'empty', text: 'Reading /v1/topics…' });
  root.append(loading);

  let data;
  try { data = await topicPolicy(); } catch (err) {
    loading.replaceWith(errorBox('Loading the topic policy', err)); return;
  }
  loading.remove();

  // Working copy. Nothing is sent until Save, so a mis-click is undoable by
  // navigating away rather than by hunting for an undo.
  const enabled = new Set(data.optional.filter((t) => t.enabled).map((t) => t.id));
  const blocking = new Set(data.optional.filter((t) => t.blocking).map((t) => t.id));
  const saved = { enabled: new Set(enabled), blocking: new Set(blocking) };

  const statSlot = el('div');
  const noteSlot = el('div');
  root.append(statSlot, noteSlot);

  function dirty() {
    if (enabled.size !== saved.enabled.size) return true;
    if (blocking.size !== saved.blocking.size) return true;
    for (const id of enabled) if (!saved.enabled.has(id)) return true;
    for (const id of blocking) if (!saved.blocking.has(id)) return true;
    return false;
  }

  function patternCount() {
    let flag = 0; let block = data.always.reduce((n, t) => n + t.patterns.length, 0);
    for (const t of data.optional) {
      if (!enabled.has(t.id)) continue;
      if (blocking.has(t.id)) block += t.patterns.length;
      else flag += t.patterns.length;
    }
    return { flag, block };
  }

  function paintStats() {
    const { flag, block } = patternCount();
    clear(statSlot).append(statRow([
      { label: 'Always banned', value: String(data.always.length),
        note: 'compiled in, cannot be switched off here, and they block' },
      { label: 'Chosen by you', value: `${enabled.size} of ${data.optional.length}`,
        tone: enabled.size ? 'good' : 'warn',
        note: enabled.size ? 'flag and escalate unless promoted' : 'nothing selected yet' },
      { label: 'Promoted to block', value: String(blocking.size),
        tone: blocking.size ? 'warn' : undefined,
        note: 'these refuse the message outright' },
      { label: 'Phrases matched', value: `${block + flag}`,
        note: `${block} blocking · ${flag} flagging` },
    ]));
  }

  function paintNote() {
    clear(noteSlot);
    if (data.restart_pending) {
      noteSlot.append(el('div', { class: 'notebox' }, [
        el('strong', { text: 'A saved policy is waiting for a restart. ' }),
        el('span', { text: 'The file on disk differs from what this gateway '
          + 'loaded at boot, so what you see here is not yet what is running. '
          + 'Restart the gateway to arm it.' }),
      ]));
    }
    if (!data.mounted) {
      noteSlot.append(el('div', { class: 'notebox notebox--stop' }, [
        el('strong', { text: 'The topic rail is NOT mounted. ' }),
        el('span', { text: 'It should always be, because the always-banned '
          + 'topics guarantee a non-empty list. This means something failed at '
          + 'startup and there is no topic cover at all — check /healthz.' }),
      ]));
    }
  }

  paintStats();
  paintNote();

  // ---------------------------------------------------------------- always ---
  root.append(rule('Always banned', 'in the code, not in this screen'));
  const always = data.always;
  root.append(el('div', { class: 'card card__pad' }, [
    el('p', { class: 'small mute', style: 'max-width:80ch', text: GROUP_NOTE.Never }),
    el('div', { class: 'topiclist', style: 'margin-top:var(--sp-4)' },
      always.map((t) => el('div', { class: 'topic topic--locked' }, [
        el('div', { class: 'topic__head' }, [
          el('span', { class: 'topic__lock', 'aria-hidden': 'true', text: '🔒' }),
          el('span', { class: 'topic__label', text: t.label }),
          pill('always blocks', 'tag--absent'),
        ]),
        el('p', { class: 'topic__why', text: t.why }),
        el('p', { class: 'topic__pat t-mono', text: `${plural(t.patterns.length, 'phrase')}: ${t.patterns.slice(0, 3).join(' · ')}${t.patterns.length > 3 ? ' …' : ''}` }),
      ]))),
  ]));

  // -------------------------------------------------------------- optional ---
  root.append(rule('Your choice', `${data.optional.length} topics, grouped`));

  const rowsById = new Map();

  function paintRow(t) {
    const row = rowsById.get(t.id);
    if (!row) return;
    const on = enabled.has(t.id);
    const blk = blocking.has(t.id);
    row.box.checked = on;
    row.el.classList.toggle('topic--on', on);
    row.promote.hidden = !on;
    row.promoteBox.checked = blk;
    row.action.textContent = !on ? '' : blk ? 'blocks the message' : 'flags and escalates';
    row.action.className = `topic__action ${blk ? 'topic__action--block' : 'topic__action--flag'}`;
  }

  const byGroup = new Map();
  for (const t of data.optional) {
    if (!byGroup.has(t.group)) byGroup.set(t.group, []);
    byGroup.get(t.group).push(t);
  }

  for (const [group, items] of byGroup) {
    const groupBox = el('div', { class: 'card card__pad', style: 'margin-top:var(--sp-4)' });
    const allOn = () => items.every((t) => enabled.has(t.id));
    const groupBtn = el('button', {
      class: 'btn btn--quiet', type: 'button',
      text: allOn() ? 'Clear this group' : 'Select this group',
      on: { click() {
        const turnOn = !allOn();
        for (const t of items) {
          if (turnOn) enabled.add(t.id);
          else { enabled.delete(t.id); blocking.delete(t.id); }
          paintRow(t);
        }
        groupBtn.textContent = allOn() ? 'Clear this group' : 'Select this group';
        paintStats(); paintSave();
      } },
    });

    groupBox.append(el('div', { class: 'topicgroup__head' }, [
      el('h3', { class: 'topicgroup__t', text: group }),
      el('span', { class: 'micro mute', text: plural(items.length, 'topic') }),
      groupBtn,
    ]));
    groupBox.append(el('p', { class: 'small mute', style: 'max-width:80ch',
      text: GROUP_NOTE[group] || '' }));

    const list = el('div', { class: 'topiclist', style: 'margin-top:var(--sp-4)' });
    for (const t of items) {
      const box = el('input', { type: 'checkbox' });
      const promoteBox = el('input', { type: 'checkbox' });
      const action = el('span', { class: 'topic__action' });

      box.addEventListener('change', () => {
        if (box.checked) enabled.add(t.id);
        // Un-ticking a topic clears its promotion too. "Blocking but not
        // enabled" is not a state the server accepts, and leaving it set would
        // make the next Save a 422 for a reason the operator cannot see.
        else { enabled.delete(t.id); blocking.delete(t.id); }
        paintRow(t);
        groupBtn.textContent = allOn() ? 'Clear this group' : 'Select this group';
        paintStats(); paintSave();
      });
      promoteBox.addEventListener('change', () => {
        if (promoteBox.checked) blocking.add(t.id); else blocking.delete(t.id);
        paintRow(t); paintStats(); paintSave();
      });

      const promote = el('label', { class: 'topic__promote', hidden: true }, [
        promoteBox,
        el('span', { text: 'block instead of flag' }),
      ]);

      const rowEl = el('div', { class: 'topic' }, [
        el('label', { class: 'topic__head' }, [
          box,
          el('span', { class: 'topic__label', text: t.label }),
          action,
        ]),
        el('p', { class: 'topic__why', text: t.why }),
        el('p', { class: 'topic__pat t-mono', text:
          `${plural(t.patterns.length, 'phrase')}: ${t.patterns.slice(0, 3).join(' · ')}${t.patterns.length > 3 ? ' …' : ''}` }),
        promote,
      ]);
      rowsById.set(t.id, { el: rowEl, box, promote, promoteBox, action });
      list.append(rowEl);
      paintRow(t);
    }
    groupBox.append(list);
    root.append(groupBox);
  }

  // ------------------------------------------------------------------ save ---
  const saveBtn = el('button', { class: 'btn', type: 'button', text: 'Save the policy' });
  const saveState = el('span', { class: 'micro mute' });
  const saveSlot = el('div', { class: 'panel__actions', style: 'margin-top:var(--sp-4)' },
    [saveBtn, saveState]);
  const resultSlot = el('div');

  function paintSave() {
    const d = dirty();
    saveBtn.disabled = !d || state.source === 'fixtures';
    clear(saveState).append(frag([
      el('span', { text: d ? 'Unsaved changes. ' : 'Nothing to save. ' }),
      el('span', { text: 'Saving writes a file on the server; it arms on the '
        + 'next gateway restart, not immediately.' }),
    ]));
  }

  saveBtn.addEventListener('click', async () => {
    saveBtn.disabled = true;
    clear(resultSlot);
    try {
      const body = await saveTopicPolicy({
        enabled: [...enabled].sort(), blocking: [...blocking].sort(),
      });
      saved.enabled = new Set(enabled);
      saved.blocking = new Set(blocking);
      data.restart_pending = true;
      paintNote();
      resultSlot.append(el('div', { class: 'notebox' }, [
        el('strong', { text: 'Saved. ' }),
        el('span', { text: String(body.note || '') }),
        el('div', { class: 'micro mute', style: 'margin-top:var(--sp-2)', text:
          `${body.patterns.blocking} blocking and ${body.patterns.flagging} flagging `
          + `phrases · written to ${body.policy_path}` }),
      ]));
    } catch (err) {
      resultSlot.append(errorBox('Saving the topic policy', err));
    } finally {
      paintSave();
    }
  });

  root.append(rule('Apply', 'writes a file on the server'));
  root.append(el('div', { class: 'card card__pad' }, [
    el('p', { class: 'small', style: 'max-width:80ch', text:
      'Flagged topics are recorded and the message still goes through. Blocked '
      + 'topics refuse it. Promote a topic to blocking only when its phrases '
      + 'cannot plausibly appear in legitimate work — a blocking word list is '
      + 'the easiest way to build a guardrail that refuses ordinary business.' }),
    saveSlot, resultSlot,
  ]));
  paintSave();
}
