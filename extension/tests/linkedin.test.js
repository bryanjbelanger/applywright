const { describe, it, beforeEach } = require('node:test');
const assert = require('node:assert');
const { JSDOM } = require('jsdom');
const fs = require('fs');
const path = require('path');

const root = path.join(__dirname, '..');
const fixture = (name) => fs.readFileSync(path.join(root, 'fixtures', name), 'utf8');
const { extractJob, decodeRedirect } = require('../linkedin/linkedin_extract.js');

function load(name, url) {
  const dom = new JSDOM(fixture(name), { url, runScripts: 'outside-only' });
  return dom;
}

describe('LinkedIn extraction', () => {
  it('view page with redirect apply link', () => {
    const dom = load('linkedin_view_page.html', 'https://www.linkedin.com/jobs/view/4001234567/?trk=x');
    const res = extractJob(dom.window.document, dom.window.location.href);
    assert.ok(res.ok);
    assert.deepStrictEqual(res.job, {
      external_id: '4001234567',
      title: 'Cloud Architect',
      company: 'Acme Corp',
      location: 'Austin, TX',
      remote_status: 'Remote',
      description: 'Design cloud platforms.\n\n- AWS\n- Terraform\n\nLine one\nLine two',
      job_url: 'https://www.linkedin.com/jobs/view/4001234567/',
      apply_type: 'external',
      apply_url: 'https://acme.com/careers/42?utm_source=linkedin',
      source: 'linkedin',
    });
  });

  it('split pane uses currentJobId and ignores the list', () => {
    const dom = load('linkedin_split_pane.html', 'https://www.linkedin.com/jobs/search/?keywords=x&currentJobId=4009876543');
    const { job } = extractJob(dom.window.document, dom.window.location.href);
    assert.strictEqual(job.external_id, '4009876543');
    assert.strictEqual(job.title, 'Platform Engineer');
    assert.strictEqual(job.company, 'Globex');
    assert.strictEqual(job.remote_status, 'Hybrid');
    assert.strictEqual(job.job_url, 'https://www.linkedin.com/jobs/view/4009876543/');
    assert.strictEqual(job.apply_type, 'external');
    assert.strictEqual(job.apply_url, null);
  });

  it('easy apply with older class names', () => {
    const dom = load('linkedin_easy_apply.html', 'https://www.linkedin.com/jobs/view/555/');
    const { job } = extractJob(dom.window.document, dom.window.location.href);
    assert.strictEqual(job.apply_type, 'easy_apply');
    assert.strictEqual(job.apply_url, null);
    assert.strictEqual(job.title, 'Site Reliability Engineer');
    assert.strictEqual(job.company, 'Initech');
    assert.strictEqual(job.location, 'Remote');
    assert.strictEqual(job.description, 'Keep systems up.');
  });

  it('external with redirect URL', () => {
    const dom = load('linkedin_external_redirect.html', 'https://www.linkedin.com/jobs/collections/recommended/?currentJobId=777');
    const { job } = extractJob(dom.window.document, dom.window.location.href);
    assert.strictEqual(job.apply_type, 'external');
    assert.strictEqual(job.apply_url, 'https://boards.greenhouse.io/umbrella/jobs/77');
    assert.strictEqual(job.remote_status, null);
  });

  it('external without URL', () => {
    const dom = load('linkedin_external_no_url.html', 'https://www.linkedin.com/jobs/view/888/');
    const { job } = extractJob(dom.window.document, dom.window.location.href);
    assert.strictEqual(job.apply_type, 'external');
    assert.strictEqual(job.apply_url, null);
  });

  it('fails without a job id or title', () => {
    const dom = load('linkedin_view_page.html', 'https://www.linkedin.com/jobs/search/');
    assert.strictEqual(extractJob(dom.window.document, dom.window.location.href).ok, false);
    const empty = new JSDOM('<body></body>', { url: 'https://www.linkedin.com/jobs/view/1/' });
    assert.strictEqual(extractJob(empty.window.document, empty.window.location.href).ok, false);
  });

  it('rejects unsafe redirect targets', () => {
    const base = 'https://www.linkedin.com/jobs/view/1/';
    assert.strictEqual(decodeRedirect('/redir/redirect?url=javascript%3Aalert(1)', base), null);
    assert.strictEqual(decodeRedirect('/redir/redirect?url=https%3A%2F%2Fwww.linkedin.com%2Fx', base), null);
    assert.strictEqual(decodeRedirect('/redir/redirect', base), null);
  });

  it('does not scroll, click, open, fetch, or navigate', () => {
    const dom = load('linkedin_view_page.html', 'https://www.linkedin.com/jobs/view/4001234567/');
    const w = dom.window;
    const calls = [];
    const spy = (name) => () => calls.push(name);
    w.scrollTo = spy('scrollTo');
    w.scrollBy = spy('scrollBy');
    w.open = spy('open');
    w.fetch = spy('fetch');
    w.XMLHttpRequest = function () { calls.push('xhr'); };
    w.Element.prototype.scrollIntoView = spy('scrollIntoView');
    w.HTMLElement.prototype.click = spy('click');
    w.document.addEventListener('click', () => calls.push('click-event'), true);
    const before = w.location.href;
    extractJob(w.document, w.location.href);
    assert.deepStrictEqual(calls, []);
    assert.strictEqual(w.location.href, before);
  });
});

