const { test, describe, it, before, after, beforeEach } = require('node:test');
const assert = require('node:assert');
const { JSDOM } = require('jsdom');
const fs = require('fs');
const path = require('path');

describe('ApplywrightExtension Popup', () => {
  let dom;
  let popupCode;
  
  before(() => {
    popupCode = fs.readFileSync(path.join(__dirname, '../popup.js'), 'utf8');
  });
  
  beforeEach(() => {
    dom = new JSDOM(`
      <html>
        <body>
          <button id="btn-scan"></button>
          <button id="btn-scan-auto"></button>
          <button id="btn-cancel"></button>
          <button id="btn-enrich"></button>
          <button id="btn-export"></button>
          <button id="btn-copy"></button>
          <button id="btn-diagnostics"></button>
          <button id="btn-clear"></button>
          <div id="status"></div>

          <input type="file" id="batch-queue-file">
          <button id="btn-batch-load"></button>
          <button id="btn-batch-start"></button>
          <button id="btn-batch-resume"></button>
          <button id="btn-batch-cancel"></button>
          <button id="btn-batch-export"></button>
          <div id="batch-status"></div>
        </body>
      </html>
    `, { runScripts: "dangerously" });
    
    globalThis.window = dom.window;
    globalThis.document = dom.window.document;
    
    dom.window.chrome = {
      storage: {
        local: {
          get: async () => ({}),
          set: async () => {},
          remove: async () => {}
        }
      },
      runtime: {
        sendMessage: (msg, cb) => { if (cb) cb({}); }
      },
      tabs: {
        query: async () => [{ id: 1, url: 'https://app.jobcopilot.com/' }],
        connect: () => ({
          onMessage: { addListener: () => {} },
          onDisconnect: { addListener: () => {} },
          postMessage: () => {}
        }),
        sendMessage: async () => {}
      },
      downloads: { download: () => {} }
    };
  });

  describe('Auto-scroll Extraction', () => {
    it('registers onMessage before postMessage and handles immediate completion', async () => {
      let callOrder = [];
      let savedResult = null;
      let registeredOnMessage = null;
      
      dom.window.chrome.storage.local.set = async (data) => {
        savedResult = data.scanResult;
      };
      
      const mockPort = {
        onMessage: {
          addListener: (fn) => {
            callOrder.push('onMessage');
            registeredOnMessage = fn;
          }
        },
        onDisconnect: {
          addListener: (fn) => {
            callOrder.push('onDisconnect');
          }
        },
        postMessage: (msg) => {
          callOrder.push('postMessage');
          if (registeredOnMessage) {
             registeredOnMessage({ status: 'complete', result: { metadata: { exported_count: 5 }, jobs: [] } });
          }
        }
      };
      
      dom.window.chrome.tabs.connect = () => mockPort;
      
      dom.window.eval(popupCode);
      dom.window.document.dispatchEvent(new dom.window.Event('DOMContentLoaded'));
      await new Promise(resolve => setTimeout(resolve, 0));
      
      const btnScanAuto = dom.window.document.getElementById('btn-scan-auto');
      const btnScan = dom.window.document.getElementById('btn-scan');
      const btnCancel = dom.window.document.getElementById('btn-cancel');
      
      btnScanAuto.click();
      await new Promise(resolve => setTimeout(resolve, 10));
      
      assert.deepStrictEqual(callOrder, ['onMessage', 'onDisconnect', 'postMessage']);
      assert.strictEqual(btnScanAuto.disabled, false);
      assert.strictEqual(btnScan.disabled, false);
      assert.strictEqual(btnCancel.disabled, true);
      assert.ok(savedResult !== null, "Result should be saved on immediate completion");
    });

    it('disconnect restores button state', async () => {
      let disconnectCb = null;
      const mockPort = {
        onMessage: { addListener: () => {} },
        onDisconnect: {
          addListener: (fn) => { disconnectCb = fn; }
        },
        postMessage: () => {}
      };
      
      dom.window.chrome.tabs.connect = () => mockPort;
      
      dom.window.eval(popupCode);
      dom.window.document.dispatchEvent(new dom.window.Event('DOMContentLoaded'));
      await new Promise(resolve => setTimeout(resolve, 0));
      
      const btnScanAuto = dom.window.document.getElementById('btn-scan-auto');
      const btnScan = dom.window.document.getElementById('btn-scan');
      const btnCancel = dom.window.document.getElementById('btn-cancel');
      
      btnScanAuto.click();
      await new Promise(resolve => setTimeout(resolve, 10));
      
      assert.strictEqual(btnScanAuto.disabled, true);
      assert.strictEqual(btnCancel.disabled, false);
      
      disconnectCb();
      
      assert.strictEqual(btnScanAuto.disabled, false);
      assert.strictEqual(btnScan.disabled, false);
      assert.strictEqual(btnCancel.disabled, true);
      assert.strictEqual(dom.window.document.getElementById('status').innerHTML, "Auto-scroll scan disconnected before completion.");
    });
  });

  describe('Current Job Enrichment', () => {
    it('invalid review URL does not send enrich_current message', async () => {
      let messageSent = false;
      dom.window.chrome.tabs.query = async () => [{ id: 1, url: 'https://app.jobcopilot.com/jobs' }];
      dom.window.chrome.tabs.sendMessage = async (tabId, msg) => {
        if (msg.action === 'enrich_current') messageSent = true;
      };
      
      dom.window.eval(popupCode);
      dom.window.document.dispatchEvent(new dom.window.Event('DOMContentLoaded'));
      await new Promise(resolve => setTimeout(resolve, 0));
      
      const btnEnrich = dom.window.document.getElementById('btn-enrich');
      btnEnrich.click();
      await new Promise(resolve => setTimeout(resolve, 10));
      
      assert.strictEqual(messageSent, false);
      assert.match(dom.window.document.getElementById('status').innerHTML, /Cannot enrich: Must be on a JobCopilot review page/);
    });

    it('controls are disabled during enrichment and cancel is not presented', async () => {
      let sendPromiseResolve;
      dom.window.chrome.tabs.query = async () => [{ id: 1, url: 'https://app.jobcopilot.com/applications/review/123' }];
      dom.window.chrome.tabs.sendMessage = async () => {
        return new Promise(resolve => { sendPromiseResolve = resolve; });
      };
      
      dom.window.eval(popupCode);
      dom.window.document.dispatchEvent(new dom.window.Event('DOMContentLoaded'));
      await new Promise(resolve => setTimeout(resolve, 0));
      
      const btnEnrich = dom.window.document.getElementById('btn-enrich');
      const btnCancel = dom.window.document.getElementById('btn-cancel');
      
      btnEnrich.click();
      await new Promise(resolve => setTimeout(resolve, 10));
      
      assert.strictEqual(btnEnrich.disabled, true);
      assert.strictEqual(btnCancel.disabled, true, "Cancel button should not be enabled for synchronous enrichment");
      assert.match(dom.window.document.getElementById('status').innerHTML, /Extracting current job details/);
      
      sendPromiseResolve({ result: { metadata: { exported_count: 1 }, jobs: [{title: "A"}] } });
      await new Promise(resolve => setTimeout(resolve, 10));
      
      assert.strictEqual(btnEnrich.disabled, false);
    });

    it('enrichment success saves result and enables export buttons', async () => {
      let savedData = null;
      dom.window.chrome.storage.local.set = async (data) => { savedData = data; };
      dom.window.chrome.tabs.query = async () => [{ id: 1, url: 'https://app.jobcopilot.com/applications/review/123' }];
      dom.window.chrome.tabs.sendMessage = async () => ({ metadata: { exported_count: 1, page_url: "x", exported_at: "x", detected_count: 1, invalid_count: 0, duplicate_count: 0, warning_count: 0 }, jobs: [{title: "A"}] });
      
      dom.window.eval(popupCode);
      dom.window.document.dispatchEvent(new dom.window.Event('DOMContentLoaded'));
      await new Promise(resolve => setTimeout(resolve, 0));
      
      const btnEnrich = dom.window.document.getElementById('btn-enrich');
      const btnExport = dom.window.document.getElementById('btn-export');
      const btnCopy = dom.window.document.getElementById('btn-copy');
      
      btnEnrich.click();
      await new Promise(resolve => setTimeout(resolve, 10));
      
      assert.ok(savedData && savedData.scanResult);
      assert.strictEqual(savedData.scanResult.jobs[0].title, "A");
      assert.strictEqual(btnExport.disabled, false);
      assert.strictEqual(btnCopy.disabled, false);
      assert.match(dom.window.document.getElementById('status').innerHTML, /Jobs Exported:/);
    });

    it('enrichment failure does not overwrite previous valid result and restores controls', async () => {
      let savedData = { scanResult: { metadata: { exported_count: 1 }, jobs: [{title: "ValidOld"}] } };
      dom.window.chrome.storage.local.get = async () => savedData;
      dom.window.chrome.storage.local.set = async (data) => { savedData = data; };
      dom.window.chrome.tabs.query = async () => [{ id: 1, url: 'https://app.jobcopilot.com/applications/review/123' }];
      dom.window.chrome.tabs.sendMessage = async () => ({ error: "Failed to extract" });
      
      dom.window.eval(popupCode);
      dom.window.document.dispatchEvent(new dom.window.Event('DOMContentLoaded'));
      await new Promise(resolve => setTimeout(resolve, 10)); // wait for init
      
      const btnEnrich = dom.window.document.getElementById('btn-enrich');
      btnEnrich.click();
      await new Promise(resolve => setTimeout(resolve, 10));
      
      assert.strictEqual(savedData.scanResult.jobs[0].title, "ValidOld", "Old result should not be overwritten");
      assert.strictEqual(btnEnrich.disabled, false, "Controls should be restored");
      assert.match(dom.window.document.getElementById('status').innerHTML, /Failed to extract/);
    });

    it('empty response or thrown sendMessage error does not overwrite previous result', async () => {
      let savedData = { scanResult: { metadata: { exported_count: 1 }, jobs: [{title: "ValidOld"}] } };
      dom.window.chrome.storage.local.get = async () => savedData;
      dom.window.chrome.storage.local.set = async (data) => { savedData = data; };
      dom.window.chrome.tabs.query = async () => [{ id: 1, url: 'https://app.jobcopilot.com/applications/review/123' }];
      dom.window.chrome.tabs.sendMessage = async () => { throw new Error("Connection failed"); };
      
      dom.window.eval(popupCode);
      dom.window.document.dispatchEvent(new dom.window.Event('DOMContentLoaded'));
      await new Promise(resolve => setTimeout(resolve, 10));
      
      const btnEnrich = dom.window.document.getElementById('btn-enrich');
      btnEnrich.click();
      await new Promise(resolve => setTimeout(resolve, 10));
      
      assert.strictEqual(savedData.scanResult.jobs[0].title, "ValidOld");
      assert.strictEqual(btnEnrich.disabled, false);
      assert.match(dom.window.document.getElementById('status').innerHTML, /failed/i);
    });

    it('repeated clicks cannot start concurrent enrichment', async () => {
      let sendMessageCalls = 0;
      let sendPromiseResolve;
      dom.window.chrome.tabs.query = async () => [{ id: 1, url: 'https://app.jobcopilot.com/applications/review/123' }];
      dom.window.chrome.tabs.sendMessage = async () => {
        sendMessageCalls++;
        return new Promise(resolve => { sendPromiseResolve = resolve; });
      };
      
      dom.window.eval(popupCode);
      dom.window.document.dispatchEvent(new dom.window.Event('DOMContentLoaded'));
      await new Promise(resolve => setTimeout(resolve, 0));
      
      const btnEnrich = dom.window.document.getElementById('btn-enrich');
      
      // Simulate click
      btnEnrich.click();
      // Second click should be blocked by btnEnrich.disabled state
      btnEnrich.click();
      
      await new Promise(resolve => setTimeout(resolve, 10));
      assert.strictEqual(sendMessageCalls, 1);
      
      sendPromiseResolve({ metadata: { exported_count: 1 }, jobs: [{}] });
      await new Promise(resolve => setTimeout(resolve, 10));
    });
  });

  // F5: an error reply is not a scan result. It must never reach storage.
  describe('Scan failure', () => {
    async function openPopup() {
      dom.window.eval(popupCode);
      dom.window.document.dispatchEvent(new dom.window.Event('DOMContentLoaded'));
      await new Promise(resolve => setTimeout(resolve, 10));
    }

    it('scan error reply is shown and not stored', async () => {
      const writes = [];
      dom.window.chrome.storage.local.set = async (data) => { writes.push(data); };
      dom.window.chrome.tabs.sendMessage = async () => ({ error: 'selector failed' });
      await openPopup();

      dom.window.document.getElementById('btn-scan').click();
      await new Promise(resolve => setTimeout(resolve, 10));

      assert.deepStrictEqual(writes, []);
      assert.match(dom.window.document.getElementById('status').innerHTML, /selector failed/);
    });

    it('auto-scan completing without a result is shown and not stored', async () => {
      const writes = [];
      let onMessage = null;
      dom.window.chrome.storage.local.set = async (data) => { writes.push(data); };
      dom.window.chrome.tabs.connect = () => ({
        onMessage: { addListener: (fn) => { onMessage = fn; } },
        onDisconnect: { addListener: () => {} },
        postMessage: () => { onMessage({ status: 'complete', result: { error: 'boom' } }); }
      });
      await openPopup();

      dom.window.document.getElementById('btn-scan-auto').click();
      await new Promise(resolve => setTimeout(resolve, 10));

      assert.deepStrictEqual(writes, []);
      assert.match(dom.window.document.getElementById('status').innerHTML, /boom/);
    });

    it('a bad stored value is cleared on open and the popup stays usable', async () => {
      const removed = [];
      dom.window.chrome.storage.local.get = async () => ({ scanResult: { error: 'old failure' } });
      dom.window.chrome.storage.local.remove = async (keys) => { removed.push(keys); };
      await openPopup();

      assert.strictEqual(JSON.stringify(removed), JSON.stringify([['scanResult']]));
      assert.strictEqual(dom.window.document.getElementById('btn-export').disabled, true);
      assert.strictEqual(dom.window.document.getElementById('btn-clear').disabled, true);
    });
  });

  describe('Batch export', () => {
    it('gives every envelope of one export the same timestamp', async () => {
      // Each new Date() is one second later than the last.
      const RealDate = dom.window.Date;
      let tick = 0;
      dom.window.Date = class extends RealDate {
        constructor(...args) {
          super(...(args.length ? args : [Date.UTC(2026, 0, 1, 0, 0, tick++)]));
        }
      };
      const names = [];
      dom.window.chrome.downloads.download = (opts) => { names.push(opts.filename); };
      dom.window.chrome.runtime.sendMessage = (msg, cb) => {
        if (msg.action === 'get_batch_export') cb({ payloads: [{ jobs: [] }, { jobs: [] }, { jobs: [] }] });
        else if (cb) cb({});
      };
      dom.window.URL.createObjectURL = () => 'blob:x';

      dom.window.eval(popupCode);
      dom.window.document.dispatchEvent(new dom.window.Event('DOMContentLoaded'));
      await new Promise(resolve => setTimeout(resolve, 0));
      dom.window.document.getElementById('btn-batch-export').click();

      assert.strictEqual(names.length, 3);
      const stamps = names.map(n => n.match(/export-(\d{8}-\d{6})-batch-\d+of3\.json$/)[1]);
      assert.strictEqual(new Set(stamps).size, 1);
    });
  });
});
