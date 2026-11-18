// Shared form filler for the apply content scripts.
//
// Safety rules, enforced by tests/apply_*.test.js:
//  - This file never clicks anything, never calls form.submit() or
//    requestSubmit(), and never dispatches a "submit" event.
//  - A field whose label, name, or id refers to work authorization, sponsorship,
//    citizenship, gender, race, ethnicity, veteran status, disability,
//    pronouns, or a certification/attestation is never touched. It is listed in
//    report.left_for_you. A human answers those fields.
(function (root) {
  'use strict';

  const PROTECTED = new RegExp(
    [
      'authori[sz]ation', 'authori[sz]ed\\s+to\\s+work', 'legally\\s+(authori|eligible|permitted)',
      'eligible\\s+to\\s+work', 'right\\s+to\\s+work', 'sponsor', '\\bvisa\\b', 'citizen',
      '\\bgender', 'transgender', '\\bsex\\b', 'sexual\\s+orientation', 'lgbt', '\\brace\\b',
      'ethnic', 'hispanic', 'latino', 'veteran', 'military', 'disabilit', 'pronoun', 'certif',
      'attest', '\\bi\\s+(agree|acknowledge|confirm|understand|consent)\\b', 'demographic',
      '\\beeo\\b', 'self[-\\s]?identif', '\\bconsent\\b',
    ].join('|'),
    'i'
  );

  const SKIP_TYPES = new Set(['hidden', 'submit', 'button', 'reset', 'image']);
  const TEXT_TYPES = new Set(['', 'text', 'tel', 'email', 'url', 'search']);

  function norm(text) {
    return String(text == null ? '' : text).replace(/[✱*]/g, '').replace(/\s+/g, ' ').trim();
  }

  function isProtectedText(text) {
    return PROTECTED.test(String(text || ''));
  }

  function isControl(el) {
    const type = (el.getAttribute('type') || '').toLowerCase();
    if (el.tagName === 'INPUT') {
      if (SKIP_TYPES.has(type)) return false;
      // react-select keeps an aria-hidden shim input for form validation.
      if (el.getAttribute('aria-hidden') === 'true' && type !== 'file') return false;
    }
    return true;
  }

  function controls(doc) {
    return Array.from(doc.querySelectorAll('input, textarea, select')).filter(isControl);
  }

  function controlType(el) {
    if (el.tagName === 'TEXTAREA') return 'textarea';
    if (el.tagName === 'SELECT') return 'select';
    return (el.getAttribute('type') || 'text').toLowerCase();
  }

  // Text that names a control: its labels, ARIA label, and, for a radio or
  // checkbox, the question that holds the group.
  function describe(el) {
    const doc = el.ownerDocument;
    const labels = [];
    const add = (t) => { const n = norm(t); if (n && !labels.includes(n)) labels.push(n); };
    if (el.labels) Array.from(el.labels).forEach((l) => add(l.textContent));
    else {
      const wrap = el.closest('label');
      if (wrap) add(wrap.textContent);
    }
    const id = el.getAttribute('id');
    if (id) {
      Array.from(doc.querySelectorAll('label[for]'))
        .filter((l) => l.getAttribute('for') === id)
        .forEach((l) => add(l.textContent));
    }
    add(el.getAttribute('aria-label'));
    const by = el.getAttribute('aria-labelledby');
    if (by) by.split(/\s+/).forEach((ref) => { const n = doc.getElementById(ref); if (n) add(n.textContent); });
    let group = '';
    let groupTitle = '';
    const type = controlType(el);
    if (type === 'radio' || type === 'checkbox') {
      const holder = el.closest('.application-question, fieldset, [role="group"], [role="radiogroup"]') || el.closest('li');
      if (holder) {
        group = norm(holder.textContent).slice(0, 400);
        const title = holder.querySelector('legend, .application-label');
        groupTitle = title ? norm(title.textContent) : group;
      }
    }
    const ident = [el.getAttribute('name'), id, el.getAttribute('placeholder')].filter(Boolean).join(' ');
    const display = (groupTitle || labels[0] || norm(el.getAttribute('placeholder')) || el.getAttribute('name') || id || '(unlabeled field)').slice(0, 120);
    return { labels, group, ident, display, all: [group, ...labels, ident].join(' | ') };
  }

  function isProtectedControl(el) {
    return isProtectedText(describe(el).all);
  }

  function groupKey(el) {
    const type = controlType(el);
    const name = el.getAttribute('name');
    if ((type === 'radio' || type === 'checkbox') && name) return type + ':' + name;
    return null;
  }

  function nativeSetter(el) {
    const win = el.ownerDocument.defaultView;
    const proto = el.tagName === 'TEXTAREA' ? win.HTMLTextAreaElement.prototype
      : el.tagName === 'SELECT' ? win.HTMLSelectElement.prototype
        : win.HTMLInputElement.prototype;
    const desc = Object.getOwnPropertyDescriptor(proto, 'value');
    return desc && desc.set;
  }

  // Set a value so that React-controlled inputs register it.
  function setValue(el, value) {
    const win = el.ownerDocument.defaultView;
    const setter = nativeSetter(el);
    if (setter) setter.call(el, value); else el.value = value;
    el.dispatchEvent(new win.Event('input', { bubbles: true }));
    el.dispatchEvent(new win.Event('change', { bubbles: true }));
  }

  function decodeBase64(win, b64) {
    const bin = win.atob(b64);
    const bytes = new win.Uint8Array(bin.length);
    for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
    return bytes;
  }

  // Attach a file from a bundle entry {filename, mime_type, base64}.
  function attachFile(input, entry) {
    const win = input.ownerDocument.defaultView;
    const file = new win.File([decodeBase64(win, entry.base64)], entry.filename, { type: entry.mime_type });
    const transfer = new win.DataTransfer();
    transfer.items.add(file);
    input.files = transfer.files;
    input.dispatchEvent(new win.Event('input', { bubbles: true }));
    input.dispatchEvent(new win.Event('change', { bubbles: true }));
    return !!(input.files && input.files.length > 0);
  }

  function kindMatches(el, kind) {
    const type = controlType(el);
    if (kind === 'file') return type === 'file';
    if (kind === 'textarea') return type === 'textarea';
    return TEXT_TYPES.has(type) || type === 'textarea';
  }

  function usable(el, kind) {
    return !el.disabled && kindMatches(el, kind) && !isProtectedControl(el);
  }

  // Find a field by selectors first, then by label text.
  function findField(doc, spec, kind) {
    for (const selector of spec.selectors || []) {
      let nodes = [];
      try { nodes = Array.from(doc.querySelectorAll(selector)); } catch (e) { nodes = []; }
      const hit = nodes.find((el) => usable(el, kind));
      if (hit) return hit;
    }
    const patterns = spec.labels || [];
    if (patterns.length) {
      return controls(doc).find((el) => {
        if (!usable(el, kind)) return false;
        const d = describe(el);
        return d.labels.some((text) => patterns.some((p) => p.test(text)));
      }) || null;
    }
    return null;
  }

  function isEmpty(el) {
    const type = controlType(el);
    if (type === 'file') return !(el.files && el.files.length);
    if (type === 'radio' || type === 'checkbox') {
      const name = el.getAttribute('name');
      const peers = name
        ? Array.from(el.ownerDocument.querySelectorAll('input')).filter((n) => n.getAttribute('name') === name && n.type === type)
        : [el];
      return !peers.some((n) => n.checked);
    }
    return !String(el.value || '').trim();
  }

  function isRequired(el) {
    return el.required === true || el.getAttribute('aria-required') === 'true';
  }

  function dedupe(list) {
    return Array.from(new Set(list));
  }

  // Fill one form. `map.fields` entries:
  //   {key, kind: 'text', applicant: 'first_name', selectors, labels}
  //   {key: 'resume', kind: 'file', file: 'resume', selectors, labels}
  //   {key: 'cover_letter', kind: 'cover_letter', fileSelectors, fileLabels, textSelectors, textLabels}
  function fillForm(doc, bundle, map) {
    const report = { filled: [], attached: [], left_for_you: [], unfilled_required: [] };
    const applicant = bundle.applicant || {};
    const files = bundle.files || {};

    for (const spec of map.fields) {
      if (spec.kind === 'text') {
        const value = applicant[spec.applicant];
        if (!value) continue;
        const el = findField(doc, spec, 'text');
        if (!el) continue;
        setValue(el, value);
        const combo = el.getAttribute('role') === 'combobox';
        report.filled.push(combo ? spec.key + ' (choose from the list)' : spec.key);
      } else if (spec.kind === 'file') {
        const entry = files[spec.file];
        if (!entry) continue;
        const el = findField(doc, spec, 'file');
        if (el && attachFile(el, entry)) report.attached.push(spec.key);
      } else if (spec.kind === 'cover_letter') {
        const fileEl = files.cover_letter
          ? findField(doc, { selectors: spec.fileSelectors, labels: spec.fileLabels }, 'file') : null;
        if (fileEl) {
          if (attachFile(fileEl, files.cover_letter)) report.attached.push('cover_letter');
          continue;
        }
        if (!bundle.cover_letter_text) continue;
        const textEl = findField(doc, { selectors: spec.textSelectors, labels: spec.textLabels }, 'textarea');
        if (textEl) {
          setValue(textEl, bundle.cover_letter_text);
          report.filled.push('cover_letter (text)');
        }
      }
    }

    const seen = new Set();
    for (const el of controls(doc)) {
      if (el.disabled) continue;
      const key = groupKey(el) || el;
      if (seen.has(key)) continue;
      const d = describe(el);
      if (isProtectedText(d.all)) {
        seen.add(key);
        report.left_for_you.push(d.display);
        continue;
      }
      if (isRequired(el) && isEmpty(el)) {
        seen.add(key);
        report.unfilled_required.push(d.display);
      }
    }
    report.left_for_you = dedupe(report.left_for_you);
    report.unfilled_required = dedupe(report.unfilled_required);
    return report;
  }

  // True when the page has the form of this map. Used to wait for late renders.
  function hasForm(doc, map) {
    return (map.formSelectors || []).some((s) => !!doc.querySelector(s));
  }

  // Poll until `predicate()` is true or `timeoutMs` has passed.
  function waitFor(predicate, opts) {
    const timeoutMs = (opts && opts.timeoutMs) || 0;
    const intervalMs = (opts && opts.intervalMs) || 250;
    const started = Date.now();
    return new Promise((resolve) => {
      const tick = () => {
        if (predicate()) return resolve(true);
        if (Date.now() - started >= timeoutMs) return resolve(false);
        setTimeout(tick, intervalMs);
      };
      tick();
    });
  }

  const CONFIRMATION_TEXT = /thank(s| you) for (applying|your application|submitting)|application (has been |was )?(successfully )?(submitted|received)|we(?:'ve| have) received your application/i;
  const CONFIRMATION_PATH = /\/(confirmation|thanks|thank-you|submitted)(\/|$)/i;

  // Detect the confirmation state that follows a submitted application.
  function detectConfirmation(doc, url) {
    let pathname = '';
    try { pathname = new URL(url).pathname; } catch (e) { pathname = ''; }
    const text = norm(doc.body ? (doc.body.innerText || doc.body.textContent) : '').slice(0, 4000);
    const urlHit = CONFIRMATION_PATH.test(pathname);
    const match = CONFIRMATION_TEXT.exec(text);
    const stillForm = !!doc.querySelector('input[type="email"], input[name="email"], input#email');
    const textHit = !!match && !stillForm;
    if (!urlHit && !textHit) return { confirmed: false, text: '' };
    const snippet = match ? text.slice(Math.max(0, match.index - 20), match.index + 240).trim() : '';
    return { confirmed: true, text: snippet };
  }

  const api = {
    PROTECTED, isProtectedText, describe, setValue, attachFile, findField,
    fillForm, hasForm, waitFor, detectConfirmation,
  };
  root.ApplyFill = api;
  root.ApplyMaps = root.ApplyMaps || {};
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
})(typeof globalThis !== 'undefined' ? globalThis : this);
