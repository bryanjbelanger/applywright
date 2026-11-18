document.addEventListener('DOMContentLoaded', async () => {
  const btnScan = document.getElementById('btn-scan');
  const btnScanAuto = document.getElementById('btn-scan-auto');
  const btnEnrich = document.getElementById('btn-enrich');
  const btnCancel = document.getElementById('btn-cancel');
  const btnExport = document.getElementById('btn-export');
  const btnCopy = document.getElementById('btn-copy');
  const btnDiagnostics = document.getElementById('btn-diagnostics');
  const btnClear = document.getElementById('btn-clear');
  const statusDiv = document.getElementById('status');

  let currentResult = null;

  // A scan result has metadata and a jobs list. A reply such as { error } is
  // not a result and must never reach storage or updateUI.
  function isScanResult(res) {
    return !!res && !res.error && !!res.metadata && typeof res.metadata === 'object' && Array.isArray(res.jobs);
  }

  async function loadState() {
    const data = await chrome.storage.local.get(['scanResult']);
    if (!data.scanResult) return;
    if (isScanResult(data.scanResult)) {
      currentResult = data.scanResult;
    } else {
      // A bad value from an earlier failed scan. Clear it so the popup opens.
      currentResult = null;
      await chrome.storage.local.remove(['scanResult']);
    }
    updateUI();
  }

  async function saveState(res) {
    if (!isScanResult(res)) {
      statusDiv.textContent = 'Scan failed: ' + ((res && res.error) ? res.error : 'no usable result returned.');
      return;
    }
    currentResult = res;
    // only save the sanitized result/diagnostics
    await chrome.storage.local.set({ scanResult: res });
    updateUI();
  }

  async function clearState() {
    currentResult = null;
    await chrome.storage.local.remove(['scanResult']);
    updateUI();
    statusDiv.innerHTML = "Results cleared.";
  }

  function updateUI() {
    if (!currentResult) {
      btnExport.disabled = true;
      btnCopy.disabled = true;
      btnDiagnostics.disabled = true;
      btnClear.disabled = true;
      return;
    }

    const { metadata } = currentResult;
    const hasJobs = metadata.exported_count > 0;
    
    btnExport.disabled = !hasJobs;
    btnCopy.disabled = !hasJobs;
    btnDiagnostics.disabled = false;
    btnClear.disabled = false;

    statusDiv.innerHTML = `
      <strong>URL:</strong> ${metadata.page_url}<br/>
      <strong>Cards Detected:</strong> ${metadata.detected_count}<br/>
      <strong>Jobs Exported:</strong> ${metadata.exported_count}<br/>
      <strong>Invalid Records:</strong> ${metadata.invalid_count}<br/>
      <strong>Duplicates:</strong> ${metadata.duplicate_count}<br/>
      <strong>Warnings:</strong> ${metadata.warning_count}<br/>
      <strong>Last Scan:</strong> ${metadata.exported_at}
    `;
  }

  async function getActiveTab() {
    const tabs = await chrome.tabs.query({ active: true, currentWindow: true });
    return tabs[0];
  }

  function formatFilename() {
    const d = new Date();
    const pad = n => n.toString().padStart(2, '0');
    return `jobcopilot-export-${d.getUTCFullYear()}${pad(d.getUTCMonth()+1)}${pad(d.getUTCDate())}-${pad(d.getUTCHours())}${pad(d.getUTCMinutes())}${pad(d.getUTCSeconds())}.json`;
  }

  btnScan.addEventListener('click', async () => {
    const tab = await getActiveTab();
    if (!tab || !tab.url || !tab.url.startsWith('https://app.jobcopilot.com/')) {
      statusDiv.innerHTML = "Error: Must be on https://app.jobcopilot.com/";
      return;
    }
    statusDiv.innerHTML = "Scanning...";
    try {
      const res = await chrome.tabs.sendMessage(tab.id, { action: 'scan_current', target_status: 'saved' });
      if (res) {
        await saveState(res);
      } else {
        statusDiv.innerHTML = "Scan returned empty result (check if cards exist).";
      }
    } catch (e) {
      statusDiv.innerHTML = "Scan failed. Ensure you are on the JobCopilot page and reload. " + e.message;
    }
  });

  let activePort = null;
  let scanFinished = false;

  function resetAutoScanUI() {
    btnScan.disabled = false;
    btnScanAuto.disabled = false;
    btnEnrich.disabled = false;
    btnCancel.disabled = true;
    activePort = null;
  }

  btnScanAuto.addEventListener('click', async () => {
    const tab = await getActiveTab();
    if (!tab || !tab.url || !tab.url.startsWith('https://app.jobcopilot.com/')) {
      statusDiv.innerHTML = "Error: Must be on https://app.jobcopilot.com/";
      return;
    }
    
    btnScan.disabled = true;
    btnScanAuto.disabled = true;
    btnEnrich.disabled = true;
    btnCancel.disabled = false;
    scanFinished = false;

    activePort = chrome.tabs.connect(tab.id, { name: 'auto_scroll_scan' });
    
    activePort.onMessage.addListener(async (msg) => {
      if (msg.status === 'scanning') {
        statusDiv.innerHTML = msg.message;
      } else if (msg.status === 'complete') {
        scanFinished = true;
        await saveState(msg.result);
        resetAutoScanUI();
      } else if (msg.status === 'cancelled') {
        scanFinished = true;
        statusDiv.innerHTML = "Scan cancelled.";
        resetAutoScanUI();
      }
    });

    activePort.onDisconnect.addListener(() => {
      if (!scanFinished) {
        statusDiv.innerHTML = "Auto-scroll scan disconnected before completion.";
        resetAutoScanUI();
      }
    });

    activePort.postMessage({ action: 'start_auto_scroll', target_status: 'saved' });
  });

  btnEnrich.addEventListener('click', async () => {
    btnEnrich.disabled = true;
    const tab = await getActiveTab();
    if (!tab || !tab.url) {
      statusDiv.innerHTML = "Error: Cannot determine tab URL.";
      resetAutoScanUI();
      return;
    }
    
    try {
      const urlObj = new URL(tab.url);
      if (urlObj.protocol !== 'https:' || urlObj.hostname !== 'app.jobcopilot.com') {
        statusDiv.innerHTML = "Error: Must be on https://app.jobcopilot.com/";
        resetAutoScanUI();
        return;
      }
      const match = urlObj.pathname.match(/^\/applications\/review\/([^\/]+)\/?$/);
      if (!match) {
        statusDiv.innerHTML = "Cannot enrich: Must be on a JobCopilot review page";
        resetAutoScanUI();
        return;
      }
    } catch (e) {
      statusDiv.innerHTML = "Error: Malformed URL.";
      resetAutoScanUI();
      return;
    }
    
    btnScan.disabled = true;
    btnCancel.disabled = true;
    statusDiv.innerHTML = "Extracting current job details...";
    
    try {
      const res = await chrome.tabs.sendMessage(tab.id, { action: 'enrich_current' });
      if (res && res.error) {
        statusDiv.innerHTML = "Enrichment failed: " + res.error;
      } else if (res) {
        await saveState(res);
      } else {
        statusDiv.innerHTML = "Enrichment returned empty result.";
      }
    } catch (e) {
      statusDiv.innerHTML = "Enrichment failed. Ensure the page has fully loaded. " + e.message;
    } finally {
      resetAutoScanUI();
    }
  });

  btnCancel.addEventListener('click', async () => {
    const tab = await getActiveTab();
    if (tab) {
      chrome.tabs.sendMessage(tab.id, { action: 'cancel_scan' });
    }
  });

  btnExport.addEventListener('click', () => {
    if (!currentResult) return;
    const blob = new Blob([JSON.stringify({ metadata: currentResult.metadata, jobs: currentResult.jobs }, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    chrome.downloads.download({
      url: url,
      filename: formatFilename()
    });
  });

  btnCopy.addEventListener('click', async () => {
    if (!currentResult) return;
    const text = JSON.stringify({ metadata: currentResult.metadata, jobs: currentResult.jobs }, null, 2);
    await navigator.clipboard.writeText(text);
    btnCopy.innerText = "Copied!";
    setTimeout(() => { btnCopy.innerText = "Copy JSON"; }, 2000);
  });

  btnDiagnostics.addEventListener('click', async () => {
    if (!currentResult) return;
    const text = JSON.stringify(currentResult.diagnostics, null, 2);
    await navigator.clipboard.writeText(text);
    btnDiagnostics.innerText = "Copied!";
    setTimeout(() => { btnDiagnostics.innerText = "Copy Diagnostics"; }, 2000);
  });

  btnClear.addEventListener('click', async () => {
    await clearState();
  });

  // --- BATCH ENRICHMENT ---
  const fileInput = document.getElementById('batch-queue-file');
  const btnBatchLoad = document.getElementById('btn-batch-load');
  const btnBatchStart = document.getElementById('btn-batch-start');
  const btnBatchResume = document.getElementById('btn-batch-resume');
  const btnBatchCancel = document.getElementById('btn-batch-cancel');
  const btnBatchExport = document.getElementById('btn-batch-export');
  const batchStatusDiv = document.getElementById('batch-status');
  
  let batchPollInterval = null;

  function updateBatchUI(state) {
    if (!state) return;
    
    const { status, queue, currentIndex, extractedJobs, stopped_reason } = state;
    const total = queue ? queue.length : 0;
    const extracted = extractedJobs ? extractedJobs.length : 0;
    const hasJobs = extracted > 0;
    const currentJob = queue && currentIndex < queue.length ? queue[currentIndex].external_id : 'None';

    btnBatchLoad.disabled = status === 'running';
    fileInput.disabled = status === 'running';
    btnBatchStart.disabled = status !== 'idle' || total === 0;
    btnBatchResume.disabled = status !== 'stopped' || total === 0;
    btnBatchCancel.disabled = status !== 'running';
    btnBatchExport.disabled = !hasJobs;

    let html = `<strong>Status:</strong> ${status.toUpperCase()}<br/>`;
    html += `<strong>Progress:</strong> ${currentIndex} / ${total}<br/>`;
    html += `<strong>Extracted:</strong> ${extracted}<br/>`;
    
    if (status === 'running') {
       html += `<strong>Processing:</strong> ${currentJob}<br/>`;
    }
    if (stopped_reason) {
       html += `<strong style="color:red;">Error/Stop Reason:</strong> ${stopped_reason}<br/>`;
    }

    batchStatusDiv.innerHTML = html;

    if (status === 'running' && !batchPollInterval) {
       batchPollInterval = setInterval(pollBatchStatus, 1000);
    } else if (status !== 'running' && batchPollInterval) {
       clearInterval(batchPollInterval);
       batchPollInterval = null;
    }
  }

  async function pollBatchStatus() {
    chrome.runtime.sendMessage({ action: 'get_batch_status' }, (res) => {
       if (res && res.state) {
         updateBatchUI(res.state);
       }
    });
  }

  pollBatchStatus();

  btnBatchLoad.addEventListener('click', () => {
    if (fileInput.files.length === 0) {
      batchStatusDiv.innerHTML = "Please select a JSON file first.";
      return;
    }
    const file = fileInput.files[0];
    const reader = new FileReader();
    reader.onload = function(e) {
      try {
        const payload = JSON.parse(e.target.result);
        chrome.runtime.sendMessage({ action: 'load_queue', payload: payload }, (res) => {
          if (res && res.error) {
            batchStatusDiv.innerHTML = `<span style="color:red">Error: ${res.error}</span>`;
          } else if (res && res.state) {
            updateBatchUI(res.state);
            fileInput.value = ""; // clear input
          }
        });
      } catch (err) {
        batchStatusDiv.innerHTML = `<span style="color:red">Invalid JSON file.</span>`;
      }
    };
    reader.readAsText(file);
  });

  btnBatchStart.addEventListener('click', () => {
    chrome.runtime.sendMessage({ action: 'start_batch' }, (res) => {
       if (res && res.error) {
         batchStatusDiv.innerHTML = `<span style="color:red">Error: ${res.error}</span>`;
       } else {
         pollBatchStatus();
       }
    });
  });

  btnBatchResume.addEventListener('click', () => {
    chrome.runtime.sendMessage({ action: 'resume_batch' }, (res) => {
       if (res && res.error) {
         batchStatusDiv.innerHTML = `<span style="color:red">Error: ${res.error}</span>`;
       } else {
         pollBatchStatus();
       }
    });
  });

  btnBatchCancel.addEventListener('click', () => {
    chrome.runtime.sendMessage({ action: 'cancel_batch' }, (res) => {
       pollBatchStatus();
    });
  });

  btnBatchExport.addEventListener('click', () => {
    chrome.runtime.sendMessage({ action: 'get_batch_export' }, (res) => {
       if (res && Array.isArray(res.payloads) && res.payloads.length > 0) {
          // One file per envelope: the bridge accepts at most 20 jobs per file.
          const total = res.payloads.length;
          const baseName = formatFilename();
          res.payloads.forEach((payload, index) => {
            const blob = new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json' });
            const url = URL.createObjectURL(blob);
            const suffix = total === 1 ? '-batch.json' : `-batch-${index + 1}of${total}.json`;
            chrome.downloads.download({
              url: url,
              filename: baseName.replace('.json', suffix)
            });
          });
       }
    });
  });

  // ---- Delete Flagged Jobs ----
  const deleteFileInput = document.getElementById('delete-list-file');
  const btnDeleteLoad = document.getElementById('btn-delete-load');
  const btnDeleteStart = document.getElementById('btn-delete-start');
  const btnDeleteCancel = document.getElementById('btn-delete-cancel');
  const deleteStatusDiv = document.getElementById('delete-status');
  let deleteIds = [];
  let deletePort = null;
  let deleteConfirmArmed = false;

  // Accept JSON ({external_ids:[...]}, {jobs:[{external_id}]}, or a bare array)
  // or CSV (external_id in the first column; header row skipped).
  function parseDeleteList(text, name) {
    const ids = [];
    const push = (v) => { const s = String(v == null ? '' : v).trim(); if (/^[A-Za-z0-9_-]+$/.test(s)) ids.push(s); };
    if (/\.csv$/i.test(name) || !/^\s*[\[{]/.test(text)) {
      const lines = text.split(/\r?\n/).filter(l => l.trim());
      let start = /external_id/i.test(lines[0] || '') ? 1 : 0;
      for (let i = start; i < lines.length; i++) push(lines[i].split(',')[0]);
    } else {
      const data = JSON.parse(text);
      const arr = Array.isArray(data) ? data : (data.external_ids || data.jobs || []);
      for (const item of arr) push(item && typeof item === 'object' ? item.external_id : item);
    }
    return Array.from(new Set(ids));
  }

  function resetDeleteButtons() {
    btnDeleteCancel.disabled = true;
    btnDeleteLoad.disabled = false;
    deleteFileInput.disabled = false;
    btnDeleteStart.disabled = deleteIds.length === 0;
  }

  if (btnDeleteLoad && btnDeleteStart && btnDeleteCancel && deleteFileInput && deleteStatusDiv) {
  btnDeleteLoad.addEventListener('click', () => {
    if (!deleteFileInput.files.length) { deleteStatusDiv.innerHTML = 'Select a .json or .csv list first.'; return; }
    const reader = new FileReader();
    reader.onload = (e) => {
      try {
        deleteIds = parseDeleteList(e.target.result, deleteFileInput.files[0].name);
        deleteConfirmArmed = false;
        btnDeleteStart.disabled = deleteIds.length === 0;
        deleteStatusDiv.innerHTML = 'Loaded <strong>' + deleteIds.length + '</strong> job IDs. Click "Delete Flagged on JobCopilot" to begin (you confirm once).';
      } catch (err) {
        deleteStatusDiv.innerHTML = '<span style="color:red">Could not parse list: ' + err.message + '</span>';
      }
    };
    reader.readAsText(deleteFileInput.files[0]);
  });

  btnDeleteStart.addEventListener('click', async () => {
    if (deleteIds.length === 0) return;
    if (!deleteConfirmArmed) {
      deleteConfirmArmed = true;
      deleteStatusDiv.innerHTML = '<span style="color:#b00"><strong>Permanently delete ' + deleteIds.length +
        ' jobs from JobCopilot?</strong> This cannot be undone. Click the button again to confirm.</span>';
      return;
    }
    deleteConfirmArmed = false;
    btnDeleteStart.disabled = true;
    btnDeleteLoad.disabled = true;
    deleteFileInput.disabled = true;

    const tab = await getActiveTab();
    if (!tab || !/app\.jobcopilot\.com\/applications/.test(tab.url || '')) {
      deleteStatusDiv.innerHTML = '<span style="color:red">Open the JobCopilot Applications page in this tab first.</span>';
      resetDeleteButtons();
      return;
    }
    deletePort = chrome.tabs.connect(tab.id, { name: 'delete_flagged' });
    btnDeleteCancel.disabled = false;
    deletePort.onMessage.addListener((msg) => {
      if (msg.status === 'deleting') {
        deleteStatusDiv.innerHTML = msg.message;
      } else if (msg.status === 'complete') {
        const r = msg.result || {};
        deleteStatusDiv.innerHTML = '<strong>Done.</strong> Deleted ' + (r.deleted || []).length +
          ', failed ' + (r.failed || []).length + ', not found ' + (r.not_found || []).length + '.';
        resetDeleteButtons();
      } else if (msg.status === 'error') {
        deleteStatusDiv.innerHTML = '<span style="color:red">' + msg.message + '</span>';
        resetDeleteButtons();
      }
    });
    deletePort.postMessage({ action: 'start_delete', external_ids: deleteIds });
    deleteStatusDiv.innerHTML = 'Deleting ' + deleteIds.length + '... keep this popup open (it will keep running if it closes, and the result is saved).';
  });

  btnDeleteCancel.addEventListener('click', () => {
    if (deletePort) { try { deletePort.postMessage({ action: 'cancel_delete' }); } catch (_) {} }
    deleteStatusDiv.innerHTML = 'Cancelling after the current card...';
  });

  // Reflect persisted delete progress/result on open and poll it, so reopening
  // the popup shows live progress even when the run outlived the last popup or
  // is happening on another tab. Skipped while loading a list, confirming, or in
  // an active local session (so it can't clobber those prompts).
  function refreshDeleteFromStorage() {
    if (deleteIds.length > 0 || deletePort) return;
    chrome.storage.local.get(['deleteResult'], (data) => {
      const r = data && data.deleteResult;
      if (r && r.message) {
        deleteStatusDiv.innerHTML = r.message + (r.in_progress ? ' <em>(running — stays updating while this popup is open)</em>' : '');
      }
    });
  }
  refreshDeleteFromStorage();
  setInterval(refreshDeleteFromStorage, 2500);
  }

  // ---- Apply form filler ----
  // Fills the standard fields of an application form from a loaded apply bundle.
  // It never submits. Frames with a form answer with an 'apply_report' message.
  const applyFileInput = document.getElementById('apply-bundle-file');
  const btnApplyLoad = document.getElementById('btn-apply-load');
  const btnApplyFill = document.getElementById('btn-apply-fill');
  const btnApplySave = document.getElementById('btn-apply-save');
  const applyStatusDiv = document.getElementById('apply-status');
  const applyReportList = document.getElementById('apply-report');
  const APPLY_FILL_TIMEOUT_MS = 25000;

  if (applyFileInput && btnApplyLoad && btnApplyFill && btnApplySave && applyStatusDiv) {
    let applyBundle = null;
    let applyRequestId = null;
    let applyBestReport = null;
    let applyTimer = null;
    let confirmation = null;
    let confirmationTabUrl = '';

    function isApplyBundle(b) {
      return !!b && b.bundle_version === 1 && typeof b.slug === 'string' && !!b.applicant &&
        !!b.files && !!b.files.resume && typeof b.files.resume.base64 === 'string';
    }

    function showBundle() {
      if (!applyBundle) {
        applyStatusDiv.textContent = 'No apply bundle loaded.';
      } else {
        applyStatusDiv.textContent = 'Bundle: ' + applyBundle.slug + ' | ' + applyBundle.company + ' | ' + applyBundle.title;
      }
      updateApplyButtons();
    }

    function updateApplyButtons() {
      btnApplyFill.disabled = !applyBundle;
      btnApplySave.disabled = !(applyBundle && confirmation);
    }

    function renderReport(report) {
      if (!applyReportList) return;
      applyReportList.textContent = '';
      const rows = [
        ['Filled', report.filled],
        ['Attached', report.attached],
        ['Left for you', report.left_for_you],
        ['Required and still empty', report.unfilled_required],
      ];
      for (const [title, items] of rows) {
        const li = document.createElement('li');
        li.textContent = title + ': ' + ((items && items.length) ? items.join('; ') : 'none');
        applyReportList.appendChild(li);
      }
    }

    function reportScore(report) {
      return (report.filled || []).length + (report.attached || []).length;
    }

    function newRequestId() {
      return String(Date.now()) + '-' + Math.random().toString(36).slice(2, 8);
    }

    chrome.storage.local.get(['applyBundle']).then((data) => {
      if (data && isApplyBundle(data.applyBundle)) applyBundle = data.applyBundle;
      showBundle();
    });

    if (chrome.runtime.onMessage) {
      chrome.runtime.onMessage.addListener((msg) => {
        if (!msg) return;
        if (msg.action === 'apply_report' && msg.request_id === applyRequestId) {
          if (!applyBestReport || reportScore(msg.report) >= reportScore(applyBestReport)) {
            applyBestReport = msg.report;
            renderReport(msg.report);
          }
          if (applyTimer) { clearTimeout(applyTimer); applyTimer = null; }
          applyStatusDiv.textContent = 'Form filled (' + msg.system + '). Review every field, answer the rest, and click Submit yourself.';
          btnApplyFill.disabled = false;
        } else if (msg.action === 'apply_confirmation') {
          confirmation = { text: msg.text || '', frame_url: msg.frame_url || '' };
          applyStatusDiv.textContent = 'Confirmation page detected. You can save a submission record.';
          updateApplyButtons();
        }
      });
    }

    btnApplyLoad.addEventListener('click', () => {
      if (!applyFileInput.files.length) { applyStatusDiv.textContent = 'Select an apply bundle .json file first.'; return; }
      const reader = new FileReader();
      reader.onload = async (e) => {
        let bundle;
        try { bundle = JSON.parse(e.target.result); } catch (err) { applyStatusDiv.textContent = 'Invalid JSON file.'; return; }
        if (!isApplyBundle(bundle)) { applyStatusDiv.textContent = 'Not an apply bundle (bundle_version 1 with applicant and files.resume).'; return; }
        try {
          await chrome.storage.local.set({ applyBundle: bundle });
        } catch (err) {
          applyStatusDiv.textContent = 'Could not store the bundle: ' + err.message;
          return;
        }
        applyBundle = bundle;
        applyFileInput.value = '';
        showBundle();
      };
      reader.readAsText(applyFileInput.files[0]);
    });

    btnApplyFill.addEventListener('click', async () => {
      if (!applyBundle) return;
      const tab = await getActiveTab();
      if (!tab) { applyStatusDiv.textContent = 'No active tab.'; return; }
      applyRequestId = newRequestId();
      applyBestReport = null;
      if (applyReportList) applyReportList.textContent = '';
      btnApplyFill.disabled = true;
      applyStatusDiv.textContent = 'Filling... waiting for the form.';
      if (applyTimer) clearTimeout(applyTimer);
      applyTimer = setTimeout(() => {
        applyTimer = null;
        if (!applyBestReport) {
          applyStatusDiv.textContent = 'No supported form found in this tab (Greenhouse, Lever, or Ashby).';
          btnApplyFill.disabled = false;
        }
      }, APPLY_FILL_TIMEOUT_MS);
      try {
        await chrome.tabs.sendMessage(tab.id, { action: 'apply_fill', request_id: applyRequestId, bundle: applyBundle });
      } catch (err) {
        if (applyTimer) { clearTimeout(applyTimer); applyTimer = null; }
        applyStatusDiv.textContent = 'Cannot reach the page. Open a Greenhouse, Lever, or Ashby application page and reload it. ' + err.message;
        btnApplyFill.disabled = false;
      }
    });

    btnApplySave.addEventListener('click', () => {
      if (!applyBundle || !confirmation) return;
      const record = {
        job_id: applyBundle.job_id,
        package_slug: applyBundle.slug,
        application_source_url: confirmationTabUrl,
        submitted_at: new Date().toISOString(),
        confirmation_text: confirmation.text,
      };
      chrome.downloads.download({
        url: 'data:application/json;charset=utf-8,' + encodeURIComponent(JSON.stringify(record, null, 2) + '\n'),
        filename: 'submission-' + applyBundle.slug + '.json',
      });
      applyStatusDiv.textContent = 'Saved submission-' + applyBundle.slug + '.json. Tell the user to record the status.';
    });

    // Ask every frame of the active tab whether it shows a confirmation page.
    (async () => {
      try {
        const tab = await getActiveTab();
        if (!tab) return;
        confirmationTabUrl = tab.url || '';
        await chrome.tabs.sendMessage(tab.id, { action: 'apply_check_confirmation', request_id: newRequestId() });
      } catch (err) { /* page has no apply script: nothing to detect */ }
    })();
  }

  loadState();
});
