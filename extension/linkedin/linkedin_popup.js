// Popup logic for "Capture this LinkedIn job". Kept apart from popup.js.
document.addEventListener('DOMContentLoaded', async () => {
  const btn = document.getElementById('btn-linkedin-capture');
  const statusDiv = document.getElementById('linkedin-status');
  if (!btn) return;

  const LINKEDIN_JOBS = /^https:\/\/www\.linkedin\.com\/jobs\//;
  const say = (text) => {
    if (statusDiv) statusDiv.textContent = text;
  };

  async function activeTab() {
    const tabs = await chrome.tabs.query({ active: true, currentWindow: true });
    return tabs[0];
  }

  function buildEnvelope(job, pageUrl) {
    return {
      metadata: {
        source: 'linkedin',
        export_kind: 'linkedin_capture',
        exported_at: new Date().toISOString(),
        extension_version: chrome.runtime.getManifest().version,
        page_url: pageUrl,
      },
      jobs: [job],
    };
  }

  btn.disabled = true;
  try {
    const tab = await activeTab();
    btn.disabled = !(tab && tab.url && LINKEDIN_JOBS.test(tab.url));
  } catch (e) {
    btn.disabled = true;
  }

  btn.addEventListener('click', async () => {
    const tab = await activeTab();
    if (!tab || !tab.url || !LINKEDIN_JOBS.test(tab.url)) {
      say('Open a LinkedIn jobs page first.');
      return;
    }
    let res;
    try {
      res = await chrome.tabs.sendMessage(tab.id, { action: 'linkedin_capture' });
    } catch (e) {
      say('Cannot reach the page. Reload the LinkedIn tab and try again.');
      return;
    }
    if (!res || !res.ok) {
      say(`Capture failed: ${(res && res.error) || 'no response'}`);
      return;
    }
    const envelope = buildEnvelope(res.job, tab.url);
    const blob = new Blob([JSON.stringify(envelope, null, 2)], { type: 'application/json' });
    chrome.downloads.download({
      url: URL.createObjectURL(blob),
      filename: `linkedin-capture-${res.job.external_id}.json`,
      saveAs: true,
    });
    say(`Captured job ${res.job.external_id}: ${res.job.title} (${res.job.apply_type}).`);
  });
});
