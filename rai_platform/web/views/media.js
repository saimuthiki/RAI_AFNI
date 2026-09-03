// Media — the only screen where the thing being judged is not text.
//
// Three decisions shaped this screen, and each one is visible in it:
//
//   1. THE BLURRED COPY IS WHAT YOU SEE FIRST. If regions were detected, the
//      redacted image is displayed and the original is behind a deliberate
//      click. An operator moderating uploads should not have explicit content
//      painted onto their monitor by default just because they pressed Check.
//   2. THE BOXES ARE DRAWN. A verdict that says "explicit content, 0.91" and
//      shows nothing is unauditable. The rectangles the detector actually fired
//      on are overlaid, so a false positive is visible as a false positive.
//   3. A MISSING MODEL IS SHOUTED ABOUT, NOT INFERRED. Without `nudenet` every
//      image comes back BLOCKED, and an operator reading that word without
//      being told why would conclude their holiday photo was pornographic.
//
// Nothing here writes server configuration. The thresholds this screen reports
// are set on the Sensitivity screen.

import {
  el, clear, pageHead, rule, statRow, errorBox, pill, plural, fmtScore,
} from '../ui.js';
import { mediaStatus, moderateMedia, state } from '../api.js';

const MAX_MB = 16;

/** Read a File as bare base64 (no data-URL prefix). */
function toBase64(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onerror = () => reject(new Error(`could not read ${file.name}`));
    reader.onload = () => {
      const result = String(reader.result || '');
      // FileReader gives `data:image/png;base64,AAAA`. The gateway accepts the
      // prefix, but stripping it here keeps the request body smaller and the
      // two sides honest about which one is being lenient.
      resolve(result.slice(result.indexOf(',') + 1));
    };
    reader.readAsDataURL(file);
  });
}

const isVideo = (file) => /^video\//.test(file.type)
  || /\.(mp4|mov|webm|avi|mkv)$/i.test(file.name);

/** The band a region belongs to, as a colour class. */
const BAND_CLASS = { explicit: 'mbox--block', suggestive: 'mbox--flag', face: 'mbox--face' };

const BAND_NOTE = {
  explicit: 'Exposure. Blocks at or above the explicit threshold.',
  suggestive: 'Covered but suggestive. Flags for review — never blocks on its own.',
  face: 'A face. Reported as biometric PII, and it never blocks: a photograph of '
    + 'a person is not a policy violation. The model’s gender guess is discarded '
    + 'before the finding is made.',
};

export async function render(root) {
  clear(root);
  root.append(pageHead(
    'Media',
    'Images and video',
    'A local model, no network, about 90 ms an image. It looks for exposure and '
    + 'for faces, and nothing it finds ever leaves this machine.',
  ));

  if (state.source === 'fixtures') {
    root.append(el('div', { class: 'notebox' }, [
      el('strong', { text: 'The gateway is not answering. ' }),
      el('span', {
        text: 'This screen has no fixture: an image can only be judged by the '
          + 'real model, and inventing a verdict for one would be a lie dressed '
          + 'as a demo. Start the gateway and reload.',
      }),
    ]));
    return;
  }

  const loading = el('p', { class: 'empty', text: 'Reading /v1/media…' });
  root.append(loading);

  let status;
  try {
    status = await mediaStatus();
  } catch (err) {
    loading.remove();
    root.append(errorBox('GET /v1/media', err));
    return;
  }
  loading.remove();

  root.append(rule('Is it installed', status.available ? 'yes' : 'NO'));

  if (!status.available) {
    root.append(el('div', { class: 'notebox notebox--stop' }, [
      el('strong', { text: 'The model is not installed, so nothing can be judged. ' }),
      el('p', {
        text: 'Every image and every video will come back BLOCKED. That is a '
          + 'coverage gap, not a detection — “could not look” is never allowed to '
          + 'mean “found nothing” anywhere in this platform. Install it and '
          + 'restart the gateway:',
      }),
      el('pre', { class: 'code', text: status.install_hint || 'pip install nudenet' }),
      el('p', {
        class: 'micro',
        text: 'There is no separate model download. The 12 MB '
          + `${status.model_file} ships inside the wheel, so this works on a `
          + 'machine with no internet access at all once the wheel is on it.',
      }),
    ]));
  } else {
    root.append(statRow([
      { label: 'Detector', value: status.detector },
      { label: 'Cost', value: '≈90 ms' },
      { label: 'Stage', value: '2 — local' },
      { label: 'Network', value: 'none' },
    ]));
    root.append(el('p', {
      class: 'micro',
      text: `Weights: ${status.model_path}`,
    }));
  }

  root.append(el('div', { class: 'notebox' }, [
    el('strong', { text: 'Live check does not check images. ' }),
    el('span', {
      text: 'Text and media are separate routes, because a guard event’s payload '
        + 'is strings. An application of yours that accepts uploads has to call '
        + 'POST /v1/media/image as well as POST /v1/guard — one does not cover '
        + 'the other.',
    }),
  ]));

  root.append(rule('Try one', 'nothing is uploaded anywhere'));
  root.append(picker(status));

  const reported = (status.labels?.explicit_block?.length || 0)
    + (status.labels?.suggestive_flag?.length || 0) + 1;
  root.append(rule('What it looks for',
    plural(reported, 'reported class', 'reported classes')));
  root.append(labelTable(status));

  root.append(rule('Video', 'offline, not the request path'));
  root.append(el('p', {
    class: 'mediapara',
    text: 'A frame costs about 90 ms, so scoring every frame of a thirty-second '
      + 'clip is over a minute of CPU. That is not a check to put in front of '
      + 'somebody waiting for an answer, so video samples every '
      + `${status.video?.frame_stride ?? 15}th frame and stops at `
      + `${status.video?.max_frames ?? 120}. The result reports how many frames `
      + 'were actually looked at against how many exist, because the gap is real '
      + 'and hiding it would make the check look stronger than it is.',
  }));

  root.append(el('p', {
    class: 'micro',
    text: status.accuracy_note || '',
  }));
}

