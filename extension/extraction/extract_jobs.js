globalThis.ApplywrightExtension = globalThis.ApplywrightExtension || {};

globalThis.ApplywrightExtension.extract = {
  _getMatchingElement(container, candidates) {
    for (const sel of candidates) {
      const el = container.querySelector(sel);
      if (el) return { element: el, selector: sel };
    }
    return null;
  },

  _extractExternalId(card, url) {
    const { selectors } = globalThis.ApplywrightExtension;
    for (const attr of selectors.external_id_attr) {
      if (card.hasAttribute(attr)) return card.getAttribute(attr);
    }

    let urlToParse = url;
    if (!urlToParse) {
      const reviewLink = card.querySelector('a[href^="/applications/review/"], a[href^="/applications/connect/"]');
      if (reviewLink) {
        urlToParse = reviewLink.href || reviewLink.getAttribute('href');
      }
    }
    
    if (urlToParse) {
      try {
        const urlObj = new URL(urlToParse, 'http://dummy.com');
        const match = urlObj.pathname.match(/\/(?:applications\/review|applications\/connect|jobs?)\/([^/]+)/);
        if (match) return match[1];
        
        const idParam = urlObj.searchParams.get('id');
        if (idParam) return idParam;
      } catch (e) {}
    }
    return null;
  },

  parseJobCopilotReviewUrl(urlStr) {
    try {
      if (urlStr.includes('..') || urlStr.toLowerCase().includes('%2e')) return null;
      const urlObj = new URL(urlStr);
      if (urlObj.protocol !== 'https:' || urlObj.hostname !== 'app.jobcopilot.com') return null;
      if (urlObj.port || urlObj.username || urlObj.password) return null;
      
      const match = urlObj.pathname.match(/^\/applications\/review\/([A-Za-z0-9_-]+)\/?$/);
      if (!match) return null;
      
      return match[1];
    } catch (e) {
      return null;
    }
  },

  findTrustedPageIds(documentObj) {
    const trustedAttrs = ['data-job-id', 'data-application-id'];
    const foundIds = new Set();
    
    for (const attr of trustedAttrs) {
      if (documentObj.body.hasAttribute(attr)) {
        const val = documentObj.body.getAttribute(attr);
        if (val && val.trim()) foundIds.add(val.trim());
      }
      const els = documentObj.querySelectorAll(`[${attr}]`);
      els.forEach(el => {
        const val = el.getAttribute(attr);
        if (val && val.trim()) foundIds.add(val.trim());
      });
    }
    return Array.from(foundIds);
  },

  validateEnrichmentPageIdentity(documentObj, urlExternalId) {
    const trustedIds = this.findTrustedPageIds(documentObj);
    
    if (trustedIds.length === 0) {
      return true; // no trusted ID: use validated URL ID
    }
    if (trustedIds.length === 1 && trustedIds[0] === urlExternalId) {
      return true; // one distinct trusted ID matching the URL ID: valid
    }
    return false; // conflicts or multiple distinct IDs fail
  },
  
  extractReviewLabeledValue(documentObj, allowedTags, labelPrefixes, valueSelector) {
    const { normalize } = globalThis.ApplywrightExtension;
    const tagSelector = allowedTags.join(', ');
    const candidates = Array.from(documentObj.querySelectorAll(tagSelector)).filter(el => {
      const txt = normalize.cleanText(el.innerText || el.textContent) || '';
      return labelPrefixes.some(prefix => txt.startsWith(prefix));
    });
    
    if (candidates.length === 0) return null;
    
    // Pick the most specific candidate (shortest text length)
    candidates.sort((a, b) => {
      const txtA = (a.innerText || a.textContent || '');
      const txtB = (b.innerText || b.textContent || '');
      return txtA.length - txtB.length;
    });
    
    const row = candidates[0];
    
    const valueNodes = Array.from(row.querySelectorAll(valueSelector));
    if (valueNodes.length === 0) return null;
    
    // Deepest element (fewest descendants)
    valueNodes.sort((a, b) => a.querySelectorAll('*').length - b.querySelectorAll('*').length);
    
    const valueEl = valueNodes[0];
    const valText = normalize.cleanText(valueEl.innerText || valueEl.textContent);
    return valText || null;
  },

  _mapStatus(text) {
    if (!text) return 'saved';
    const normalized = text.toLowerCase().trim();
    const valid = ['discovered', 'saved', 'applied', 'screening', 'interview', 'rejected', 'withdrawn', 'offer', 'unknown'];
    if (valid.includes(normalized)) return normalized;
    return 'saved';
  },

  scanDOM(documentObj, baseUrl, targetStatus = "saved") {
    const { normalize, selectors } = globalThis.ApplywrightExtension;
    const cards = [];
    
    for (const sel of selectors.card) {
      const found = documentObj.querySelectorAll(sel);
      if (found.length > 0) {
        found.forEach(el => cards.push({ element: el, selector: sel }));
        break;
      }
    }

    const report = {
      card_count: cards.length,
      records: []
    };

    cards.forEach((c, index) => {
      const { element, selector: cardSelector } = c;
      const rec = {
        card_index: index,
        valid: false,
        fields_found: [],
        fields_missing: [],
        selectors_used: { card: cardSelector },
        warnings: [],
        job_data: null
      };

      const extractField = (key, selectorList, isLink = false) => {
        const found = this._getMatchingElement(element, selectorList);
        if (found) {
          rec.selectors_used[key] = found.selector;
          rec.fields_found.push(key);
          if (isLink) {
             return normalize.canonicalizeUrl(found.element.href || found.element.getAttribute('href'), baseUrl);
          }
          return normalize.cleanText(found.element.innerText || found.element.textContent);
        } else {
          rec.fields_missing.push(key);
          return null;
        }
      };

      const title = extractField('title', selectors.title);
      const company = extractField('company', selectors.company);
      const url = extractField('job_url', selectors.job_url, true);

      if (!title || !company || ['apply', 'review application'].includes(title.toLowerCase()) || ['apply', 'review application'].includes(company.toLowerCase())) {
        rec.warnings.push("Missing required title or company, or parsed button text.");
      } else {
        rec.valid = true;
      }

      if (rec.valid) {
        rec.job_data = {
          external_id: this._extractExternalId(element, url),
          title: title,
          company: company,
          location: extractField('location', selectors.location),
          remote_status: extractField('remote_status', selectors.remote_status),
          salary: extractField('salary', selectors.salary),
          employment_type: extractField('employment_type', selectors.employment_type),
          job_url: url,
          description: extractField('description', selectors.description),
          date_found: null,
          date_applied: null,
          application_status: targetStatus,
          source: 'jobcopilot'
        };
      }
      
      report.records.push(rec);
    });

    return report;
  },

  processRecords(report, currentUrl) {
    const { normalize } = globalThis.ApplywrightExtension;
    
    let exported = [];
    let duplicates = 0;
    let warnings = 0;
    
    const seen = new Map();
    
    for (const rec of report.records) {
      if (!rec.valid) {
         warnings += rec.warnings.length > 0 ? 1 : 0;
         continue;
      }
      
      const jd = rec.job_data;
      
      let identity = null;
      if (jd.external_id) {
         identity = `id:${jd.source}:${jd.external_id}`;
      } else if (jd.job_url) {
         identity = `url:${jd.job_url}`;
      } else {
         identity = `title:${normalize.cleanText(jd.company)?.toLowerCase()}:${normalize.cleanText(jd.title)?.toLowerCase()}`;
      }
      
      if (seen.has(identity)) {
         const existing = seen.get(identity);
         const existingData = existing.data;
         
         const isIdentical = JSON.stringify(existingData) === JSON.stringify(jd);
         if (isIdentical) {
            duplicates++;
            rec.warnings.push("Identical duplicate ignored");
         } else {
            duplicates++;
            const existingFields = Object.values(existingData).filter(v => v !== null).length;
            const newFields = Object.values(jd).filter(v => v !== null).length;
            
            const conflicts = [];
            for (const key of Object.keys(jd)) {
                if (existingData[key] !== jd[key]) conflicts.push(key);
            }
            rec.warnings.push(`Conflicting duplicate on fields: ${conflicts.join(', ')}`);
            warnings++;
            
            if (newFields > existingFields) {
               exported[existing.index] = jd;
               seen.set(identity, { data: jd, index: existing.index });
            }
         }
      } else {
         seen.set(identity, { data: jd, index: exported.length });
         exported.push(jd);
      }
    }
    
    return {
      metadata: {
        source: 'jobcopilot',
        exported_at: new Date().toISOString(),
        page_url: currentUrl,
        detected_count: report.card_count,
        exported_count: exported.length,
        invalid_count: report.records.filter(r => !r.valid).length,
        duplicate_count: duplicates,
        warning_count: warnings,
        extension_version: "0.1.0"
      },
      jobs: exported,
      diagnostics: {
        page_url: currentUrl,
        scanned_at: new Date().toISOString(),
        card_count: report.card_count,
        records: report.records.map(r => {
           const out = { ...r };
           delete out.job_data;
           return out;
        })
      }
    };
  },

  extractCurrentPage(documentObj, currentUrl) {
    const { normalize, selectors } = globalThis.ApplywrightExtension;
    
    // 1. Validate URL completely
    const external_id = this.parseJobCopilotReviewUrl(currentUrl);
    if (!external_id) {
       return { error: "Invalid JobCopilot review URL or external ID." };
    }
    
    // 2. Identity fields must be extracted from the main page area
    if (!this.validateEnrichmentPageIdentity(documentObj, external_id)) {
       return { error: "Page identity mismatch: multiple conflicting trusted IDs found or ID does not match URL" };
    }
    
    // 3. Detect login and incomplete pages
    if (documentObj.querySelector('form[action*="login"], input[type="password"]')) {
       return { error: "Login page detected" };
    }
    if (documentObj.querySelector('[aria-busy="true"], .skeleton-loader, .loading-spinner')) {
       return { error: "Page is still loading" };
    }
    
    const extractField = (selectorList) => {
      const found = this._getMatchingElement(documentObj, selectorList);
      if (found) return normalize.cleanText(found.element.innerText || found.element.textContent);
      return null;
    };
    
    let title = this.extractReviewLabeledValue(documentObj, ['p'], ['Job Title:'], 'span.text-black.font-semibold');
    if (!title) {
       title = extractField(selectors.title);
    }
    
    let company = this.extractReviewLabeledValue(documentObj, ['div', 'span'], ['Company:', 'Company :'], 'span.text-black');
    if (!company) {
       company = extractField(selectors.company);
    }
    
    if (!title || !company) {
       return { error: "Missing required title or company on page" };
    }

    // 4. Attempt to extract the description
    let descriptionText = null;
    let descriptionWarnings = [];
    
    // Find candidate container
    const descSelectors = [
       '[data-testid="job-description"]',
       '.job-description',
       '[aria-label*="Job Description" i]',
       '[aria-label*="About the Role" i]'
    ];
    let container = null;
    let usedSelector = null;
    for (const sel of descSelectors) {
       container = documentObj.querySelector(sel);
       if (container) {
          usedSelector = sel;
          break;
       }
    }
    
    // Fallback to heading-anchored extraction
    if (!container) {
       const headingNames = ["Job Description", "About the Job", "About the Role", "The Role", "Responsibilities", "What You’ll Do", "Qualifications", "Requirements"];
       const walker = documentObj.createTreeWalker(documentObj.body, 1 /* NodeFilter.SHOW_ELEMENT */, null, false);
       while (walker.nextNode()) {
          const el = walker.currentNode;
          if (/^H[1-6]$/.test(el.tagName) && el.textContent) {
             const txt = el.textContent.trim();
             if (headingNames.some(h => txt.toLowerCase().includes(h.toLowerCase()))) {
                let parent = el.parentElement;
                
                // If it explicitly belongs to a description block, take the whole block.
                const pClass = typeof parent.className === 'string' ? parent.className.toLowerCase() : '';
                const hasDescClass = pClass.includes('job-description') || pClass.includes('description-section');
                const hasAria = (parent.getAttribute('aria-label') || '').toLowerCase();
                const hasDescAria = headingNames.some(h => hasAria.includes(h.toLowerCase()));
                const hasTestId = parent.getAttribute('data-testid') === 'job-description';
                
                if (hasTestId || hasDescClass || hasDescAria || (parent.getAttribute('role') === 'region' && hasDescAria)) {
                   container = parent;
                   usedSelector = `heading-anchored-parent(${el.tagName})`;
                   break;
                }
                
                // Build a temporary bounded region
                const level = parseInt(el.tagName.substring(1));
                container = documentObj.createElement('div');
                container.appendChild(el.cloneNode(true));
                let curr = el.nextElementSibling;
                while (curr) {
                   // Stop at navigation/metadata explicit boundaries
                   if (curr.tagName === 'NAV' || curr.tagName === 'ASIDE' || curr.tagName === 'FORM' || curr.className.includes('apply')) {
                      break;
                   }
                   // Stop at next heading of same or higher level
                   if (/^H[1-6]$/.test(curr.tagName)) {
                      const currLevel = parseInt(curr.tagName.substring(1));
                      if (currLevel <= level) break;
                   }
                   container.appendChild(curr.cloneNode(true));
                   curr = curr.nextElementSibling;
                }
                
                usedSelector = `heading-anchored-bounded(${el.tagName})`;
                break;
             }
          }
       }
    }
    
    if (!container) {
       return { error: "Could not locate a reliable description container" };
    }
    
    // Clone node to strip unwanted elements
    const clone = container.cloneNode(true);
    const unwanted = [
       'script', 'style', 'svg', 'nav', 'aside', 'form', 'button', 'input', 'select', 'textarea',
       '[role="button"]', '.cookie-banner', '.consent-banner', '.application-action', '.modal',
       '[hidden]', '[aria-hidden="true"]'
    ];
    for (const sel of unwanted) {
       clone.querySelectorAll(sel).forEach(el => el.remove());
    }
    clone.querySelectorAll('*').forEach(el => {
       const style = el.getAttribute('style') || '';
       if (style.includes('display:none') || style.includes('display: none') || style.includes('visibility:hidden') || style.includes('visibility: hidden')) {
          el.remove();
       }
    });
    
    // Strip elements whose text is exact controls (like "Review Application", "Apply", "Submit", "Save")
    // Traverse and remove nodes matching exactly these terms.
    const controls = ["Review Application", "Apply", "Apply Now", "Submit", "Submit Application", "Save", "Continue", "Continue Application"];
    const walker2 = documentObj.createTreeWalker(clone, 1 /* NodeFilter.SHOW_ELEMENT */, null, false);
    const toRemove = [];
    while (walker2.nextNode()) {
       const el = walker2.currentNode;
       if (el.children.length === 0 && el.textContent) {
          const txt = el.textContent.trim();
          if (controls.includes(txt) || controls.some(c => txt.toLowerCase() === c.toLowerCase())) {
             toRemove.push(el);
          }
       }
    }
    toRemove.forEach(el => el.remove());
    
    // Serialize
    // Convert block elements to have linebreaks, lists to have bullets
    const blockTags = new Set(['DIV', 'P', 'H1', 'H2', 'H3', 'H4', 'H5', 'H6', 'SECTION', 'ARTICLE', 'PRE']);
    let rawText = '';
    
    // Need state for numbered lists
    const state = { listIndex: 1 };
    
    function serializeNode(node, currentListType = null) {
       if (node.nodeType === 3 /* Node.TEXT_NODE */) {
          if (node.nodeValue.trim() !== '') {
             rawText += node.nodeValue;
          }
       } else if (node.nodeType === 1 /* Node.ELEMENT_NODE */) {
          let listType = currentListType;
          if (node.tagName === 'OL') listType = 'OL';
          else if (node.tagName === 'UL') listType = 'UL';
          
          if (node.tagName === 'OL') {
             state.listIndex = 1;
          }
          
          if (node.tagName === 'LI') {
             if (listType === 'OL') {
                rawText += `\n${state.listIndex}. `;
                state.listIndex++;
             } else {
                rawText += '\n- ';
             }
          } else if (blockTags.has(node.tagName) || node.tagName === 'UL' || node.tagName === 'OL') {
             rawText += '\n';
          }
          
          for (let child of node.childNodes) {
             serializeNode(child, listType);
          }
          
          if (blockTags.has(node.tagName) || node.tagName === 'UL' || node.tagName === 'OL') {
             rawText += '\n';
          }
       }
    }
    
    serializeNode(clone);
    descriptionText = normalize.cleanMultilineText(rawText);
    
    if (!descriptionText) {
       return { error: "Extracted description was empty after formatting" };
    }
    
    // Structured metadata on the review page uses the same labeled-row pattern as
    // Company: e.g. "Location : Remote" / "Job Type : Fulltime" with the value in a
    // <span class="text-black">. Read them via the labeled-value helper (which already
    // powers title/company); fall back to the generic selectors for resilience.
    const labeledLocation = this.extractReviewLabeledValue(
       documentObj, ['div', 'span', 'p'], ['Location:', 'Location :'], 'span.text-black'
    ) || extractField(selectors.location) || null;

    const labeledEmploymentType = this.extractReviewLabeledValue(
       documentObj, ['div', 'span', 'p'],
       ['Job Type:', 'Job Type :', 'Employment Type:', 'Employment Type :'], 'span.text-black'
    ) || extractField(selectors.employment_type) || null;

    const labeledSalary = this.extractReviewLabeledValue(
       documentObj, ['div', 'span', 'p'],
       ['Salary:', 'Salary :', 'Compensation:', 'Compensation :', 'Pay:', 'Pay :'], 'span.text-black'
    ) || extractField(selectors.salary) || null;

    // JobCopilot encodes remote/hybrid/onsite as the Location value rather than a
    // separate field, so derive remote_status from it when not explicitly present.
    let labeledRemoteStatus = extractField(selectors.remote_status) || null;
    if (!labeledRemoteStatus && labeledLocation) {
       if (/\bremote\b/i.test(labeledLocation)) labeledRemoteStatus = 'Remote';
       else if (/\bhybrid\b/i.test(labeledLocation)) labeledRemoteStatus = 'Hybrid';
       else if (/\bon-?site\b|\bin-office\b/i.test(labeledLocation)) labeledRemoteStatus = 'Onsite';
    }

    const jd = {
       external_id: external_id,
       title: title,
       company: company,
       location: labeledLocation,
       remote_status: labeledRemoteStatus,
       salary: labeledSalary,
       employment_type: labeledEmploymentType,
       job_url: `https://app.jobcopilot.com/applications/review/${external_id}`,
       description: descriptionText,
       date_found: null,
       date_applied: null,
       application_status: "saved",
       source: "jobcopilot"
    };

    return {
       metadata: {
         source: 'jobcopilot',
         export_kind: 'current_job_enrichment',
         exported_at: new Date().toISOString(),
         page_url: currentUrl,
         detected_count: 1,
         exported_count: 1,
         invalid_count: 0,
         duplicate_count: 0,
         warning_count: descriptionWarnings.length,
         warnings: descriptionWarnings
       },
       jobs: [jd],
       diagnostics: {
         strategy: "structural",
         selector: usedSelector,
         char_count: descriptionText.length,
         line_count: descriptionText.split('\n').length
       }
    };
  }
};
