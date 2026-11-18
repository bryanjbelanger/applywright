globalThis.ApplywrightExtension = globalThis.ApplywrightExtension || {};

globalThis.ApplywrightExtension.content = {
  isScanning: false,
  cancelScan: false,
  isDeleting: false,
  cancelDelete: false,

  extractNearbyStatusLabel(listElement, supportedStatuses) {
    const statusRegex = new RegExp(`^\\s*(${supportedStatuses.join('|')})\\b(?:\\s*\\((\\d+)\\))?`, 'i');
    let current = listElement;
    let depth = 0;
    
    const getDirectText = (el) => {
      let text = '';
      if (!el.childNodes) return text;
      for (const node of el.childNodes) {
        if (node.nodeType === 3) text += node.textContent;
      }
      return text.trim();
    };

    while (current && current !== document.body && depth < 5) {
      let sibling = current.previousElementSibling;
      while (sibling) {
        if (sibling.querySelector && sibling.querySelector('.at-card')) {
          sibling = sibling.previousElementSibling;
          continue;
        }

        const candidates = [sibling, ...Array.from(sibling.querySelectorAll ? sibling.querySelectorAll('div, p, span, h1, h2, h3, h4, h5, h6, button, [role="tab"]') : [])];
        for (const cand of candidates) {
          if (cand.querySelector && cand.querySelector('.at-card')) continue;
          
          let textCandidates = [];
          if (cand.getAttribute) {
            if (cand.getAttribute('aria-label')) textCandidates.push(cand.getAttribute('aria-label'));
            if (cand.getAttribute('data-status')) textCandidates.push(cand.getAttribute('data-status'));
            if (cand.getAttribute('data-state')) textCandidates.push(cand.getAttribute('data-state'));
          }
          textCandidates.push(getDirectText(cand));
          if (!cand.querySelector || !cand.querySelector('.at-card')) {
            textCandidates.push((cand.textContent || '').trim());
          }
          
          for (const text of textCandidates) {
            if (!text) continue;
            const match = text.match(statusRegex);
            if (match) {
              return { status: match[1].toLowerCase(), declared_count: match[2] ? parseInt(match[2], 10) : 0 };
            }
          }
        }
        sibling = sibling.previousElementSibling;
      }
      
      if (current.parentElement) {
        for (const child of current.parentElement.children) {
          if (child === listElement || child.contains(listElement)) continue;
          if (child.querySelector && child.querySelector('.at-card')) continue;

          const candidates = [child, ...Array.from(child.querySelectorAll ? child.querySelectorAll('div, p, span, h1, h2, h3, h4, h5, h6, button, [role="tab"]') : [])];
          for (const cand of candidates) {
            if (cand.querySelector && cand.querySelector('.at-card')) continue;
            
            let textCandidates = [];
            if (cand.getAttribute) {
              if (cand.getAttribute('aria-label')) textCandidates.push(cand.getAttribute('aria-label'));
              if (cand.getAttribute('data-status')) textCandidates.push(cand.getAttribute('data-status'));
              if (cand.getAttribute('data-state')) textCandidates.push(cand.getAttribute('data-state'));
            }
            textCandidates.push(getDirectText(cand));
            if (!cand.querySelector || !cand.querySelector('.at-card')) {
              textCandidates.push((cand.textContent || '').trim());
            }
            
            for (const text of textCandidates) {
              if (!text) continue;
              const match = text.match(statusRegex);
              if (match) {
                return { status: match[1].toLowerCase(), declared_count: match[2] ? parseInt(match[2], 10) : 0 };
              }
            }
          }
        }
      }
      
      current = current.parentElement;
      depth++;
    }
    return null;
  },

  findJobList(documentObj, targetStatus = "saved") {
    const candidates = Array.from(documentObj.querySelectorAll('.at-card'));
    const visibleCandidates = [];
    const supportedStatuses = ['saved', 'applied', 'screening', 'interview', 'rejected', 'withdrawn', 'offer'];
    const detectedStatuses = [];

    for (const el of candidates) {
      if (el.getClientRects && el.getClientRects().length === 0) continue;
      
      const style = window.getComputedStyle ? window.getComputedStyle(el) : { display: '', visibility: '' };
      if (style.display === 'none' || style.visibility === 'hidden') continue;
      if (el.clientHeight === 0) continue;
      
      const cards = el.querySelectorAll('div.shadow-card, .shadow-card, [data-testid="job-card"], .job-card, article');
      if (cards.length === 0) continue;
      
      const rect = el.getBoundingClientRect ? el.getBoundingClientRect() : { width: 0, height: 0 };
      const area = rect.width * rect.height;
      
      const detected = this.extractNearbyStatusLabel(el, supportedStatuses);
      if (detected) {
        detectedStatuses.push(detected);
      }
      
      visibleCandidates.push({
        element: el,
        area: area,
        cardCount: cards.length,
        detected: detected
      });
    }

    const matchingCandidates = visibleCandidates.filter(c => c.detected && c.detected.status === targetStatus.toLowerCase());
    let selected = null;
    
    if (matchingCandidates.length === 1) {
      selected = matchingCandidates[0];
    } else if (matchingCandidates.length > 1) {
      matchingCandidates.sort((a, b) => {
        if (b.area !== a.area) return b.area - a.area;
        return b.cardCount - a.cardCount;
      });
      selected = matchingCandidates[0];
    } else {
      if (visibleCandidates.length === 1 && (!visibleCandidates[0].detected || !supportedStatuses.includes(visibleCandidates[0].detected.status))) {
        selected = visibleCandidates[0];
      }
    }
    
    const diagnostics = {
      requested_status: targetStatus,
      detected_status: selected && selected.detected ? selected.detected.status : (selected ? "unknown" : null),
      declared_count: selected && selected.detected ? selected.detected.declared_count : 0,
      candidate_count: candidates.length,
      visible_candidate_count: visibleCandidates.length,
      matching_candidate_count: matchingCandidates.length,
      detected_statuses: detectedStatuses
    };

    if (selected) {
      diagnostics.selected_card_count = selected.cardCount;
      diagnostics.selected_client_height = selected.element.clientHeight;
      diagnostics.selected_scroll_height = selected.element.scrollHeight;
    }

    return {
      element: selected ? selected.element : null,
      diagnostics: diagnostics
    };
  },

  async doScan(targetStatus = "saved") {
    const { extract } = globalThis.ApplywrightExtension;
    const listResult = this.findJobList(document, targetStatus);
    
    if (!listResult.element) {
      return {
        metadata: {
          source: 'jobcopilot',
          exported_at: new Date().toISOString(),
          page_url: location.href,
          detected_count: 0,
          exported_count: 0,
          invalid_count: 0,
          duplicate_count: 0,
          warning_count: 1,
          extension_version: "0.1.0"
        },
        jobs: [],
        diagnostics: {
          page_url: location.href,
          scanned_at: new Date().toISOString(),
          card_count: 0,
          records: [],
          warnings: [`No visible ${targetStatus.charAt(0).toUpperCase() + targetStatus.slice(1)} JobCopilot application list was found.`]
        }
      };
    }
    
    const rawReport = extract.scanDOM(listResult.element, location.href, targetStatus);
    const result = extract.processRecords(rawReport, location.href);
    result.diagnostics.list_container = listResult.diagnostics;
    return result;
  },

  async autoScrollScan(port, targetStatus = "saved") {
    // The popup owns this port and Chrome tears the popup down the instant it
    // loses focus, so any postMessage can hit a disconnected port mid-scan.
    // Route every message through a guard so a closed popup never throws an
    // uncaught rejection that aborts the (page-resident) scan.
    const post = (m) => { try { port.postMessage(m); } catch (_) { /* popup/port closed */ } };
    // Persist results to storage too, so a scan that finishes after the popup
    // has closed is not lost — the popup reloads scanResult when reopened.
    const persist = async (r) => { try { await chrome.storage.local.set({ scanResult: r }); } catch (_) {} };

    if (this.isScanning) {
      post({ status: 'scanning', message: 'A scan is already running.' });
      return;
    }
    this.isScanning = true;
    this.cancelScan = false;
    
    const maxScrolls = 200;
    const maxRuntime = 180000;
    const waitTime = 1800;
    
    let stableChecks = 0;
    let lastUniqueCount = 0;
    let lastScrollHeight = 0;
    let scrolls = 0;
    const startTime = Date.now();
    
    const listResult = this.findJobList(document, targetStatus);
    
    if (!listResult.element) {
      const emptyResult = {
        metadata: {
          source: 'jobcopilot',
          exported_at: new Date().toISOString(),
          page_url: location.href,
          detected_count: 0,
          exported_count: 0,
          invalid_count: 0,
          duplicate_count: 0,
          warning_count: 1,
          extension_version: "0.1.0"
        },
        jobs: [],
        diagnostics: {
          page_url: location.href,
          scanned_at: new Date().toISOString(),
          card_count: 0,
          records: [],
          warnings: [`No visible ${targetStatus.charAt(0).toUpperCase() + targetStatus.slice(1)} JobCopilot application list was found.`]
        }
      };
      await persist(emptyResult);
      post({ status: 'complete', result: emptyResult });
      this.isScanning = false;
      return emptyResult;
    }
    
    const scrollContainer = listResult.element;
    const originalScroll = scrollContainer.scrollTop;

    const { extract } = globalThis.ApplywrightExtension;
    let accumulatedRecords = [];
    // Dedupe records as they are collected. Each scroll round re-scans every
    // card currently in the DOM, so a naive push re-adds the whole visible set
    // every iteration — on a ~500-card list that balloons into tens of thousands
    // of duplicate objects and overflows the 64 MiB port/storage message limit.
    const seenKeys = new Set();
    const addRecords = (records) => {
      for (const rec of records) {
        // Identity lives under rec.job_data (external_id / job_url); the record
        // itself has no top-level id. Key on that so repeated scans of the same
        // card collapse to one entry. Invalid records (no job_data) fall back to
        // a structural key.
        const jd = rec && rec.job_data;
        const key = (jd && (jd.external_id || jd.job_url)) || JSON.stringify(rec);
        if (seenKeys.has(key)) continue;
        seenKeys.add(key);
        accumulatedRecords.push(rec);
      }
    };

    post({ status: 'scanning', message: 'Started auto-scan...' });

    let rawReport = extract.scanDOM(scrollContainer, location.href, targetStatus);
    addRecords(rawReport.records);

    let tempResult = extract.processRecords({ card_count: rawReport.card_count, records: accumulatedRecords }, location.href);
    lastUniqueCount = tempResult.metadata.exported_count;
    lastScrollHeight = scrollContainer.scrollHeight;

    while (!this.cancelScan && scrolls < maxScrolls && (Date.now() - startTime) < maxRuntime) {
      // Drive the infinite-scroll list to its current bottom. Pulling the last
      // rendered card into view AND pinning scrollTop to scrollHeight is far more
      // reliable at triggering JobCopilot's lazy append than the previous
      // 0.8-viewport nudge, which could stall on large lists.
      const cardLinks = scrollContainer.querySelectorAll('a[href*="/applications/review/"]');
      if (cardLinks.length) {
        cardLinks[cardLinks.length - 1].scrollIntoView({ block: 'end' });
      }
      scrollContainer.scrollTop = scrollContainer.scrollHeight;
      scrolls++;

      // Fixed settle wait so appended cards have time to fetch and render. The
      // old MutationObserver resolved on the FIRST mutation — typically the
      // loading spinner, not the new cards — which made large/slow saved lists
      // report "stable" and stop after only the first screenful.
      await new Promise(resolve => setTimeout(resolve, waitTime));

      rawReport = extract.scanDOM(scrollContainer, location.href, targetStatus);
      addRecords(rawReport.records);

      tempResult = extract.processRecords({ card_count: accumulatedRecords.length, records: accumulatedRecords }, location.href);
      const currentUniqueCount = tempResult.metadata.exported_count;
      const currentScrollHeight = scrollContainer.scrollHeight;
      const newScrollTop = scrollContainer.scrollTop;

      post({
        status: 'scanning',
        message: `Unique jobs: ${currentUniqueCount}\nCard observations: ${accumulatedRecords.length}\nScroll: ${scrolls}\nPosition: ${Math.round(newScrollTop)} / ${currentScrollHeight}`
      });

      // Only conclude the list is exhausted after several consecutive settle
      // rounds add zero new unique jobs while parked at the bottom. Requiring 5
      // (was 3, and gated on an exact scrollHeight match) tolerates slow appends
      // on large saved lists — the regression that capped exports to ~1 screen.
      const atBottom = (newScrollTop + scrollContainer.clientHeight) >= (currentScrollHeight - 6);
      if (currentUniqueCount === lastUniqueCount) {
        stableChecks++;
        if (atBottom && stableChecks >= 5) break;
      } else {
        stableChecks = 0;
      }

      lastUniqueCount = currentUniqueCount;
      lastScrollHeight = currentScrollHeight;
    }

    scrollContainer.scrollTop = originalScroll;
    this.isScanning = false;
    
    if (this.cancelScan) {
      post({ status: 'cancelled', message: 'Scan cancelled' });
      return null;
    }

    const finalReport = { card_count: accumulatedRecords.length, records: accumulatedRecords };
    const result = extract.processRecords(finalReport, location.href);
    result.diagnostics.list_container = listResult.diagnostics;
    await persist(result);
    post({ status: 'complete', result: result });
    return result;
  },

  async deleteFlagged(port, externalIds) {
    // Permanently delete a caller-supplied list of saved jobs by driving the
    // card UI (trash icon -> "Confirm" popover), which fires JobCopilot's own
    // authenticated DELETE. STRICTLY bounded to the external_ids passed in: it
    // only ever clicks the trash on a card whose review link matches an id on
    // the list, so nothing off the list can be deleted. One at a time, so the
    // single visible Confirm always belongs to the card just armed.
    const post = (m) => { try { port.postMessage(m); } catch (_) {} };
    const persist = async (r) => { try { await chrome.storage.local.set({ deleteResult: r }); } catch (_) {} };
    const sleep = ms => new Promise(r => setTimeout(r, ms));

    if (this.isDeleting) { post({ status: 'error', message: 'A delete run is already in progress.' }); return; }
    this.isDeleting = true;
    this.cancelDelete = false;

    const link0 = document.querySelector('a[href*="/applications/review/"]');
    let cont = link0;
    while (cont && !(cont.classList && cont.classList.contains('at-card'))) cont = cont.parentElement;
    // Match the id exactly. A substring match would let id 123 find the card for 1234.
    const reviewId = (a) => {
      const m = (a.getAttribute('href') || '').match(/\/applications\/review\/([A-Za-z0-9_-]+)\/?(?:[?#]|$)/);
      return m ? m[1] : null;
    };
    const findCard = (id) => {
      const links = document.querySelectorAll('a[href*="/applications/review/"]');
      for (const a of links) {
        if (reviewId(a) === id) return a.closest('.shadow-card');
      }
      return null;
    };

    const remaining = new Set((externalIds || []).map(String).filter(Boolean));
    const result = { requested: remaining.size, deleted: [], failed: [], not_found: [] };
    const startTime = Date.now();
    post({ status: 'deleting', message: 'Starting: ' + remaining.size + ' to delete' });

    let idleScrolls = 0;
    while (remaining.size > 0 && !this.cancelDelete && (Date.now() - startTime) < 600000) {
      let didOne = false;
      for (const id of Array.from(remaining)) {
        if (this.cancelDelete) break;
        const card = findCard(id);
        if (!card) continue; // not in the DOM yet; a scroll pass below loads more
        const trashSvg = card.querySelector('svg[class*="ic_trash"]');
        const wrap = trashSvg ? trashSvg.closest('div.cursor-pointer') : null;
        if (!wrap) { remaining.delete(id); result.failed.push({ id: id, reason: 'no trash control' }); continue; }
        // Another job can already show a confirmation. Only a prompt that this
        // click opens may be confirmed: one inside this card, or a new one that
        // is not inside any other card.
        const visibleConfirms = () => Array.from(document.querySelectorAll('button')).filter(b => b.offsetParent !== null && /^confirm$/i.test((b.textContent || '').trim()));
        const preexisting = new Set(visibleConfirms());
        wrap.click();
        let confirmBtn = null;
        for (let t = 0; t < 15 && !confirmBtn; t++) {
          await sleep(120);
          confirmBtn = visibleConfirms().find(b => {
            const owner = b.closest('.shadow-card');
            return owner ? owner === card : !preexisting.has(b);
          }) || null;
        }
        if (!confirmBtn) { remaining.delete(id); result.failed.push({ id: id, reason: 'no confirm prompt' }); continue; }
        confirmBtn.click();
        let removed = false;
        for (let t = 0; t < 25 && !removed; t++) { await sleep(150); removed = !findCard(id); }
        remaining.delete(id);
        if (removed) { result.deleted.push(id); didOne = true; }
        else { result.failed.push({ id: id, reason: 'card not removed after confirm' }); }
        const msg = 'Deleted ' + result.deleted.length + '/' + result.requested + ' (failed ' + result.failed.length + ')';
        post({ status: 'deleting', message: msg });
        // Persist progress every step so the popup can show it after reopening.
        await persist({ requested: result.requested, deleted: result.deleted, failed: result.failed, remaining: remaining.size, in_progress: true, message: msg });
        await sleep(250);
      }
      if (this.cancelDelete) break;
      if (!didOne) {
        // none of the remaining targets are currently rendered; load more
        const msg = 'Deleted ' + result.deleted.length + '/' + result.requested + ' — scrolling to find ' + remaining.size + ' more...';
        post({ status: 'deleting', message: msg });
        await persist({ requested: result.requested, deleted: result.deleted, failed: result.failed, remaining: remaining.size, in_progress: true, message: msg });
        if (cont) cont.scrollTop = cont.scrollHeight;
        const links = cont ? cont.querySelectorAll('a[href*="/applications/review/"]') : [];
        if (links.length) links[links.length - 1].scrollIntoView({ block: 'end' });
        await sleep(1500);
        idleScrolls++;
        if (idleScrolls >= 8) break; // remaining targets not found after repeated scrolls
      } else {
        idleScrolls = 0;
      }
    }
    for (const id of remaining) result.not_found.push(id);
    this.isDeleting = false;
    result.in_progress = false;
    result.message = 'Done. Deleted ' + result.deleted.length + ', failed ' + result.failed.length + ', not found ' + result.not_found.length + '.';
    await persist(result);
    post({ status: 'complete', result: result });
    return result;
  }
};

chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  if (msg.action === 'scan_current') {
    globalThis.ApplywrightExtension.content.doScan(msg.target_status || "saved")
      .then(sendResponse)
      .catch(e => { try { sendResponse({ error: String((e && e.message) || e) }); } catch (_) {} });
    return true; // Keep channel open
  }
  if (msg.action === 'enrich_current') {
    try {
      const result = globalThis.ApplywrightExtension.extract.extractCurrentPage(document, location.href);
      sendResponse(result);
    } catch(e) {
      sendResponse({ error: e.message });
    }
    return false;
  }
  if (msg.action === 'cancel_scan') {
    globalThis.ApplywrightExtension.content.cancelScan = true;
    sendResponse({ ok: true });
  }
});

chrome.runtime.onConnect.addListener(port => {
  if (port.name === 'auto_scroll_scan') {
    if (port._hasListener) return;
    port._hasListener = true;
    port.onMessage.addListener(msg => {
      if (msg.action === 'start_auto_scroll') {
        // autoScrollScan is async and long-running; the popup (which owns this
        // port) can close mid-scan. Attach a catch so a rejection from any awaited
        // step can never become an "Uncaught (in promise)" — reset scan state and
        // best-effort notify the port (guarded; it may already be disconnected).
        Promise.resolve(
          globalThis.ApplywrightExtension.content.autoScrollScan(port, msg.target_status || "saved")
        ).catch(err => {
          globalThis.ApplywrightExtension.content.isScanning = false;
          try { port.postMessage({ status: 'error', message: String((err && err.message) || err) }); } catch (_) {}
        });
      }
    });
  }

  if (port.name === 'delete_flagged') {
    if (port._hasListener) return;
    port._hasListener = true;
    port.onMessage.addListener(msg => {
      if (msg.action === 'start_delete') {
        Promise.resolve(
          globalThis.ApplywrightExtension.content.deleteFlagged(port, msg.external_ids || [])
        ).catch(err => {
          globalThis.ApplywrightExtension.content.isDeleting = false;
          try { port.postMessage({ status: 'error', message: String((err && err.message) || err) }); } catch (_) {}
        });
      }
      if (msg.action === 'cancel_delete') {
        globalThis.ApplywrightExtension.content.cancelDelete = true;
      }
    });
  }
});
