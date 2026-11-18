const { describe, it, before } = require('node:test');
const assert = require('node:assert');
const { JSDOM } = require('jsdom');

describe('ApplywrightExtension', () => {

  before(() => {
    globalThis.ApplywrightExtension = {};
    require('../extraction/normalize.js');
    require('../extraction/selectors.js');
    require('../extraction/extract_jobs.js');
  });

  it('normalizes text and urls', () => {
    const { normalize } = globalThis.ApplywrightExtension;
    assert.strictEqual(normalize.cleanText('  Hello   World  '), 'Hello World');
    assert.strictEqual(normalize.cleanText('N/A'), null);
    
    const url = normalize.canonicalizeUrl('https://example.com/job?utm_source=foo&id=123', 'https://example.com');
    assert.strictEqual(url, 'https://example.com/job?id=123');
    
    // Relative URL resolution
    const relativeUrl = normalize.canonicalizeUrl('/jobs/123', 'https://app.jobcopilot.com/');
    assert.strictEqual(relativeUrl, 'https://app.jobcopilot.com/jobs/123');
    
    // Unsafe URL rejection
    assert.strictEqual(normalize.canonicalizeUrl('javascript:alert(1)', 'https://app.jobcopilot.com/'), null);
  });

  it('extracts normal cards and handles external IDs', () => {
    const dom = new JSDOM(`
      <html>
        <body>
          <article data-testid="job-card" data-job-id="ext123">
            <h2 data-testid="job-title">Software Engineer</h2>
            <div data-testid="company-name">Acme Corp</div>
            <a data-testid="job-link" href="/jobs/ext123?source=test">Link</a>
            <div data-testid="application-status">Applied</div>
          </article>
        </body>
      </html>
    `, { url: "https://app.jobcopilot.com/" });
    
    const { extract } = globalThis.ApplywrightExtension;
    const raw = extract.scanDOM(dom.window.document, "https://app.jobcopilot.com/", "applied");
    const processed = extract.processRecords(raw, "https://app.jobcopilot.com/");
    
    assert.strictEqual(processed.metadata.detected_count, 1);
    assert.strictEqual(processed.metadata.exported_count, 1);
    assert.strictEqual(processed.jobs[0].title, "Software Engineer");
    assert.strictEqual(processed.jobs[0].company, "Acme Corp");
    assert.strictEqual(processed.jobs[0].external_id, "ext123");
    assert.strictEqual(processed.jobs[0].application_status, "applied");
    assert.strictEqual(processed.jobs[0].job_url, "https://app.jobcopilot.com/jobs/ext123");
  });

  it('rejects cards missing required fields', () => {
    const dom = new JSDOM(`
      <html>
        <body>
          <article class="job-card">
            <!-- Missing title -->
            <div class="company-name">Acme Corp</div>
          </article>
          <article class="job-card">
            <h2 class="job-title">Apply</h2> <!-- Button text treated as title -->
            <div class="company-name">Acme Corp</div>
          </article>
        </body>
      </html>
    `, { url: "https://app.jobcopilot.com/" });
    
    const { extract } = globalThis.ApplywrightExtension;
    const raw = extract.scanDOM(dom.window.document, "https://app.jobcopilot.com/");
    const processed = extract.processRecords(raw, "https://app.jobcopilot.com/");
    
    assert.strictEqual(processed.metadata.detected_count, 2);
    assert.strictEqual(processed.metadata.exported_count, 0); // Both rejected
    assert.strictEqual(processed.metadata.invalid_count, 2);
  });

  it('handles duplicates (identical and conflicting)', () => {
    const dom = new JSDOM(`
      <html>
        <body>
          <!-- Record 1 (base) -->
          <article data-testid="job-card" data-job-id="dup1">
            <h2 data-testid="job-title">Dev</h2>
            <div data-testid="company-name">Corp</div>
            <div data-testid="salary">$100k</div>
          </article>
          
          <!-- Record 2 (identical duplicate) -->
          <article data-testid="job-card" data-job-id="dup1">
            <h2 data-testid="job-title">Dev</h2>
            <div data-testid="company-name">Corp</div>
            <div data-testid="salary">$100k</div>
          </article>
          
          <!-- Record 3 (conflicting duplicate - more fields) -->
          <article data-testid="job-card" data-job-id="dup1">
            <h2 data-testid="job-title">Dev</h2>
            <div data-testid="company-name">Corp</div>
            <div data-testid="salary">$100k</div>
            <div data-testid="job-location">Remote</div>
          </article>
        </body>
      </html>
    `, { url: "https://app.jobcopilot.com/" });
    
    const { extract } = globalThis.ApplywrightExtension;
    const raw = extract.scanDOM(dom.window.document, "https://app.jobcopilot.com/");
    const processed = extract.processRecords(raw, "https://app.jobcopilot.com/");
    
    assert.strictEqual(processed.metadata.detected_count, 3);
    assert.strictEqual(processed.metadata.exported_count, 1);
    assert.strictEqual(processed.metadata.duplicate_count, 2);
    assert.strictEqual(processed.metadata.warning_count, 1); // Conflicting duplicate generates warning
    assert.strictEqual(processed.jobs[0].location, "Remote"); // Picked the richer record
  });
  
  it('does not export cookies, storage, or html in jobs or diagnostics', () => {
      const dom = new JSDOM(`
      <html>
        <body>
          <article data-testid="job-card" data-job-id="ext123">
            <h2 data-testid="job-title">Software Engineer</h2>
            <div data-testid="company-name">Acme Corp</div>
          </article>
        </body>
      </html>
    `, { url: "https://app.jobcopilot.com/" });
    
    const { extract } = globalThis.ApplywrightExtension;
    const raw = extract.scanDOM(dom.window.document, "https://app.jobcopilot.com/");
    const processed = extract.processRecords(raw, "https://app.jobcopilot.com/");
    
    const jobsJson = JSON.stringify(processed.jobs);
    assert.ok(!jobsJson.includes('<html>'));
    assert.ok(!jobsJson.includes('cookie'));
    
    const diagnosticsJson = JSON.stringify(processed.diagnostics);
    assert.ok(!diagnosticsJson.includes('<html>'));
    assert.ok(!diagnosticsJson.includes('cookie'));
    assert.ok(!diagnosticsJson.includes('job_data'));
  });

  it('handles JobCopilot live DOM structure', () => {
    const dom = new JSDOM(`
      <html>
        <body>
          <div class="px-2 flex flex-col gap-1 overflow-y-auto at-card pb-2">
            <div class="flex flex-col p-2 shadow-card rounded-[10px]">
              <div class="flex flex-row gap-2 items-center">
                <div class="flex flex-col gap-1">
                  <p class="font-bold text-sm cursor-pointer break-words">Salesforce Architect</p>
                  <p>Nozomi Networks</p>
                </div>
              </div>
              <a href="/applications/review/36276634">
                <button>Review Application</button>
              </a>
              <a href="/applications/connect/36276634"></a>
            </div>
          </div>
        </body>
      </html>
    `, { url: "https://app.jobcopilot.com/" });
    
    const { extract } = globalThis.ApplywrightExtension;
    const raw = extract.scanDOM(dom.window.document, "https://app.jobcopilot.com/");
    const processed = extract.processRecords(raw, "https://app.jobcopilot.com/");
    
    assert.strictEqual(processed.metadata.detected_count, 1);
    assert.strictEqual(processed.metadata.exported_count, 1);
    assert.strictEqual(processed.jobs[0].title, "Salesforce Architect");
    assert.strictEqual(processed.jobs[0].company, "Nozomi Networks");
    assert.strictEqual(processed.jobs[0].external_id, "36276634");
    assert.strictEqual(processed.jobs[0].job_url, "https://app.jobcopilot.com/applications/review/36276634");
    assert.strictEqual(processed.jobs[0].application_status, "saved");
  });

  it('scopes extraction to active saved list', async () => {
    const dom = new JSDOM(`
      <html>
        <body>
          <div class="at-card" id="visible-list">
            <div class="shadow-card" data-job-id="v1"><h2 class="job-title">V1</h2><div class="company-name">C</div></div>
            <div class="shadow-card" data-job-id="v2"><h2 class="job-title">V2</h2><div class="company-name">C</div></div>
            <div class="shadow-card" data-job-id="v3"><h2 class="job-title">V3</h2><div class="company-name">C</div></div>
          </div>
          <div class="at-card" id="hidden-list" style="display: none;">
            <div class="shadow-card" data-job-id="h1"><h2 class="job-title">H1</h2><div class="company-name">C</div></div>
            <div class="shadow-card" data-job-id="h2"><h2 class="job-title">H2</h2><div class="company-name">C</div></div>
          </div>
          <div class="shadow-card" data-job-id="outside1"><h2 class="job-title">O1</h2><div class="company-name">C</div></div>
        </body>
      </html>
    `, { url: "https://app.jobcopilot.com/" });
    
    const doc = dom.window.document;
    const visibleList = doc.getElementById('visible-list');
    const hiddenList = doc.getElementById('hidden-list');
    
    visibleList.getClientRects = () => [{width: 100, height: 100}];
    visibleList.getBoundingClientRect = () => ({width: 100, height: 100});
    Object.defineProperty(visibleList, 'clientHeight', { value: 100 });
    
    hiddenList.getClientRects = () => [];
    hiddenList.getBoundingClientRect = () => ({width: 0, height: 0});
    Object.defineProperty(hiddenList, 'clientHeight', { value: 0 });
    
    globalThis.window = dom.window;
    globalThis.document = doc;
    globalThis.location = dom.window.location;
    
    globalThis.chrome = {
      runtime: {
        onMessage: { addListener: () => {} },
        onConnect: { addListener: () => {} }
      }
    };
    
    require('../content.js');
    const { content } = globalThis.ApplywrightExtension;
    
    const result = await content.doScan();
    assert.strictEqual(result.metadata.detected_count, 3);
    assert.strictEqual(result.metadata.exported_count, 3);
    assert.strictEqual(result.diagnostics.list_container.selected_card_count, 3);
  });

  it('returns zero jobs and warning if no active list', async () => {
    const dom = new JSDOM(`
      <html>
        <body>
          <div class="shadow-card" data-job-id="outside1"><h2 class="job-title">O1</h2><div class="company-name">C</div></div>
        </body>
      </html>
    `, { url: "https://app.jobcopilot.com/" });
    
    globalThis.window = dom.window;
    globalThis.document = dom.window.document;
    globalThis.location = dom.window.location;
    globalThis.window.getComputedStyle = () => ({ display: 'block', visibility: 'visible' });
    
    globalThis.chrome = {
      runtime: {
        onMessage: { addListener: () => {} },
        onConnect: { addListener: () => {} }
      }
    };
    
    require('../content.js');
    const { content } = globalThis.ApplywrightExtension;
    const result = await content.doScan("saved");
    
    assert.strictEqual(result.metadata.detected_count, 0);
    assert.strictEqual(result.metadata.exported_count, 0);
    assert.strictEqual(result.diagnostics.warnings[0], "No visible Saved JobCopilot application list was found.");
  });

  it('selects JobCopilot list by application status correctly', async () => {
    const dom = new JSDOM(`
      <html>
        <body>
          <div class="column-wrapper">
            <h2>Saved (196)</h2>
            <div class="at-card" id="saved-list">
              <div class="shadow-card" data-job-id="s1"><h2 class="job-title">S1</h2><div class="company-name">C</div></div>
            </div>
          </div>
          <div class="column-wrapper">
            <h2>Applied (15)</h2>
            <div class="at-card" id="applied-list">
              <div class="shadow-card" data-job-id="a1"><h2 class="job-title">A1</h2><div class="company-name">C</div></div>
              <div class="shadow-card" data-job-id="a2"><h2 class="job-title">A2</h2><div class="company-name">C</div></div>
            </div>
          </div>
        </body>
      </html>
    `, { url: "https://app.jobcopilot.com/" });
    
    const doc = dom.window.document;
    const savedList = doc.getElementById('saved-list');
    const appliedList = doc.getElementById('applied-list');
    
    savedList.getClientRects = () => [{width: 100, height: 100}];
    savedList.getBoundingClientRect = () => ({width: 100, height: 100});
    Object.defineProperty(savedList, 'clientHeight', { value: 100 });
    Object.defineProperty(savedList, 'scrollHeight', { value: 100 });
    Object.defineProperty(savedList, 'scrollTop', { value: 0, writable: true });
    
    appliedList.getClientRects = () => [{width: 500, height: 500}];
    appliedList.getBoundingClientRect = () => ({width: 500, height: 500});
    Object.defineProperty(appliedList, 'clientHeight', { value: 500 });
    
    globalThis.window = dom.window;
    globalThis.document = doc;
    globalThis.location = dom.window.location;
    globalThis.window.getComputedStyle = () => ({ display: 'block', visibility: 'visible' });
    
    require('../content.js');
    const { content } = globalThis.ApplywrightExtension;
    
    let result = await content.doScan("saved");
    assert.strictEqual(result.metadata.detected_count, 1);
    assert.strictEqual(result.jobs[0].title, "S1");
    assert.strictEqual(result.jobs[0].application_status, "saved");
    assert.strictEqual(result.diagnostics.list_container.requested_status, "saved");
    assert.strictEqual(result.diagnostics.list_container.detected_status, "saved");
    assert.strictEqual(result.diagnostics.list_container.declared_count, 196);
    
    result = await content.doScan("applied");
    assert.strictEqual(result.metadata.detected_count, 2);
    assert.strictEqual(result.jobs[0].title, "A1");
    assert.strictEqual(result.jobs[0].application_status, "applied");
    assert.strictEqual(result.diagnostics.list_container.declared_count, 15);
    
    result = await content.doScan("offer");
    assert.strictEqual(result.metadata.detected_count, 0);
    assert.strictEqual(result.diagnostics.warnings[0], "No visible Offer JobCopilot application list was found.");
    
    globalThis.MutationObserver = class { observe() {} disconnect() {} };
    const originalSetTimeout = globalThis.setTimeout;
    const originalClearTimeout = globalThis.clearTimeout;
    globalThis.setTimeout = (fn) => { fn(); return 1; };
    globalThis.clearTimeout = () => {};
    
    const port = { messages: [], postMessage: (msg) => port.messages.push(msg) };
    await content.autoScrollScan(port, "saved");
    
    globalThis.setTimeout = originalSetTimeout;
    globalThis.clearTimeout = originalClearTimeout;
    
    const finalMsg = port.messages[port.messages.length - 1];
    assert.strictEqual(finalMsg.status, 'complete');
    assert.strictEqual(finalMsg.result.metadata.exported_count, 1);
    assert.strictEqual(finalMsg.result.jobs[0].application_status, "saved");
  });

  it('works on single-list page as compatibility fallback', async () => {
    const dom = new JSDOM(`
      <html>
        <body>
          <div class="column-wrapper">
            <div class="at-card" id="fallback-list">
              <div class="shadow-card" data-job-id="f1"><h2 class="job-title">F1</h2><div class="company-name">C</div></div>
            </div>
          </div>
        </body>
      </html>
    `, { url: "https://app.jobcopilot.com/" });
    
    const doc = dom.window.document;
    const fallbackList = doc.getElementById('fallback-list');
    
    fallbackList.getClientRects = () => [{width: 100, height: 100}];
    fallbackList.getBoundingClientRect = () => ({width: 100, height: 100});
    Object.defineProperty(fallbackList, 'clientHeight', { value: 100 });
    
    globalThis.window = dom.window;
    globalThis.document = doc;
    globalThis.location = dom.window.location;
    globalThis.window.getComputedStyle = () => ({ display: 'block', visibility: 'visible' });
    
    require('../content.js');
    const { content } = globalThis.ApplywrightExtension;
    
    const result = await content.doScan("saved");
    assert.strictEqual(result.metadata.detected_count, 1);
    assert.strictEqual(result.jobs[0].title, "F1");
    assert.strictEqual(result.diagnostics.list_container.detected_status, "unknown");
  });

  it('handles robust auto-scroll with virtualized list dynamics', async () => {
    // We will simulate 196 unique records. 
    // They load 20 at a time, scrollHeight increases by 1000 each load.
    // Client height is 500.
    const mockContainer = {
      scrollTop: 0,
      clientHeight: 500,
      scrollHeight: 1000,
      getClientRects: () => [{width: 100, height: 100}],
      getBoundingClientRect: () => ({width: 100, height: 100}),
      querySelectorAll: (sel) => {
        if (sel.includes('shadow-card')) return [{}, {}];
        return [];
      }
    };
    
    let generatedRecords = 0;
    const totalRecords = 196;
    let nextUniqueCountAtLastCheck = 0;
    
    const origScanDOM = globalThis.ApplywrightExtension.extract.scanDOM;
    const origProcessRecords = globalThis.ApplywrightExtension.extract.processRecords;
    
    globalThis.ApplywrightExtension.extract.scanDOM = (root) => {
      assert.strictEqual(root, mockContainer); // scoped root is used
      
      // Return up to 20 records based on scrollTop
        const batchIndex = Math.floor(mockContainer.scrollTop / 1000);
        const start = batchIndex * 20;
        const end = Math.min(start + 40, totalRecords); // Returns current and next batch overlapping
        
        const records = [];
        for(let i = start; i < end; i++) {
          records.push({ valid: true, job_data: { external_id: `id-${i}`, title: `Job ${i}`, company: 'Corp' } });
        }
        
        // Simulate DOM mutation by increasing scrollHeight if we near the bottom
        // But only up to a point
        if (mockContainer.scrollTop + mockContainer.clientHeight >= mockContainer.scrollHeight - 500) {
          if (end < totalRecords) {
            mockContainer.scrollHeight += 1000;
          }
        }
        
        return { card_count: records.length, records };
    };
    
    globalThis.ApplywrightExtension.extract.processRecords = (report) => {
        const unique = new Set();
        report.records.forEach(r => {
           if (r.valid && r.job_data) unique.add(r.job_data.external_id);
        });
        return {
          metadata: { exported_count: unique.size },
          jobs: Array.from(unique).map(id => ({ external_id: id })),
          diagnostics: {}
        };
    };
    
    globalThis.document = {
      querySelectorAll: (sel) => sel === '.at-card' ? [mockContainer] : [],
      querySelector: (sel) => sel === '.at-card' ? mockContainer : null,
      body: {}
    };
    // Need window.getComputedStyle for findActiveJobList
    globalThis.window = { 
      scrollY: 0, 
      innerHeight: 800, 
      scrollTo: () => {},
      getComputedStyle: () => ({ display: 'block', visibility: 'visible' })
    };
    globalThis.location = { href: 'https://app.jobcopilot.com' };
    
    // Mock chrome
    globalThis.chrome = {
      runtime: {
        onMessage: { addListener: () => {} },
        onConnect: { addListener: () => {} }
      }
    };
    
    // Mock MutationObserver
    globalThis.MutationObserver = class {
      observe() {}
      disconnect() {}
    };
    
    const { content } = globalThis.ApplywrightExtension;
    require('../content.js');
    
    // Fast-forward timeouts
    const originalSetTimeout = globalThis.setTimeout;
    const originalClearTimeout = globalThis.clearTimeout;
    globalThis.setTimeout = (fn) => { fn(); return 1; };
    globalThis.clearTimeout = () => {};
    
    const port = {
      messages: [],
      postMessage: (msg) => port.messages.push(msg)
    };
    
    const result = await globalThis.ApplywrightExtension.content.autoScrollScan(port);
    
    globalThis.setTimeout = originalSetTimeout;
    globalThis.clearTimeout = originalClearTimeout;
    
    globalThis.ApplywrightExtension.extract.scanDOM = origScanDOM;
    globalThis.ApplywrightExtension.extract.processRecords = origProcessRecords;
    
    // Check results
    assert.strictEqual(result.metadata.exported_count, totalRecords); // all 196 accumulated
    assert.strictEqual(mockContainer.scrollTop, 0); // scroll restored
    
    // Verification of progress messages
    const finalMsg = port.messages[port.messages.length - 2].message;
    assert.ok(finalMsg.includes(`Unique jobs: ${totalRecords}`));
  });

  it('detects live JobCopilot status headers and handles popup duplicate runs', async () => {
    const dom = new JSDOM(`
      <html>
        <body>
          <div class="column">
            <div class="header">
              <div>Saved (196)</div>
              <button>One Click Apply</button>
              <p>Select jobs to activate this feature.</p>
            </div>
            <div class="at-card" id="saved-list">
              <div class="shadow-card" data-job-id="s1"><h2 class="job-title">S1</h2><div class="company-name">C</div></div>
            </div>
          </div>
          <div class="column">
            <div class="header">
              <div>Applied (15)</div>
            </div>
            <div class="at-card" id="applied-list">
              <div class="shadow-card" data-job-id="a1"><h2 class="job-title">Saved Job in Applied</h2><div class="company-name">C</div></div>
            </div>
          </div>
          <div class="column">
            <div class="header">
              Saved (123) One Click Apply Select jobs to activate this feature.
            </div>
            <div class="at-card" id="combined-list">
              <div class="shadow-card" data-job-id="c1"><h2 class="job-title">C1</h2><div class="company-name">C</div></div>
            </div>
          </div>
        </body>
      </html>
    `, { url: "https://app.jobcopilot.com/" });
    
    const doc = dom.window.document;
    const savedList = doc.getElementById('saved-list');
    const appliedList = doc.getElementById('applied-list');
    const combinedList = doc.getElementById('combined-list');
    
    const setupList = (list) => {
      list.getClientRects = () => [{width: 100, height: 100}];
      list.getBoundingClientRect = () => ({width: 100, height: 100});
      Object.defineProperty(list, 'clientHeight', { value: 100 });
      Object.defineProperty(list, 'scrollHeight', { value: 100 });
      Object.defineProperty(list, 'scrollTop', { value: 0, writable: true });
    };
    setupList(savedList);
    setupList(appliedList);
    setupList(combinedList);
    
    globalThis.window = dom.window;
    globalThis.document = doc;
    globalThis.location = dom.window.location;
    globalThis.window.getComputedStyle = () => ({ display: 'block', visibility: 'visible' });
    
    require('../content.js');
    const { content } = globalThis.ApplywrightExtension;
    
    // Test 1: Saved is detected from a div and combined text
    // "Saved (196)" div will be detected for #saved-list, making it a tie between #saved-list and #combined-list
    // It should pick #saved-list or #combined-list, but definitely NOT #applied-list
    const result = await content.doScan("saved");
    assert.strictEqual(result.diagnostics.list_container.requested_status, "saved");
    assert.strictEqual(result.diagnostics.list_container.detected_status, "saved");
    assert.strictEqual(result.diagnostics.list_container.matching_candidate_count, 2); // Both saved-list and combined-list match
    assert.ok(result.metadata.detected_count > 0);
    assert.strictEqual(result.jobs[0].application_status, "saved");
    
    // Test duplicate auto-scroll start
    const port = { messages: [], postMessage: (msg) => port.messages.push(msg) };
    
    globalThis.MutationObserver = class { observe() {} disconnect() {} };
    const originalSetTimeout = globalThis.setTimeout;
    const originalClearTimeout = globalThis.clearTimeout;
    globalThis.setTimeout = (fn) => { fn(); return 1; };
    globalThis.clearTimeout = () => {};
    
    // Start auto-scan
    const promise1 = content.autoScrollScan(port, "saved");
    // Attempt duplicate start
    content.autoScrollScan(port, "saved");
    
    await promise1;
    
    globalThis.setTimeout = originalSetTimeout;
    globalThis.clearTimeout = originalClearTimeout;
    
    // The duplicate start should have pushed "A scan is already running"
    const duplicateMsg = port.messages.find(m => m.message === 'A scan is already running.');
    assert.ok(duplicateMsg, "Duplicate auto-scroll start should send error message");
    
    // The actual scan should have completed
    const finalMsg = port.messages[port.messages.length - 1];
    assert.strictEqual(finalMsg.status, 'complete');
  });
  it('extracts review-page specific title and company deterministically', () => {
    const dom = new JSDOM(`
      <html>
        <body>
          <div class="flex flex-col gap-4">
            <p class="text-primary font-bold text-lg">
              Job Title:
              <span class="text-black font-semibold">Technical Architect</span>
            </p>

            <div class="flex flex-col gap-2">
              <div class="flex flex-row items-center gap-2 text-primary">
                <span>
                  Company :
                  <span class="text-black">Acme Connections1</span>
                </span>
              </div>
            </div>

            <div data-testid="job-description">
              <h2>Job Description</h2>
              <p>Example description.</p>
            </div>
          </div>
        </body>
      </html>
    `, { url: "https://app.jobcopilot.com/applications/review/test-id-123" });
    
    const { extract } = globalThis.ApplywrightExtension;
    const documentObj = dom.window.document;
    documentObj.body.setAttribute('data-job-id', 'test-id-123');
    
    const result = extract.extractCurrentPage(documentObj, "https://app.jobcopilot.com/applications/review/test-id-123");
    
    assert.strictEqual(result.error, undefined);
    assert.strictEqual(result.metadata.detected_count, 1);
    assert.strictEqual(result.jobs[0].title, "Technical Architect");
    assert.strictEqual(result.jobs[0].company, "Acme Connections1");
    assert.ok(result.jobs[0].description.includes("Example description"));
  });

  it('handles ambiguity and fallbacks in review-page extraction safely', () => {
    const dom = new JSDOM(`
      <html>
        <body>
          <!-- Unrelated elements that might trick weak selectors -->
          <span class="text-black font-semibold">Random unrelated text</span>
          <div class="flex">
             <span class="text-black">Another unrelated</span>
          </div>
          
          <div class="flex flex-col gap-4" data-job-id="test-id-ambig">
            <!-- Broad ancestor containing both -->
            <div id="broad-ancestor">
              Job Title:
              <p class="text-primary font-bold text-lg">
                Job Title:
                <span class="text-black font-semibold">Real Title</span>
              </p>
              Company:
              <div class="flex flex-row items-center gap-2 text-primary">
                <span>
                  Company :
                  <span class="text-black">Real Company</span>
                </span>
              </div>
            </div>
          </div>
        </body>
      </html>
    `, { url: "https://app.jobcopilot.com/applications/review/test-id-ambig" });
    
    const { extract } = globalThis.ApplywrightExtension;
    const documentObj = dom.window.document;
    
    let result = extract.extractCurrentPage(documentObj, "https://app.jobcopilot.com/applications/review/test-id-ambig");
    assert.strictEqual(result.error, "Could not locate a reliable description container"); // title/company succeeded
    assert.strictEqual(extract.extractReviewLabeledValue(documentObj, ['p'], ['Job Title:'], 'span.text-black.font-semibold'), "Real Title");
    assert.strictEqual(extract.extractReviewLabeledValue(documentObj, ['div', 'span'], ['Company:', 'Company :'], 'span.text-black'), "Real Company");

    // Test missing labeled title fails safely (falls back or errors)
    const domMissing = new JSDOM(`
      <html>
        <body data-job-id="test-missing">
          <p class="text-primary font-bold text-lg">
            Other Label:
            <span class="text-black font-semibold">Not Title</span>
          </p>
        </body>
      </html>
    `, { url: "https://app.jobcopilot.com/applications/review/test-missing" });
    
    let resMissing = extract.extractCurrentPage(domMissing.window.document, "https://app.jobcopilot.com/applications/review/test-missing");
    assert.strictEqual(resMissing.error, "Missing required title or company on page");

    // Test blank value span fails safely
    const domBlank = new JSDOM(`
      <html>
        <body data-job-id="test-blank">
          <p class="text-primary font-bold text-lg">
            Job Title:
            <span class="text-black font-semibold">   </span>
          </p>
          <span>
            Company :
            <span class="text-black"></span>
          </span>
        </body>
      </html>
    `, { url: "https://app.jobcopilot.com/applications/review/test-blank" });
    
    let resBlank = extract.extractCurrentPage(domBlank.window.document, "https://app.jobcopilot.com/applications/review/test-blank");
    assert.strictEqual(resBlank.error, "Missing required title or company on page");
  });

  it('extracts labeled Location / Job Type on the review page and derives remote_status', () => {
    const { extract } = globalThis.ApplywrightExtension;
    const dom = new JSDOM(`
      <html>
        <body data-job-id="job-meta">
          <p class="text-primary font-bold text-lg">Job Title: <span class="text-black font-semibold">DevOps Engineer</span></p>
          <div class="flex flex-row items-center gap-2 text-primary"><span>Company : <span class="text-black">Sample Team</span></span></div>
          <div class="flex flex-row items-center gap-2 text-primary">Location : <span class="text-black">Remote</span></div>
          <div class="flex flex-row items-center gap-2 text-primary">Job Type : <span class="text-black">Fulltime</span></div>
          <div data-testid="job-description">
            <h2>Job Description</h2>
            <p>We are hiring a DevOps Engineer to build AWS infrastructure with Terraform and Kubernetes.</p>
          </div>
        </body>
      </html>
    `, { url: "https://app.jobcopilot.com/applications/review/job-meta" });

    const result = extract.extractCurrentPage(dom.window.document, "https://app.jobcopilot.com/applications/review/job-meta");
    assert.ok(result.jobs, `expected a successful extraction, got error: ${result.error}`);
    const jd = result.jobs[0];
    assert.strictEqual(jd.location, "Remote");
    assert.strictEqual(jd.employment_type, "Fulltime");
    assert.strictEqual(jd.remote_status, "Remote"); // derived from Location value
    assert.strictEqual(jd.salary, null);            // no salary row present -> stays null
  });
});
