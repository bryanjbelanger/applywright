const { describe, it, after } = require('node:test');
const assert = require('node:assert');
const { JSDOM } = require('jsdom');
const { BUNDLE, makeWindow, assertNoSubmit, read, load } = require('./apply_harness');

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const plain = (v) => JSON.parse(JSON.stringify(v));

function contentWindow(system, url) {
  const ctx = makeWindow(null, url, []);
  const sent = [];
  let listener = null;
  ctx.win.chrome = {
    runtime: {
      onMessage: { addListener: (fn) => { listener = fn; } },
      sendMessage: (m) => { sent.push(plain(m)); },
    },
  };
  load(ctx.win, [`apply/${system}.js`, 'apply/content_apply.js']);
  return { ...ctx, sent, send: (m) => listener(m) };
}

describe('content script', () => {
  it('waits for a late-rendered form, fills it, and reports', async () => {
    const c = contentWindow('ashby', 'https://jobs.ashbyhq.com/acme/1/application');
    c.win.ApplyMaps.ashby.waitMs = 3000;
    c.send({ action: 'apply_fill', request_id: 'r1', bundle: BUNDLE });
    await sleep(300);
    assert.strictEqual(c.sent.length, 0, 'no report before the form exists');
    c.doc.body.innerHTML = require('fs').readFileSync(require('path').join(__dirname, '../fixtures/ashby_form.html'), 'utf8');
    await sleep(700);
    assert.strictEqual(c.sent.length, 1);
    assert.strictEqual(c.sent[0].action, 'apply_report');
    assert.strictEqual(c.sent[0].request_id, 'r1');
    assert.strictEqual(c.sent[0].system, 'ashby');
    assert.ok(c.sent[0].report.filled.includes('email'));
    assert.strictEqual(c.doc.querySelector('#_systemfield_email').value, 'ada@example.com');
    assertNoSubmit(assert, c.spy);
  });

  it('stays silent when no form appears within the bounded wait', async () => {
    const c = contentWindow('greenhouse', 'https://job-boards.greenhouse.io/x/jobs/1');
    c.win.ApplyMaps.greenhouse.waitMs = 300;
    c.send({ action: 'apply_fill', request_id: 'r2', bundle: BUNDLE });
    await sleep(800);
    assert.strictEqual(c.sent.length, 0);
  });

  it('manifest registers the three systems, greenhouse in all frames, and keeps the JobCopilot entry', () => {
    const m = JSON.parse(read('manifest.json'));
    const find = (host) => m.content_scripts.find((e) => e.matches.includes(host));
    assert.deepStrictEqual(find('https://app.jobcopilot.com/*').js, ['extraction/normalize.js', 'extraction/selectors.js', 'extraction/extract_jobs.js', 'content.js']);
    assert.strictEqual(find('https://boards.greenhouse.io/*').all_frames, true);
    assert.strictEqual(find('https://job-boards.greenhouse.io/*').all_frames, true);
    assert.ok(find('https://jobs.lever.co/*'));
    assert.ok(find('https://jobs.ashbyhq.com/*'));
    for (const h of ['https://boards.greenhouse.io/*', 'https://job-boards.greenhouse.io/*', 'https://jobs.lever.co/*', 'https://jobs.ashbyhq.com/*']) {
      assert.ok(m.host_permissions.includes(h), h);
    }
  });

  it('source never calls submit, requestSubmit, or click', () => {
    for (const f of ['fill_common.js', 'greenhouse.js', 'lever.js', 'ashby.js', 'content_apply.js']) {
      const code = read('apply/' + f).split('\n').filter((l) => !l.trim().startsWith('//')).join('\n');
      assert.ok(!/\.click\s*\(|\.submit\s*\(|requestSubmit|dispatchEvent\(\s*new[^)]*['"]submit['"]/.test(code), f);
    }
  });
});

describe('confirmation detection', () => {
  const detect = (html, url) => {
    const c = makeWindow(null, url, []);
    c.doc.body.innerHTML = html;
    return plain(c.win.ApplyFill.detectConfirmation(c.doc, url));
  };
  it('detects a Greenhouse confirmation URL', () => {
    assert.strictEqual(detect('<p>x</p>', 'https://job-boards.greenhouse.io/a/jobs/1/confirmation').confirmed, true);
  });
  it('detects a Lever thanks URL', () => {
    assert.strictEqual(detect('<p>x</p>', 'https://jobs.lever.co/a/1/thanks').confirmed, true);
  });
  it('detects a thank-you message and returns its text', () => {
    const r = detect('<h1>Thank you for applying.</h1><p>We will be in touch.</p>', 'https://jobs.ashbyhq.com/a/1/application');
    assert.strictEqual(r.confirmed, true);
    assert.match(r.text, /Thank you for applying/);
  });
  it('does not detect a confirmation on an unfilled form', () => {
    assert.strictEqual(detect('<form><input type="email"><p>Thank you for applying early</p></form>', 'https://jobs.ashbyhq.com/a/1/application').confirmed, false);
    assert.strictEqual(detect('<p>Apply now</p>', 'https://jobs.lever.co/a/1/apply').confirmed, false);
  });
  it('the content script reports a confirmation frame', () => {
    const c = contentWindow('lever', 'https://jobs.lever.co/a/1/thanks');
    c.send({ action: 'apply_check_confirmation', request_id: 'c1' });
    assert.strictEqual(c.sent.length, 1);
    assert.strictEqual(c.sent[0].action, 'apply_confirmation');
  });
  it('the content script stays silent when there is no confirmation', () => {
    const c = contentWindow('lever', 'https://jobs.lever.co/a/1/apply');
    c.send({ action: 'apply_check_confirmation', request_id: 'c1' });
    assert.strictEqual(c.sent.length, 0);
  });
});

describe('popup apply section', () => {
  const windows = [];
  // Close each window so the 25 s fill timer does not keep the test process alive.
  after(() => windows.forEach((w) => w.close()));

  async function popup({ stored } = {}) {
    const dom = new JSDOM(`<html><body>
      <button id="btn-scan"></button><button id="btn-scan-auto"></button><button id="btn-cancel"></button>
      <button id="btn-enrich"></button><button id="btn-export"></button><button id="btn-copy"></button>
      <button id="btn-diagnostics"></button><button id="btn-clear"></button><div id="status"></div>
      <input type="file" id="batch-queue-file"><button id="btn-batch-load"></button><button id="btn-batch-start"></button>
      <button id="btn-batch-resume"></button><button id="btn-batch-cancel"></button><button id="btn-batch-export"></button><div id="batch-status"></div>
      <input type="file" id="apply-bundle-file"><button id="btn-apply-load"></button>
      <button id="btn-apply-fill"></button><button id="btn-apply-save"></button>
      <div id="apply-status"></div><ul id="apply-report"></ul>
    </body></html>`, { runScripts: 'outside-only', url: 'https://example.org/' });
    const w = dom.window;
    windows.push(w);
    const calls = { set: [], tabMessages: [], downloads: [] };
    let onMessage = null;
    w.chrome = {
      storage: { local: { get: async () => (stored ? { applyBundle: stored } : {}), set: async (d) => { calls.set.push(d); }, remove: async () => {} } },
      runtime: { sendMessage: (m, cb) => { if (cb) cb({}); }, onMessage: { addListener: (fn) => { onMessage = fn; } } },
      tabs: {
        query: async () => [{ id: 7, url: 'https://employer.example.com/careers/1' }],
        sendMessage: async (id, m) => { calls.tabMessages.push({ id, m: plain(m) }); },
        connect: () => ({ onMessage: { addListener() {} }, onDisconnect: { addListener() {} }, postMessage() {} }),
      },
      downloads: { download: (o) => calls.downloads.push(o) },
    };
    // Let jsdom fire its own DOMContentLoaded first, so the popup starts once.
    await sleep(10);
    w.eval(read('popup.js'));
    w.document.dispatchEvent(new w.Event('DOMContentLoaded'));
    return { w, doc: w.document, calls, deliver: (m) => onMessage(m) };
  }

  it('loads a bundle file into storage and shows slug, company, and title', async () => {
    const p = await popup();
    await sleep(20);
    const input = p.doc.getElementById('apply-bundle-file');
    Object.defineProperty(input, 'files', { value: [new p.w.File([JSON.stringify(BUNDLE)], 'bundle.json')] });
    p.doc.getElementById('btn-apply-load').click();
    await sleep(50);
    const stored = p.calls.set.filter((d) => d.applyBundle);
    assert.strictEqual(stored.length, 1);
    assert.strictEqual(stored[0].applyBundle.slug, 'example-co-devops');
    const text = p.doc.getElementById('apply-status').textContent;
    assert.ok(text.includes('example-co-devops') && text.includes('Example Co.') && text.includes('DevOps Engineer'));
    assert.strictEqual(p.doc.getElementById('btn-apply-fill').disabled, false);
  });

  it('rejects a file that is not an apply bundle', async () => {
    const p = await popup();
    await sleep(20);
    const input = p.doc.getElementById('apply-bundle-file');
    Object.defineProperty(input, 'files', { value: [new p.w.File(['{"a":1}'], 'x.json')] });
    p.doc.getElementById('btn-apply-load').click();
    await sleep(50);
    assert.strictEqual(p.calls.set.filter((d) => d.applyBundle).length, 0);
    assert.match(p.doc.getElementById('apply-status').textContent, /Not an apply bundle/);
  });

  it('sends the stored bundle to the active tab and shows the report', async () => {
    const p = await popup({ stored: BUNDLE });
    await sleep(20);
    const fill = p.doc.getElementById('btn-apply-fill');
    assert.strictEqual(fill.disabled, false);
    fill.click();
    await sleep(20);
    const sent = p.calls.tabMessages.find((t) => t.m.action === 'apply_fill');
    assert.ok(sent);
    assert.strictEqual(sent.id, 7);
    assert.strictEqual(sent.m.bundle.slug, 'example-co-devops');
    p.deliver({
      action: 'apply_report', request_id: sent.m.request_id, system: 'lever',
      report: { filled: ['email'], attached: ['resume'], left_for_you: ['Gender'], unfilled_required: ['Pronouns'] },
    });
    const items = Array.from(p.doc.querySelectorAll('#apply-report li')).map((l) => l.textContent);
    assert.deepStrictEqual(items, [
      'Filled: email', 'Attached: resume', 'Left for you: Gender', 'Required and still empty: Pronouns',
    ]);
  });

  it('ignores a report for another request', async () => {
    const p = await popup({ stored: BUNDLE });
    await sleep(20);
    p.doc.getElementById('btn-apply-fill').click();
    await sleep(20);
    p.deliver({ action: 'apply_report', request_id: 'other', system: 'lever', report: { filled: ['x'], attached: [], left_for_you: [], unfilled_required: [] } });
    assert.strictEqual(p.doc.querySelectorAll('#apply-report li').length, 0);
  });

  it('offers a submission record only after a confirmation, and downloads it', async () => {
    const p = await popup({ stored: BUNDLE });
    await sleep(20);
    assert.ok(p.calls.tabMessages.some((t) => t.m.action === 'apply_check_confirmation'));
    const save = p.doc.getElementById('btn-apply-save');
    assert.strictEqual(save.disabled, true);
    p.deliver({ action: 'apply_confirmation', request_id: 'x', system: 'greenhouse', frame_url: 'https://job-boards.greenhouse.io/a/jobs/1/confirmation', text: 'Thank you for applying.' });
    assert.strictEqual(save.disabled, false);
    save.click();
    assert.strictEqual(p.calls.downloads.length, 1);
    const dl = p.calls.downloads[0];
    assert.strictEqual(dl.filename, 'submission-example-co-devops.json');
    const record = JSON.parse(decodeURIComponent(dl.url.split(',')[1]));
    assert.strictEqual(record.job_id, 'job-123');
    assert.strictEqual(record.package_slug, 'example-co-devops');
    assert.strictEqual(record.application_source_url, 'https://employer.example.com/careers/1');
    assert.strictEqual(record.confirmation_text, 'Thank you for applying.');
    assert.ok(!Number.isNaN(Date.parse(record.submitted_at)));
    assert.deepStrictEqual(Object.keys(record).sort(), ['application_source_url', 'confirmation_text', 'job_id', 'package_slug', 'submitted_at']);
  });

  it('keeps the save button off when no bundle is loaded', async () => {
    const p = await popup();
    await sleep(20);
    p.deliver({ action: 'apply_confirmation', request_id: 'x', system: 'lever', frame_url: 'u', text: 't' });
    assert.strictEqual(p.doc.getElementById('btn-apply-save').disabled, true);
  });
});
