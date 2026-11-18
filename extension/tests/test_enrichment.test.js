const assert = require('node:assert');
const { test } = require('node:test');
const fs = require('fs');
const path = require('path');
const { JSDOM } = require('jsdom');

// Load exporter code
const jsPath = path.join(__dirname, '..', 'extraction', 'extract_jobs.js');
const normalizePath = path.join(__dirname, '..', 'extraction', 'normalize.js');
const selectorsPath = path.join(__dirname, '..', 'extraction', 'selectors.js');

globalThis.ApplywrightExtension = {};
eval(fs.readFileSync(normalizePath, 'utf8'));
eval(fs.readFileSync(selectorsPath, 'utf8'));
eval(fs.readFileSync(jsPath, 'utf8'));

const extract = (doc, url) => globalThis.ApplywrightExtension.extract.extractCurrentPage(doc, url);

function getDoc(htmlContent) {
  const dom = new JSDOM(`<!DOCTYPE html><html><body>${htmlContent}</body></html>`);
  return dom.window.document;
}

test('URL Validation tests', (t) => {
  const doc = getDoc('<div class="job-title">T</div><div class="company-name">C</div><div data-testid="job-description">D</div>');
  
  // Valid
  assert.ok(!extract(doc, 'https://app.jobcopilot.com/applications/review/123').error);
  assert.ok(!extract(doc, 'https://app.jobcopilot.com/applications/review/123/').error);
  
  // Invalid schema/host
  assert.match(extract(doc, 'http://app.jobcopilot.com/applications/review/123').error, /Invalid JobCopilot review URL/);
  assert.match(extract(doc, 'https://other.com/applications/review/123').error, /Invalid JobCopilot review URL/);
  
  // Bad paths
  assert.match(extract(doc, 'https://app.jobcopilot.com/applications/connect/123').error, /Invalid JobCopilot review URL/);
  assert.match(extract(doc, 'https://app.jobcopilot.com/applications/review/123/extra').error, /Invalid JobCopilot review URL/);
  assert.match(extract(doc, 'https://app.jobcopilot.com/123').error, /Invalid JobCopilot review URL/);
  
  // Query and fragment accepted but canonicalized
  let res = extract(doc, 'https://app.jobcopilot.com/applications/review/123?q=1');
  assert.ok(!res.error);
  assert.strictEqual(res.jobs[0].job_url, 'https://app.jobcopilot.com/applications/review/123');
  
  res = extract(doc, 'https://app.jobcopilot.com/applications/review/123#hash');
  assert.ok(!res.error);
  assert.strictEqual(res.jobs[0].job_url, 'https://app.jobcopilot.com/applications/review/123');

  // Encoded / invalid chars
  assert.match(extract(doc, 'https://app.jobcopilot.com/applications/review/12%2F3').error, /Invalid JobCopilot review URL/);
  assert.match(extract(doc, 'https://app.jobcopilot.com/applications/review/12 3').error, /Invalid JobCopilot review URL/);
  
  assert.match(extract(doc, 'https://user:pass@app.jobcopilot.com/applications/review/123').error, /Invalid JobCopilot review URL/);
  assert.match(extract(doc, 'https://app.jobcopilot.com:8080/applications/review/123').error, /Invalid JobCopilot review URL/);

  // Dot segments
  assert.match(extract(doc, 'https://app.jobcopilot.com/applications/review/abc/../123').error, /Invalid JobCopilot review URL/);
  assert.match(extract(doc, 'https://app.jobcopilot.com/applications/review/%2e%2e/123').error, /Invalid JobCopilot review URL/);
});

test('Identity tests', (t) => {
  // Unrelated data-id values do not cause conflict
  let html = `<div class="job-title">T</div><div class="company-name">C</div>
              <div data-id="unrelated-999"></div>
              <div data-id="unrelated-888"></div>
              <div data-testid="job-description">D</div>`;
  let res = extract(getDoc(html), 'https://app.jobcopilot.com/applications/review/123');
  assert.ok(!res.error);
  assert.strictEqual(res.jobs[0].external_id, '123');
  
  // data-job-id is read and compared
  html = `<div class="job-title">T</div><div class="company-name">C</div>
          <div data-job-id="123"></div>
          <div data-testid="job-description">D</div>`;
  res = extract(getDoc(html), 'https://app.jobcopilot.com/applications/review/123');
  assert.ok(!res.error);
  assert.strictEqual(res.jobs[0].external_id, '123');
  
  // data-application-id is read and compared
  html = `<div class="job-title">T</div><div class="company-name">C</div>
          <div data-application-id="123"></div>
          <div data-testid="job-description">D</div>`;
  res = extract(getDoc(html), 'https://app.jobcopilot.com/applications/review/123');
  assert.ok(!res.error);
  
  // conflicting trusted IDs fail
  html = `<div class="job-title">T</div><div class="company-name">C</div>
          <div data-job-id="999"></div>
          <div data-testid="job-description">D</div>`;
  res = extract(getDoc(html), 'https://app.jobcopilot.com/applications/review/123');
  assert.match(res.error, /identity mismatch/);
  
  html = `<div class="job-title">T</div><div class="company-name">C</div>
          <div data-job-id="123"></div>
          <div data-application-id="999"></div>
          <div data-testid="job-description">D</div>`;
  res = extract(getDoc(html), 'https://app.jobcopilot.com/applications/review/123');
  assert.match(res.error, /identity mismatch/);
});

