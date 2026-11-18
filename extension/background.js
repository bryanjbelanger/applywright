importScripts('batch_orchestrator.js');

const { BatchOrchestrator } = globalThis.ApplywrightExtension;

let orchestrator = new BatchOrchestrator();
let currentTabId = null;
let isLoopRunning = false;
// Each cancel or replaced queue starts a new run. Work that began in an earlier
// run must not change the current one.
let runEpoch = 0;

async function saveState() {
  await chrome.storage.local.set({ batchState: orchestrator.getState() });
}

async function loadState() {
  const data = await chrome.storage.local.get(['batchState']);
  if (data.batchState) {
    orchestrator = new BatchOrchestrator(data.batchState);
  }
  if (orchestrator.getState().status === 'running') {
     runBatchLoop();
  }
}

const initializationPromise = loadState();

chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  initializationPromise.then(async () => {
    try {
      if (msg.action === 'load_queue') {
         orchestrator.loadQueue(msg.payload);
         runEpoch++;
         await saveState();
         sendResponse({ ok: true, state: orchestrator.getState() });
      }
      else if (msg.action === 'start_batch' || msg.action === 'resume_batch') {
         orchestrator.start();
         await saveState();
         sendResponse({ ok: true });
         runBatchLoop();
      }
      else if (msg.action === 'cancel_batch') {
         orchestrator.cancel();
         runEpoch++;
         await saveState();
         closeDedicatedTab();
         sendResponse({ ok: true });
      }
      else if (msg.action === 'get_batch_status') {
         sendResponse({ state: orchestrator.getState() });
      }
      else if (msg.action === 'get_batch_export') {
         sendResponse({ payloads: orchestrator.generateExportPayloads("0.1.0") });
      }
    } catch (e) {
      sendResponse({ error: e.message });
    }
  }).catch(e => {
    sendResponse({ error: e.message });
  });
  
  return true;
});

async function closeDedicatedTab() {
  if (currentTabId) {
    try {
      await chrome.tabs.remove(currentTabId);
    } catch(e) {}
    currentTabId = null;
  }
}

async function sleep(ms) {
  return new Promise(resolve => setTimeout(resolve, ms));
}

async function ensureTabAndNavigate(url) {
  if (!currentTabId) {
     const tab = await chrome.tabs.create({ url, active: false });
     currentTabId = tab.id;
  } else {
     await chrome.tabs.update(currentTabId, { url });
  }
  
  return new Promise((resolve, reject) => {
      const timeout = setTimeout(() => {
          chrome.tabs.onUpdated.removeListener(listener);
          reject(new Error("Timeout waiting for tab to load"));
      }, 20000);

      const listener = function(tabId, info, tab) {
          if (tabId === currentTabId && info.status === 'complete') {
              clearTimeout(timeout);
              chrome.tabs.onUpdated.removeListener(listener);
              if (tab.url && tab.url !== url && tab.url !== url + '/') {
                  reject(new Error(`Unexpected navigation to ${tab.url} (expected ${url})`));
              } else {
                  resolve();
              }
          }
      };
      chrome.tabs.onUpdated.addListener(listener);

      // Fallback check in case it completed before listener attached
      chrome.tabs.get(currentTabId, (tab) => {
          if (tab && tab.status === 'complete') {
              if (tab.url === url || tab.url === url + '/') {
                  clearTimeout(timeout);
                  chrome.tabs.onUpdated.removeListener(listener);
                  resolve();
              }
          }
      });
  });
}

async function tryEnrichCurrent(tabId) {
  const maxRetries = 40; // ~20s: review pages can render slowly in a background tab
  for (let i = 0; i < maxRetries; i++) {
    try {
      const res = await chrome.tabs.sendMessage(tabId, { action: 'enrich_current' });
      if (res && res.metadata) { 
         return res;
      }
      if (res && res.error) {
         // content script returned an error, might mean page is not ready, we will retry
      }
    } catch (e) {
      // Content script not ready yet (or receiving end does not exist)
    }
    await sleep(500);
  }
  throw new Error("Timeout waiting for content script to be ready or return valid data");
}

async function runBatchLoop() {
  if (isLoopRunning) return;
  isLoopRunning = true;

  try {
    while (orchestrator.getState().status === 'running') {
      const job = orchestrator.getCurrentJob();
      if (!job) break;
      const epoch = runEpoch;

      // A single slow/broken/login-gated page must not halt the whole run:
      // navigation, extraction, and validation failures are recorded against
      // this job (skipCurrent) and the loop advances to the next one.
      try {
        await ensureTabAndNavigate(job.job_url);
        await sleep(1200); // let the SPA render job data
        const result = await tryEnrichCurrent(currentTabId);
        if (epoch !== runEpoch) continue; // the run changed while this job was open
        orchestrator.processExtraction(result); // may throw on empty/mismatch
      } catch (e) {
        if (epoch === runEpoch && orchestrator.getState().status === 'running') {
          orchestrator.skipCurrent(`Failed to extract ${job.external_id}: ${e.message}`);
        }
      }
      await saveState();
      await sleep(800); // brief pause between jobs to avoid rate limiting
    }
  } catch (e) {
    orchestrator.stop(e.message);
    await saveState();
  } finally {
    if (orchestrator.getState().status !== 'running') {
      await closeDedicatedTab();
    }
    isLoopRunning = false;
  }
}
