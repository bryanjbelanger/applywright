// Shared test setup for the apply form fillers.
const fs = require('fs');
const path = require('path');
const { JSDOM } = require('jsdom');

const ROOT = path.join(__dirname, '..');
const read = (rel) => fs.readFileSync(path.join(ROOT, rel), 'utf8');

const BUNDLE = {
  bundle_version: 1,
  slug: 'example-co-devops',
  job_id: 'job-123',
  company: 'Example Co.',
  title: 'DevOps Engineer',
  job_url: 'https://app.jobcopilot.com/applications/review/9',
  applicant: {
    first_name: 'Ada', last_name: 'Lovelace', full_name: 'Ada Lovelace',
    email: 'ada@example.com', phone: '555-0100', location: 'Somewhere, MI',
    linkedin_url: 'https://linkedin.com/in/ada', github_url: 'https://github.com/ada',
  },
  files: {
    resume: { filename: 'Resume.pdf', mime_type: 'application/pdf', base64: Buffer.from('%PDF-resume').toString('base64') },
    cover_letter: { filename: 'CoverLetter.pdf', mime_type: 'application/pdf', base64: Buffer.from('%PDF-letter').toString('base64') },
  },
  cover_letter_text: 'First paragraph.\n\nSecond paragraph.',
  built_at: '2026-11-17T00:00:00+00:00',
};

// jsdom has no DataTransfer and no writable input.files. Provide both.
function polyfill(win) {
  const store = new WeakMap();
  Object.defineProperty(win.HTMLInputElement.prototype, 'files', {
    configurable: true,
    get() { return store.get(this) || []; },
    set(v) { store.set(this, Array.from(v)); },
  });
  win.DataTransfer = class {
    constructor() { this._files = []; this.items = { add: (f) => this._files.push(f) }; }
    get files() { return this._files; }
  };
}

// Record every click, submit call, and submit event. A fill must record none.
function installSubmitSpies(win) {
  const spy = { clicks: [], submitCalls: 0, requestSubmitCalls: 0, submitEvents: 0, fieldEvents: [] };
  const click = win.HTMLElement.prototype.click;
  win.HTMLElement.prototype.click = function () { spy.clicks.push(this); return click.call(this); };
  win.HTMLFormElement.prototype.submit = function () { spy.submitCalls++; };
  win.HTMLFormElement.prototype.requestSubmit = function () { spy.requestSubmitCalls++; };
  win.document.addEventListener('submit', () => { spy.submitEvents++; }, true);
  win.document.addEventListener('click', (e) => { spy.clicks.push(e.target); }, true);
  win.document.addEventListener('input', (e) => spy.fieldEvents.push(e.target), true);
  win.document.addEventListener('change', (e) => spy.fieldEvents.push(e.target), true);
  return spy;
}

function load(win, files) {
  for (const f of files) win.eval(read(f));
}

function makeWindow(fixture, url, scripts) {
  const html = fixture ? read('fixtures/' + fixture) : '';
  const dom = new JSDOM(`<!doctype html><html><body>${html}</body></html>`, { url, runScripts: 'outside-only', pretendToBeVisual: true });
  polyfill(dom.window);
  const spy = installSubmitSpies(dom.window);
  load(dom.window, ['apply/fill_common.js', ...scripts]);
  return { dom, win: dom.window, doc: dom.window.document, spy };
}

function assertNoSubmit(assert, spy) {
  assert.deepStrictEqual(spy.clicks, [], 'nothing was clicked');
  assert.strictEqual(spy.submitCalls, 0);
  assert.strictEqual(spy.requestSubmitCalls, 0);
  assert.strictEqual(spy.submitEvents, 0);
}

module.exports = { BUNDLE, makeWindow, assertNoSubmit, read, load, polyfill };