// --------------------------------------------------------------------------- //
function picker(status) {
  const wrap = el('div', { class: 'mediapick' });

  const input = el('input', {
    type: 'file', id: 'media-file', class: 'mediapick__input',
    accept: 'image/*,video/*',
  });
  const name = el('span', { class: 'mediapick__name', text: 'No file chosen' });
  const blur = el('input', { type: 'checkbox', id: 'media-blur', checked: true });
  const run = el('button', { class: 'btn', text: 'Check', disabled: true });
  const out = el('div', { class: 'mediaout' });

  let file = null;

  input.addEventListener('change', () => {
    file = input.files && input.files[0] ? input.files[0] : null;
    clear(out);
    if (!file) {
      name.textContent = 'No file chosen';
      run.disabled = true;
      return;
    }
    const mb = file.size / (1024 * 1024);
    name.textContent = `${file.name} — ${mb.toFixed(1)} MB`
      + (isVideo(file) ? ' (video)' : '');
    // Refused here rather than at the gateway: a 16 MB base64 round trip only
    // to be told no is a slow way to learn a fast fact.
    if (mb > MAX_MB) {
      run.disabled = true;
      out.append(el('div', { class: 'notebox notebox--stop' }, [
        el('strong', { text: 'Too large. ' }),
        el('span', {
          text: `${mb.toFixed(1)} MB is over the ${MAX_MB} MB limit. The limit `
            + 'exists so a single upload cannot exhaust the gateway’s memory.',
        }),
      ]));
      return;
    }
    run.disabled = false;
  });

  run.addEventListener('click', async () => {
    if (!file) return;
    const video = isVideo(file);
    run.disabled = true;
    const was = run.textContent;
    run.textContent = video ? 'Scoring frames…' : 'Checking…';
    clear(out);
    out.append(el('p', {
      class: 'empty',
      text: video
        ? 'Sampling frames. A hundred frames is about ten seconds of CPU.'
        : 'Judging…',
    }));
    try {
      const base64 = await toBase64(file);
      const body = await moderateMedia(video ? 'video' : 'image', base64,
        video ? {} : { blur: blur.checked });
      clear(out);
      out.append(result(body, file, video, status));
    } catch (err) {
      clear(out);
      out.append(errorBox(video ? 'POST /v1/media/video' : 'POST /v1/media/image', err));
    } finally {
      run.textContent = was;
      run.disabled = false;
    }
  });

  wrap.append(
    el('div', { class: 'mediapick__row' }, [
      el('label', { class: 'btn', for: 'media-file', text: 'Choose an image or video' }),
      input,
      name,
    ]),
    el('label', { class: 'mediapick__opt' }, [
      blur,
      el('span', {
        text: 'Show the blurred copy first (recommended — it is the whole point '
          + 'of moderating an upload that you do not have to look at it)',
      }),
    ]),
    el('div', { class: 'mediapick__row' }, [run]),
    out,
  );
  return wrap;
}

