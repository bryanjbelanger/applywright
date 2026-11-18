// Ashby field map for jobs.ashbyhq.com. Ashby renders the form late, so the
// content script waits for it for up to waitMs.
// The field paths (_systemfield_name, _systemfield_email, _systemfield_resume,
// _systemfield_location) were confirmed through Ashby's public posting API.
// The DOM ids and names are NOT confirmed against a rendered page.
(function (root) {
  'use strict';
  root.ApplyMaps = root.ApplyMaps || {};
  root.ApplyMaps.ashby = {
    system: 'ashby',
    waitMs: 15000,
    formSelectors: ['#_systemfield_name', 'input[name="_systemfield_name"]', '#_systemfield_email', 'input[name="_systemfield_email"]'],
    fields: [
      { key: 'name', kind: 'text', applicant: 'full_name', selectors: ['#_systemfield_name', 'input[name="_systemfield_name"]'], labels: [/^(full )?name$/i] },
      { key: 'email', kind: 'text', applicant: 'email', selectors: ['#_systemfield_email', 'input[name="_systemfield_email"]'], labels: [/^email( address)?$/i] },
      { key: 'phone', kind: 'text', applicant: 'phone', selectors: ['#_systemfield_phone', 'input[name="_systemfield_phone"]'], labels: [/^phone( number)?$/i] },
      { key: 'location', kind: 'text', applicant: 'location', selectors: ['#_systemfield_location', 'input[name="_systemfield_location"]'], labels: [/^(current )?location$/i] },
      { key: 'linkedin', kind: 'text', applicant: 'linkedin_url', selectors: [], labels: [/^linkedin( profile| url)?$/i] },
      { key: 'github', kind: 'text', applicant: 'github_url', selectors: [], labels: [/^github( profile| url)?$/i] },
      { key: 'resume', kind: 'file', file: 'resume', selectors: ['#_systemfield_resume', 'input[type="file"][name="_systemfield_resume"]'], labels: [/^resume$/i] },
      {
        key: 'cover_letter', kind: 'cover_letter',
        fileSelectors: [], fileLabels: [/^cover letter$/i],
        textSelectors: [], textLabels: [/^cover letter$/i],
      },
    ],
  };
})(typeof globalThis !== 'undefined' ? globalThis : this);
