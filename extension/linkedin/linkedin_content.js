// Passive listener. It does nothing until the popup sends 'linkedin_capture'.
(function () {
  if (typeof chrome === 'undefined' || !chrome.runtime || !chrome.runtime.onMessage) return;
  chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
    if (!msg || msg.action !== 'linkedin_capture') return false;
    try {
      sendResponse(globalThis.ApplywrightExtension.linkedin.extractJob(document, window.location.href));
    } catch (e) {
      sendResponse({ ok: false, error: String(e && e.message ? e.message : e) });
    }
    return false;
  });
})();