// --------------------------------------------------------------------------- //
function result(body, file, video, status) {
  const wrap = el('div', { class: 'mediares' });
  const blocked = body.decision === 'block';
  const gap = Array.isArray(body.unjudged) && body.unjudged.length > 0;

  wrap.append(el('div', {
    class: `verdict verdict--${blocked ? 'block' : 'allow'}`,
  }, [
    el('span', { class: 'verdict__word', text: blocked ? 'BLOCKED' : 'ALLOWED' }),
    el('span', { class: 'verdict__why', text: body.reason || '' }),
  ]));

  if (gap) {
    wrap.append(el('div', { class: 'notebox notebox--stop' }, [
      el('strong', { text: 'This is a coverage gap, not a detection. ' }),
      el('span', {
        text: 'Nothing was judged — the model is missing, or the file could not '
          + 'be decoded. The block is the platform failing closed. It is not a '
          + 'statement about what is in the file.',
      }),
    ]));
  }

  const stats = [
    { label: 'Decision', value: blocked ? 'block' : 'allow' },
    { label: 'Findings', value: String((body.findings || []).length) },
    { label: 'Regions', value: String((body.regions || []).length) },
  ];
  if (body.latency_ms != null) stats.push({ label: 'Took', value: `${body.latency_ms} ms` });
  if (body.frames_scored != null) {
    stats.push({
      label: 'Frames scored',
      value: `${body.frames_scored} of ${body.frames_total ?? '?'}`,
    });
  }
  wrap.append(statRow(stats));

  if (body.frames_scored != null) {
    wrap.append(el('p', {
      class: 'micro',
      text: 'Sampling is a real reduction in coverage. A single explicit frame '
        + 'anywhere in the sample blocks the whole video — the union of what was '
        + 'seen, not an average, because an average lets one bad frame in a long '
        + 'clean clip disappear.',
    }));
  }

  if (!video) wrap.append(preview(body, file));

  const findings = body.findings || [];
  if (findings.length) {
    wrap.append(el('h4', { class: 'mediares__h', text: 'Findings' }));
    const list = el('ul', { class: 'findlist' });
    for (const f of findings) {
      list.append(el('li', {}, [
        pill(f.action || 'flag', f.action === 'block' ? 'tag--block' : 'tag--flag'),
        el('code', { text: f.category }),
        el('span', { class: 'findlist__score', text: fmtScore(f.score) }),
        el('span', { class: 'findlist__det', text: f.detector || '' }),
      ]));
    }
    wrap.append(list);
    wrap.append(el('p', {
      class: 'micro',
      text: 'One finding per band, however many rectangles. Three exposed '
        + 'regions in one photograph are one policy violation with three '
        + 'rectangles — counting them as three would treble the number in a '
        + 'compliance report without adding anything to it.',
    }));
  } else if (!gap) {
    wrap.append(el('p', {
      class: 'empty',
      text: 'Nothing above the thresholds. Note what that does NOT mean: the '
        + 'thresholds are '
        + Object.entries(status.thresholds || {})
          .map(([k, v]) => `${k.split('.').pop()} ${v}`).join(', ')
        + ' — a detection just below one is invisible here. Lower them on the '
        + 'Sensitivity screen if this application needs to be stricter.',
    }));
  }

  const regions = body.regions || [];
  if (regions.length) {
    wrap.append(el('h4', { class: 'mediares__h', text: 'Regions' }));
    const list = el('ul', { class: 'reglist' });
    for (const r of regions) {
      list.append(el('li', {}, [
        el('span', { class: `regdot ${BAND_CLASS[r.band] || ''}` }),
        el('strong', { text: r.band }),
        el('span', { class: 'reglist__geo', text: `${r.width}×${r.height} at (${r.x}, ${r.y})` }),
        el('span', { class: 'findlist__score', text: fmtScore(r.score) }),
        r.frame != null ? el('span', { class: 'micro', text: `frame ${r.frame}` }) : el('span'),
      ]));
    }
    wrap.append(list);
  }

  return wrap;
}

