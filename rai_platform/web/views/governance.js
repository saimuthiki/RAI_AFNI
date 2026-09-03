// Governance — one accountable ROLE per tenet, and the thresholds in force.
//
// This section exists because AFNI pushed back on being asked for seven names.
// They were right, and the push-back changed the design rather than the default:
// a person's name in a governance register is stale the moment they change team,
// and a register with a wrong escalation path is worse than one with an honest
// gap — the first sends an incident to somebody who left.
//
// So the roles are generated, and what AFNI supplies is at most ONE setting.
// Read-only on purpose: an escalation path that anybody with the console could
// rewrite is not an escalation path, so the domain is a server environment
// variable and this screen reports it rather than editing it.
//
// Rendered as a section of the Tenets screen, because the register IS the seven
// tenets and a separate tab would repeat their explanation.

import { el, clear, rule, statRow, errorBox, pill, plural } from '../ui.js';
import { governance } from '../api.js';

export function section(root) {
  const wrap = el('section', { class: 'gov' });
  root.append(wrap);
  wrap.append(rule('Governance register', 'generated, not typed in'));
  const loading = el('p', { class: 'empty', text: 'Reading /v1/governance…' });
  wrap.append(loading);

  governance().then((doc) => {
    loading.remove();
    wrap.append(body(doc));
  }).catch((err) => {
    loading.remove();
    wrap.append(errorBox('GET /v1/governance', err));
  });
  return wrap;
}

function body(doc) {
  const frag = el('div', { class: 'gov__body' });

  frag.append(statRow([
    { label: 'Tenets', value: String(doc.counts.tenets) },
    {
      label: 'With an escalation address',
      value: `${doc.counts.resolved} of ${doc.counts.tenets}`,
      tone: doc.counts.resolved === doc.counts.tenets ? 'good' : 'warn',
      note: doc.counts.resolved === doc.counts.tenets
        ? 'all seven reachable'
        : `set ${doc.domain_env} on the server — one setting arms all seven`,
    },
    { label: 'Rails accounted for', value: String(doc.counts.rails_mounted) },
    { label: 'Fail mode', value: 'closed', tone: 'good',
      note: 'unconditional — no request field, no console switch' },
  ]));

  frag.append(el('div', { class: 'notebox' }, [
    // The server's sentence already opens "Roles, not people", so the lead-in
    // here asks the question rather than repeating the answer.
    el('strong', { text: 'Why there are no names here. ' }),
    el('span', { text: doc.why_no_names || '' }),
  ]));

  for (const problem of doc.problems || []) {
    frag.append(el('div', { class: 'notebox notebox--stop' }, [
      el('strong', { text: 'Not yet configured. ' }),
      el('span', { text: problem }),
    ]));
  }

  const list = el('div', { class: 'govlist' });
  for (const row of doc.tenets || []) {
    list.append(el('article', { class: 'govrow' }, [
      el('div', { class: 'govrow__head' }, [
        el('strong', { class: 'govrow__t', text: row.tenet }),
        row.resolved
          ? pill('reachable', 'tag--present')
          : pill('domain unset', 'tag--flag'),
      ]),
      el('p', { class: 'govrow__role', text: row.role }),
      el('code', { class: 'govrow__contact', text: row.contact }),
      el('p', { class: 'govrow__why', text: row.accountable_for }),
      el('p', { class: 'micro',
        text: `${plural(row.rails_mounted, 'rail')} mounted`
          + (row.stages.length ? ` · stage ${row.stages.join(', ')}` : '') }),
      thresholdTable(row.thresholds),
    ]));
  }
  frag.append(list);
  frag.append(el('p', {
    class: 'micro',
    // The point of generating it rather than maintaining it by hand.
    text: 'Every number here is read from the running platform — rails mounted, '
      + 'capability coverage, and the threshold values in force right now '
      + 'including operator overrides. The register cannot describe a '
      + 'configuration nobody is running. `afni-rai governance --markdown` '
      + 'renders the same document for a client approval pack.',
  }));
  return frag;
}

function thresholdTable(knobs) {
  if (!knobs || !knobs.length) {
    return el('p', { class: 'micro', text: 'No tunable threshold under this tenet.' });
  }
  return el('ul', { class: 'govknobs' }, knobs.map((k) => el('li', {}, [
    el('span', { class: 'govknobs__l', text: k.label }),
    el('span', {
      class: `govknobs__v ${k.overridden ? 'govknobs__v--over' : ''}`,
      text: k.overridden ? `${k.effective} (was ${k.shipped})` : String(k.effective),
    }),
  ])));
}
