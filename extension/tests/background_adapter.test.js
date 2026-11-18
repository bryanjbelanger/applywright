const { describe, it, beforeEach, afterEach } = require('node:test');
const assert = require('node:assert');
const fs = require('fs');
const path = require('path');

describe('Background Adapter', () => {

  let bgScript;
  let chromeMock;
  let storageState = {};

  beforeEach(() => {
    storageState = {};
    
    // Mock chrome API
    chromeMock = {
      storage: {
        local: {
          get: async (keys) => {
            const res = {};
            for (const k of keys) {
              if (storageState[k] !== undefined) res[k] = storageState[k];
            }
            return res;
          },
          set: async (obj) => {
            Object.assign(storageState, obj);
          }
        }
      },
      runtime: {
        onInstalled: { addListener: () => {} },
        onMessage: {
          listeners: [],
          addListener: function(fn) { this.listeners.push(fn); }
        },
        sendMessage: () => {}
      },
      tabs: {
        _currentUrl: 'https://app.jobcopilot.com/applications/review/123',
        create: async (opts) => { this._currentUrl = opts.url; return { id: 101, status: 'loading', url: opts.url }; },
        update: async (id, opts) => { chromeMock.tabs._currentUrl = opts.url; return { id, status: 'loading', url: opts.url }; },
        remove: async (id) => {},
        sendMessage: async (id, msg) => {
           return { jobs: [{ external_id: '123', description: 'mock desc', job_url: 'https://app.jobcopilot.com/applications/review/123' }], metadata: {} };
        },
        get: (id, cb) => { cb({ status: 'complete', url: chromeMock.tabs._currentUrl }); },
        onUpdated: {
          listeners: [],
          addListener: function(fn) { this.listeners.push(fn); },
          removeListener: function(fn) { this.listeners = this.listeners.filter(l => l !== fn); }
        }
      }
    };

    globalThis.chrome = chromeMock;
    globalThis.importScripts = () => {
      // Mock importScripts by requiring the orchestrator
      require('../batch_orchestrator.js');
    };

    // We can evaluate background.js in this context
    const bgCode = fs.readFileSync(path.join(__dirname, '../background.js'), 'utf8');
    
    // Clean up previous listeners
    chromeMock.runtime.onMessage.listeners = [];
    
    // Run the script
    eval(bgCode);
  });

  afterEach(async () => {
    // Force stop orchestrator to break out of loops
    if (globalThis.ApplywrightExtension.BatchOrchestrator) {
      const state = chromeMock.storage.local.get(['batchState']);
      if (state) {
        state.status = 'stopped';
      }
    }
    // Give dangling promises a chance to settle
    await new Promise(r => setTimeout(r, 2000));
  });

  it('survives service worker restart and resumes', async () => {
    // 1. Manually setup the storage state as if it was stopped mid-run
    const { BatchOrchestrator } = globalThis.ApplywrightExtension;
    const orch = new BatchOrchestrator();
    orch.loadQueue({ jobs: [
      { external_id: '123', job_url: 'https://app.jobcopilot.com/applications/review/123' },
      { external_id: '456', job_url: 'https://app.jobcopilot.com/applications/review/456' }
    ]});
    orch.start();
    
    // Save this state to mocked storage
    storageState.batchState = orch.getState();
    
    // 2. Re-eval the background script to simulate a restart
    const bgCode = fs.readFileSync(path.join(__dirname, '../background.js'), 'utf8');
    eval(bgCode); // This will call loadState() and since it's 'running', runBatchLoop()
    
    // Wait for the loop to do its thing
    await new Promise(r => setTimeout(r, 100)); // sleep wait
    
    // Simulate tab completion for the first job (123)
    chromeMock.tabs.onUpdated.listeners.forEach(l => l(101, { status: 'complete' }, { url: 'https://app.jobcopilot.com/applications/review/123' }));
    
    await new Promise(r => setTimeout(r, 1500)); 
    
    // State should now have 1 extracted job and still running
    assert.strictEqual(storageState.batchState.extractedJobs.length, 1);
    
    // Simulate tab completion for the second job (456)
    chromeMock.tabs.sendMessage = async () => {
      return { jobs: [{ external_id: '456', description: 'mock desc 2', job_url: 'https://app.jobcopilot.com/applications/review/456' }], metadata: {} };
    };
    chromeMock.tabs.onUpdated.listeners.forEach(l => l(101, { status: 'complete' }, { url: 'https://app.jobcopilot.com/applications/review/456' }));
    
    await new Promise(r => setTimeout(r, 3000));
    
    assert.strictEqual(storageState.batchState.status, 'finished');
    assert.strictEqual(storageState.batchState.extractedJobs.length, 2);
  });
  
  it('popup message listener operates correctly', async () => {
     let response = null;
     const sendResponse = (res) => { response = res; };
     
     // Find the runtime.onMessage listener
     const listener = chromeMock.runtime.onMessage.listeners[0];
     
     listener({ action: 'load_queue', payload: { jobs: [{ external_id: '999', job_url: 'https://app.jobcopilot.com/applications/review/999' }] } }, {}, sendResponse);
     
     // Wait for storage write promise to resolve
     await new Promise(r => setTimeout(r, 10));
     
     assert.strictEqual(response.ok, true);
     assert.strictEqual(storageState.batchState.queue[0].external_id, '999');
     
     // Start batch
     listener({ action: 'start_batch' }, {}, sendResponse);
     await new Promise(r => setTimeout(r, 10));
     assert.strictEqual(response.ok, true);
     assert.strictEqual(storageState.batchState.status, 'running');
     
     // Cancel batch
     listener({ action: 'cancel_batch' }, {}, sendResponse);
     await new Promise(r => setTimeout(r, 10));
     assert.strictEqual(response.ok, true);
     assert.strictEqual(storageState.batchState.status, 'stopped');
     assert.strictEqual(storageState.batchState.stopped_reason, 'cancelled_by_user');
  });

  it('status requested before storage resolves waits and returns restored state', async () => {
    let resolveStorage;
    const storagePromise = new Promise(r => { resolveStorage = r; });
    chromeMock.storage.local.get = async () => {
       await storagePromise;
       return { batchState: { status: 'idle', queue: [ { external_id: '9999' } ] } };
    };
    
    chromeMock.runtime.onMessage.listeners = [];
    const bgCode = fs.readFileSync(path.join(__dirname, '../background.js'), 'utf8');
    eval(bgCode);
    
    let response = null;
    const sendResponse = (res) => { response = res; };
    const listener = chromeMock.runtime.onMessage.listeners[0];
    
    const ret = listener({ action: 'get_batch_status' }, {}, sendResponse);
    assert.strictEqual(ret, true);
    assert.strictEqual(response, null);
    
    resolveStorage();
    await new Promise(r => setTimeout(r, 10));
    
    assert.ok(response);
    assert.strictEqual(response.state.queue[0].external_id, '9999');
  });

  it('export requested before storage resolves waits and returns restored jobs', async () => {
    let resolveStorage;
    const storagePromise = new Promise(r => { resolveStorage = r; });
    chromeMock.storage.local.get = async () => {
       await storagePromise;
       return { batchState: { status: 'idle', queue: [], extractedJobs: [ { external_id: '9999', title: 'T' } ] } };
    };
    
    chromeMock.runtime.onMessage.listeners = [];
    const bgCode = fs.readFileSync(path.join(__dirname, '../background.js'), 'utf8');
    eval(bgCode);
    
    let response = null;
    const sendResponse = (res) => { response = res; };
    const listener = chromeMock.runtime.onMessage.listeners[0];
    
    listener({ action: 'get_batch_export' }, {}, sendResponse);
    resolveStorage();
    await new Promise(r => setTimeout(r, 10));
    
    assert.ok(response);
    assert.strictEqual(response.payloads[0].jobs[0].external_id, '9999');
  });

  it('multiple early messages do not create duplicate loops', async () => {
    let resolveStorage;
    const storagePromise = new Promise(r => { resolveStorage = r; });
    chromeMock.storage.local.get = async () => {
       await storagePromise;
       return { batchState: { status: 'running', queue: [{external_id: '1', job_url: 'http://a'}], extractedJobs: [] } };
    };
    
    chromeMock.runtime.onMessage.listeners = [];
    const bgCode = fs.readFileSync(path.join(__dirname, '../background.js'), 'utf8');
    eval(bgCode);
    
    let response1 = null, response2 = null;
    const listener = chromeMock.runtime.onMessage.listeners[0];
    
    listener({ action: 'resume_batch' }, {}, r => { response1 = r; });
    listener({ action: 'resume_batch' }, {}, r => { response2 = r; });
    
    resolveStorage();
    await new Promise(r => setTimeout(r, 20));
    
    assert.ok(response1.ok);
    assert.ok(response2.ok);
  });

  it('initialization failure returns an error', async () => {
    const originalGet = chromeMock.storage.local.get;
    chromeMock.storage.local.get = async () => {
       throw new Error("Disk read error");
    };
    
    chromeMock.runtime.onMessage.listeners = [];
    const bgCode = fs.readFileSync(path.join(__dirname, '../background.js'), 'utf8');
    eval(bgCode);
    
    let response = null;
    const listener = chromeMock.runtime.onMessage.listeners[0];
    
    listener({ action: 'get_batch_status' }, {}, r => { response = r; });
    
    await new Promise(r => setTimeout(r, 10));
    assert.ok(response.error);
    assert.ok(response.error.includes("Disk read error"));
    
    chromeMock.storage.local.get = originalGet;
  });

  it('discards the old run\'s outstanding extraction after cancel and a new queue', async () => {
    const listener = chromeMock.runtime.onMessage.listeners[0];
    const send = (msg) => new Promise(resolve => listener(msg, {}, resolve));
    const url = (id) => `https://app.jobcopilot.com/applications/review/${id}`;
    const complete = (id) => chromeMock.tabs.onUpdated.listeners.forEach(
      l => l(101, { status: 'complete' }, { url: url(id) }));
    const job = (id) => ({ external_id: id, job_url: url(id) });

    // The extraction for job 111 stays outstanding until the test resolves it.
    let resolveStale;
    chromeMock.tabs.sendMessage = () => new Promise(resolve => { resolveStale = resolve; });

    await send({ action: 'load_queue', payload: { jobs: [job('111'), job('222')] } });
    await send({ action: 'start_batch' });
    await new Promise(r => setTimeout(r, 50));
    complete('111');
    await new Promise(r => setTimeout(r, 1500));
    assert.ok(resolveStale, 'extraction for 111 must be outstanding');

    // Cancel, then replace the run with a different queue.
    await send({ action: 'cancel_batch' });
    await send({ action: 'load_queue', payload: { jobs: [job('333'), job('444')] } });
    await send({ action: 'start_batch' });

    resolveStale({ jobs: [{ external_id: '111', description: 'old', job_url: url('111') }], metadata: {} });
    await new Promise(r => setTimeout(r, 100));

    const state = storageState.batchState;
    assert.deepStrictEqual(state.failed, [], 'the new queue must not lose job 333');
    assert.strictEqual(state.currentIndex, 0);
    assert.strictEqual(state.extractedJobs.length, 0);
  });

});