describe('LinkedIn popup', () => {
  const tick = () => new Promise((r) => setTimeout(r, 10));
  const popupCode = fs.readFileSync(path.join(root, 'linkedin/linkedin_popup.js'), 'utf8');

  async function setup(tabUrl, sendResult) {
    const dom = new JSDOM(
      '<body><button id="btn-linkedin-capture" disabled></button><div id="linkedin-status"></div></body>',
      { runScripts: 'dangerously' }
    );
    const downloads = [];
    const blobs = [];
    dom.window.Blob = class { constructor(parts) { blobs.push(parts.join('')); } };
    dom.window.URL.createObjectURL = () => 'blob:x';
    dom.window.chrome = {
      runtime: { getManifest: () => ({ version: '9.9.9' }) },
      tabs: {
        query: async () => [{ id: 5, url: tabUrl }],
        sendMessage: async () => sendResult,
      },
      downloads: { download: (o) => downloads.push(o) },
    };
    await tick(); // let jsdom fire its own DOMContentLoaded first
    dom.window.eval(popupCode);
    dom.window.document.dispatchEvent(new dom.window.Event('DOMContentLoaded'));
    return { dom, downloads, blobs };
  }
  it('is enabled only on a LinkedIn jobs tab', async () => {
    for (const [url, enabled] of [
      ['https://www.linkedin.com/jobs/view/1/', true],
      ['https://www.linkedin.com/jobs/search/?currentJobId=1', true],
      ['https://www.linkedin.com/feed/', false],
      ['https://app.jobcopilot.com/', false],
      ['https://evil.com/https://www.linkedin.com/jobs/', false],
    ]) {
      const { dom } = await setup(url, null);
      await tick();
      assert.strictEqual(dom.window.document.getElementById('btn-linkedin-capture').disabled, !enabled, url);
    }
  });

  it('downloads one envelope', async () => {
    const job = { external_id: '1', title: 'T', company: 'C', source: 'linkedin', apply_type: 'easy_apply', apply_url: null };
    const { dom, downloads, blobs } = await setup('https://www.linkedin.com/jobs/view/1/', { ok: true, job });
    await tick();
    dom.window.document.getElementById('btn-linkedin-capture').click();
    await tick();
    assert.strictEqual(downloads.length, 1);
    const env = JSON.parse(blobs[0]);
    assert.deepStrictEqual(Object.keys(env.metadata).sort(), ['export_kind', 'exported_at', 'extension_version', 'page_url', 'source']);
    assert.strictEqual(env.metadata.source, 'linkedin');
    assert.strictEqual(env.metadata.export_kind, 'linkedin_capture');
    assert.strictEqual(env.metadata.extension_version, '9.9.9');
    assert.strictEqual(env.metadata.page_url, 'https://www.linkedin.com/jobs/view/1/');
    assert.deepStrictEqual(env.jobs, [job]);
  });

  it('shows the error and downloads nothing on failure', async () => {
    const { dom, downloads } = await setup('https://www.linkedin.com/jobs/view/1/', { ok: false, error: 'nope' });
    await tick();
    dom.window.document.getElementById('btn-linkedin-capture').click();
    await tick();
    assert.strictEqual(downloads.length, 0);
    assert.match(dom.window.document.getElementById('linkedin-status').textContent, /nope/);
  });
});