test('Required content tests', (t) => {
  let res = extract(getDoc('<div class="job-title">T</div><div data-testid="job-description">D</div>'), 'https://app.jobcopilot.com/applications/review/123');
  assert.match(res.error, /Missing required title or company/);
  
  res = extract(getDoc('<div class="company-name">C</div><div data-testid="job-description">D</div>'), 'https://app.jobcopilot.com/applications/review/123');
  assert.match(res.error, /Missing required title or company/);
  
  res = extract(getDoc('<div class="job-title">T</div><div class="company-name">C</div>'), 'https://app.jobcopilot.com/applications/review/123');
  assert.match(res.error, /Could not locate a reliable description container/);
  
  res = extract(getDoc('<form action="/login"><input type="password"></form>'), 'https://app.jobcopilot.com/applications/review/123');
  assert.match(res.error, /Login page/);
});

test('Description extraction strategies', (t) => {

  // Test direct semantic matches first
  let html = `<div class="job-title">T</div><div class="company-name">C</div>
              <div data-testid="job-description">Semantic match</div>`;
  let res = extract(getDoc(html), 'https://app.jobcopilot.com/applications/review/123');
  assert.strictEqual(res.jobs[0].description, 'Semantic match');
  
  // Test heading fallback explicitly bounded
  html = `
<div class="wrapper">
  <div class="job-title">T</div><div class="company-name">C</div>
  <h2>Job Description</h2>
  <p>Real description</p>
  <h2>Application Process</h2>
  <p>Unrelated trailing content</p>
</div>`;
  res = extract(getDoc(html), 'https://app.jobcopilot.com/applications/review/123');
  assert.strictEqual(res.jobs[0].description, 'Job Description\n\nReal description');
  
  // Test multi-sibling bounded extraction
  html = `
<div class="wrapper">
  <div class="job-title">T</div>
  <div class="company-name">C</div>
  <h2>Job Description</h2>
  <p>Paragraph one</p>
  <p>Paragraph two</p>
  <ul>
    <li>Requirement one</li>
    <li>Requirement two</li>
  </ul>
  <h2>Application Process</h2>
  <p>Unrelated trailing content</p>
</div>`;
  res = extract(getDoc(html), 'https://app.jobcopilot.com/applications/review/123');
  assert.strictEqual(res.jobs[0].description, 'Job Description\n\nParagraph one\n\nParagraph two\n\n- Requirement one\n- Requirement two');

  // Test broad region is not exported wholesale
  html = `
<div class="job-details" role="region">
  <div class="job-title">T</div>
  <div class="company-name">C</div>
  <button class="apply">Apply</button>
  <h2>Job Description</h2>
  <p>Real description</p>
  <h2>Application Process</h2>
  <p>Unrelated trailing content</p>
</div>`;
  res = extract(getDoc(html), 'https://app.jobcopilot.com/applications/review/123');
  // Because it's not accepted wholesale, it falls back to heading-anchored bounded extraction,
  // which stops before "Application Process" (an H2).
  assert.strictEqual(res.jobs[0].description, 'Job Description\n\nReal description');
});

test('Description structural formatting and cleanup', (t) => {
  const html = `
    <div class="job-title">T</div><div class="company-name">C</div>
    <div data-testid="job-description">
      <nav>Hidden nav</nav>
      <div style="display: none;">Secret text</div>
      <form><button>Apply Now</button></form>
      <div><button>Review Application</button></div>
      <h1>Header 1</h1>
      <p>Paragraph 1</p>
      <ul>
        <li>Item 1</li>
        <li>Item 2</li>
      </ul>
      <ol>
        <li>First</li>
        <li>Second</li>
      </ol>
      <svg></svg>
      <script>alert(1);</script>
    </div>
  `;
  const res = extract(getDoc(html), 'https://app.jobcopilot.com/applications/review/123');
  const expectedDesc = 'Header 1\n\nParagraph 1\n\n- Item 1\n- Item 2\n\n1. First\n2. Second';
  assert.strictEqual(res.jobs[0].description, expectedDesc);
});

test('Export envelope and diagnostics', (t) => {
  const html = `<div class="job-title">T</div><div class="company-name">C</div><div data-testid="job-description">D</div>`;
  const res = extract(getDoc(html), 'https://app.jobcopilot.com/applications/review/123');
  assert.strictEqual(res.metadata.export_kind, 'current_job_enrichment');
  assert.strictEqual(res.jobs[0].job_url, 'https://app.jobcopilot.com/applications/review/123');
  assert.strictEqual(res.diagnostics.strategy, 'structural');
});
