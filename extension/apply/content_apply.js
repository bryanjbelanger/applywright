// Content script for the apply pages. It runs one field map per host, fills the
// form when the popup asks, and reports to the popup with a runtime message.
// Every frame that has a form reports. Frames without a form stay silent.
// This script never submits a form and never clicks a control.
(function (root) {
  'use strict';
  const MAPS = root.ApplyMaps || {};
  const map = MAPS.greenhouse || MAPS.lever || MAPS.ashby;
  if (!map || !root.chrome || !root.chrome.runtime || !root.chrome.runtime.onMessage) return;
  const Fill = root.ApplyFill;

  async function handleFill(msg) {
    const found = await Fill.waitFor(() => Fill.hasForm(document, map), { timeoutMs: map.waitMs, intervalMs: 250 });
    if (!found) return;
    const report = Fill.fillForm(document, msg.bundle, map);
    chrome.runtime.sendMessage({
      action: 'apply_report', request_id: msg.request_id, system: map.system,
      frame_url: location.href, report,
    });
  }

  function handleCheck(msg) {
    const result = Fill.detectConfirmation(document, location.href);
    if (!result.confirmed) return;
    chrome.runtime.sendMessage({
      action: 'apply_confirmation', request_id: msg.request_id, system: map.system,
      frame_url: location.href, text: result.text,
    });
  }

  chrome.runtime.onMessage.addListener((msg) => {
    if (!msg) return false;
    if (msg.action === 'apply_fill') handleFill(msg);
    else if (msg.action === 'apply_check_confirmation') handleCheck(msg);
    return false;
  });
})(typeof globalThis !== 'undefined' ? globalThis : this);
