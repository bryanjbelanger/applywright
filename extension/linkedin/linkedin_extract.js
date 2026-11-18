// Read-only extraction of the single job shown on a LinkedIn jobs page.
// It only reads the DOM it is given. It never scrolls, clicks, navigates,
// opens tabs, or fetches anything.
(function (root) {
  const NS = (root.ApplywrightExtension = root.ApplywrightExtension || {});

  // Each list holds fallbacks in priority order. LinkedIn renames classes often.
  const SELECTORS = {
    scope: [
      '.jobs-search__job-details--container',
      '.jobs-search__job-details',
      '.job-view-layout',
      '.jobs-details',
      '.scaffold-layout__detail',
      '[class*="jobs-details"]',
    ],
    title: [
      '.job-details-jobs-unified-top-card__job-title h1',
      '.job-details-jobs-unified-top-card__job-title',
      '.jobs-unified-top-card__job-title',
      '.top-card-layout__title',
      'h1',
    ],
    company: [
      '.job-details-jobs-unified-top-card__company-name a',
      '.job-details-jobs-unified-top-card__company-name',
      '.jobs-unified-top-card__company-name a',
      '.jobs-unified-top-card__company-name',
      '.topcard__org-name-link',
      'a[href*="/company/"]',
    ],
    location: [
      '.job-details-jobs-unified-top-card__primary-description-container .tvm__text',
      '.jobs-unified-top-card__bullet',
      '.topcard__flavor--bullet',
    ],
    workplace: [
      '.job-details-fit-level-preferences button',
      '.job-details-fit-level-preferences span',
      '.jobs-unified-top-card__workplace-type',
    ],
    description: [
      '#job-details',
      '.jobs-description__content',
      '.jobs-box__html-content',
      '.jobs-description-content__text',
      '.show-more-less-html__markup',
      'article',
    ],
    applyButton: [
      '.jobs-apply-button',
      'button[aria-label*="Apply" i]',
      'a[aria-label*="Apply" i]',
      '.jobs-apply-button--top-card button',
    ],
  };

  const WORKPLACE_RE = /^(remote|hybrid|on-?site)\b/i;

  function clean(text) {
    if (!text) return null;
    const t = String(text).replace(/\s+/g, ' ').trim();
    return t === '' ? null : t;
  }

  function first(scope, selectors) {
    for (const sel of selectors) {
      let el = null;
      try {
        el = scope.querySelector(sel);
      } catch (e) {
        el = null;
      }
      if (el && clean(el.textContent)) return el;
    }
    return null;
  }

  // Text with block structure kept, without relying on innerText.
  function blockText(el) {
    const out = [];
    const walk = (node) => {
      if (node.nodeType === 3) {
        out.push(node.textContent.replace(/\s+/g, ' '));
        return;
      }
      if (node.nodeType !== 1) return;
      const tag = node.tagName.toLowerCase();
      if (tag === 'script' || tag === 'style') return;
      if (tag === 'br') {
        out.push('\n');
        return;
      }
      const block = /^(p|div|li|ul|ol|h[1-6]|section|tr)$/.test(tag);
      if (tag === 'li') out.push('\n- ');
      else if (block) out.push('\n');
      node.childNodes.forEach(walk);
      if (block && tag !== 'li') out.push('\n');
    };
    walk(el);
    let text = out.join('').replace(/[ \t]*\n[ \t]*/g, '\n').replace(/\n{3,}/g, '\n\n').trim();
    text = text.replace(/^about the job\s*/i, '').trim();
    return text === '' ? null : text;
  }

  function jobIdFromUrl(href) {
    try {
      const url = new URL(href);
      const m = url.pathname.match(/\/jobs\/view\/(?:[^/]*-)?(\d+)/);
      if (m) return m[1];
      const cur = url.searchParams.get('currentJobId');
      if (cur && /^\d+$/.test(cur)) return cur;
    } catch (e) {
      // fall through
    }
    return null;
  }

  function decodeRedirect(href, base) {
    try {
      const url = new URL(href, base);
      if (!/linkedin\.com$/.test(url.hostname)) {
        return /^https?:$/.test(url.protocol) ? url.href : null;
      }
      if (!url.pathname.startsWith('/redir/redirect')) return null;
      const target = url.searchParams.get('url');
      if (!target) return null;
      const dest = new URL(target);
      if (!/^https?:$/.test(dest.protocol)) return null;
      if (/(^|\.)linkedin\.com$/.test(dest.hostname)) return null;
      return dest.href;
    } catch (e) {
      return null;
    }
  }

  function detectApply(scope, pageUrl) {
    let button = null;
    for (const sel of SELECTORS.applyButton) {
      try {
        button = scope.querySelector(sel);
      } catch (e) {
        button = null;
      }
      if (button) break;
    }
    const label = button
      ? `${button.getAttribute('aria-label') || ''} ${button.textContent || ''}`
      : '';
    if (/easy\s*apply/i.test(label)) return { apply_type: 'easy_apply', apply_url: null };

    const links = Array.from(scope.querySelectorAll('a[href]'));
    const candidates = [];
    if (button && button.tagName === 'A') candidates.push(button);
    candidates.push(...links.filter((a) => /\/redir\/redirect/.test(a.getAttribute('href'))));
    if (button && button.closest) {
      const holder = button.closest('.jobs-apply-button--top-card') || button.parentElement;
      if (holder) candidates.push(...Array.from(holder.querySelectorAll('a[href]')));
    }
    for (const a of candidates) {
      const url = decodeRedirect(a.getAttribute('href'), pageUrl);
      if (url) return { apply_type: 'external', apply_url: url };
    }
    return { apply_type: 'external', apply_url: null };
  }

  function findWorkplace(scope, location) {
    for (const sel of SELECTORS.workplace) {
      let els = [];
      try {
        els = Array.from(scope.querySelectorAll(sel));
      } catch (e) {
        els = [];
      }
      for (const el of els) {
        const t = clean(el.textContent);
        const m = t && t.match(WORKPLACE_RE);
        if (m) return m[1][0].toUpperCase() + m[1].slice(1).toLowerCase().replace('onsite', 'on-site');
      }
    }
    const m = location && location.match(/\((remote|hybrid|on-?site)\)/i);
    if (m) return m[1][0].toUpperCase() + m[1].slice(1).toLowerCase();
    return null;
  }

  function cleanLocation(text) {
    const t = clean(text);
    if (!t) return null;
    // Top card text often reads "City, ST · 2 days ago · 40 applicants".
    return clean(t.split(/[·•|]/)[0]);
  }

  // doc: a Document. pageUrl: the tab URL. Returns {ok, job} or {ok:false, error}.
  function extractJob(doc, pageUrl) {
    const job_id = jobIdFromUrl(pageUrl);
    if (!job_id) return { ok: false, error: 'No LinkedIn job id in the page URL.' };

    let scope = null;
    for (const sel of SELECTORS.scope) {
      try {
        scope = doc.querySelector(sel);
      } catch (e) {
        scope = null;
      }
      if (scope) break;
    }
    scope = scope || doc.body;

    const titleEl = first(scope, SELECTORS.title);
    const companyEl = first(scope, SELECTORS.company);
    if (!titleEl) return { ok: false, error: 'Job title not found on the page.' };
    if (!companyEl) return { ok: false, error: 'Company not found on the page.' };

    const locEl = first(scope, SELECTORS.location);
    const location = locEl ? cleanLocation(locEl.textContent) : null;
    const descEl = first(scope, SELECTORS.description);
    const apply = detectApply(scope, pageUrl);

    return {
      ok: true,
      job: {
        external_id: job_id,
        title: clean(titleEl.textContent),
        company: clean(companyEl.textContent),
        location,
        remote_status: findWorkplace(scope, location),
        description: descEl ? blockText(descEl) : null,
        job_url: `https://www.linkedin.com/jobs/view/${job_id}/`,
        apply_type: apply.apply_type,
        apply_url: apply.apply_url,
        source: 'linkedin',
      },
    };
  }

  NS.linkedin = { extractJob, jobIdFromUrl, decodeRedirect };
  if (typeof module !== 'undefined' && module.exports) module.exports = NS.linkedin;
})(typeof globalThis !== 'undefined' ? globalThis : this);