/** The image, with the detector's rectangles drawn on it.
 *
 *  Shows the BLURRED copy when the gateway returned one, and puts the original
 *  behind a click.
 *
 *  The boxes are positioned AFTER the image loads, from `naturalWidth` /
 *  `naturalHeight`. Regions come back in original-image pixels and there is no
 *  other honest source for the denominator: guessing it from the regions
 *  themselves - the largest extent, say - stretches the rectangles to fill the
 *  frame and draws boxes that are confidently in the wrong place, which is worse
 *  than drawing none.
 */
function preview(body, file) {
  const wrap = el('figure', { class: 'mediafig' });
  const regions = body.regions || [];
  const hasBlur = typeof body.blurred_base64 === 'string' && body.blurred_base64;

  const originalUrl = URL.createObjectURL(file);
  const blurredUrl = hasBlur ? `data:image/png;base64,${body.blurred_base64}` : null;

  const img = el('img', {
    class: 'mediafig__img',
    src: blurredUrl || originalUrl,
    alt: hasBlur
      ? 'The uploaded image with every detected region blurred.'
      : 'The uploaded image.',
  });

  const stage = el('div', { class: 'mediafig__stage' }, [img]);
  const boxes = regions.map((r) => el('span', {
    class: `mbox ${BAND_CLASS[r.band] || ''}`,
    title: `${r.band} ${fmtScore(r.score)}`,
    // Hidden until the natural size is known, so a box never flashes at the
    // wrong coordinates.
    style: 'display:none',
  }));
  for (const box of boxes) stage.append(box);

  img.addEventListener('load', () => {
    // The object URL is only needed while this node is alive, and leaking one
    // per check would hold every image the operator looked at in memory.
    if (img.src !== originalUrl) URL.revokeObjectURL(originalUrl);
    const w = img.naturalWidth;
    const h = img.naturalHeight;
    if (!w || !h) return;
    regions.forEach((r, i) => {
      const box = boxes[i];
      box.style.display = '';
      box.style.left = `${(100 * r.x) / w}%`;
      box.style.top = `${(100 * r.y) / h}%`;
      box.style.width = `${(100 * r.width) / w}%`;
      box.style.height = `${(100 * r.height) / h}%`;
    });
  });
  wrap.append(stage);

  const caption = el('figcaption', { class: 'mediafig__cap' });
  if (hasBlur) {
    const toggle = el('button', { class: 'btn btn--quiet', text: 'Show the original' });
    let showingBlur = true;
    toggle.addEventListener('click', () => {
      showingBlur = !showingBlur;
      img.src = showingBlur ? blurredUrl : originalUrl;
      toggle.textContent = showingBlur ? 'Show the original' : 'Show the blurred copy';
    });
    caption.append(
      el('span', {
        text: 'Blurred by the gateway, from the same detection that produced '
          + 'the findings — not a second pass that could redact a region it '
          + 'never reported. ',
      }),
      toggle,
    );
  } else if (body.blur_note) {
    caption.append(el('span', { text: body.blur_note }));
  } else {
    caption.append(el('span', { text: 'Rectangles are what the detector fired on.' }));
  }
  wrap.append(caption);
  return wrap;
}

// --------------------------------------------------------------------------- //
function labelTable(status) {
  const wrap = el('div', { class: 'mediabands' });
  const bands = [
    ['explicit', 'Blocks', status.labels?.explicit_block || []],
    ['suggestive', 'Flags', status.labels?.suggestive_flag || []],
    ['face', 'Flags', ['face']],
  ];
  for (const [band, verb, labels] of bands) {
    wrap.append(el('div', { class: 'mediaband' }, [
      el('div', { class: 'mediaband__head' }, [
        el('span', { class: `regdot ${BAND_CLASS[band]}` }),
        el('strong', { text: band }),
        pill(verb, band === 'explicit' ? 'tag--block' : 'tag--flag'),
      ]),
      el('p', { class: 'mediaband__why', text: BAND_NOTE[band] }),
      el('code', { class: 'mediaband__labels', text: labels.join(', ') }),
    ]));
  }
  wrap.append(el('div', { class: 'mediaband mediaband--muted' }, [
    el('div', { class: 'mediaband__head' }, [
      el('strong', { text: 'not reported' }),
    ]),
    el('p', {
      class: 'mediaband__why',
      text: 'The model also finds bellies, feet and armpits, covered or not. '
        + 'None of it is reported. A visible ankle is not a finding, and filling '
        + 'the audit record with them buries the ones that matter.',
    }),
    el('code', {
      class: 'mediaband__labels',
      text: (status.labels?.ignored || []).join(', '),
    }),
  ]));
  return wrap;
}
