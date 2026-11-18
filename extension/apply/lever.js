// Lever field map for jobs.lever.co application pages.
// Selectors marked "live" were confirmed against a public Lever apply page.
(function (root) {
  'use strict';
  root.ApplyMaps = root.ApplyMaps || {};
  root.ApplyMaps.lever = {
    system: 'lever',
    waitMs: 5000,
    formSelectors: ['#application-form', 'input[name="resume"]'],
    fields: [
      // live: name="name", "email", "phone", "location", "urls[LinkedIn]", "urls[GitHub]",
      // input[name="resume"][type=file], textarea[name="comments"]
      { key: 'name', kind: 'text', applicant: 'full_name', selectors: ['input[name="name"]'], labels: [/^full name$/i] },
      { key: 'email', kind: 'text', applicant: 'email', selectors: ['input[name="email"]'], labels: [/^email$/i] },
      { key: 'phone', kind: 'text', applicant: 'phone', selectors: ['input[name="phone"]'], labels: [/^phone$/i] },
      { key: 'location', kind: 'text', applicant: 'location', selectors: ['input[name="location"]'], labels: [/^current location$/i] },
      { key: 'linkedin', kind: 'text', applicant: 'linkedin_url', selectors: ['input[name="urls[LinkedIn]"]'], labels: [/^linkedin( url| profile)?$/i] },
      { key: 'github', kind: 'text', applicant: 'github_url', selectors: ['input[name="urls[GitHub]"]'], labels: [/^github( url| profile)?$/i] },
      { key: 'resume', kind: 'file', file: 'resume', selectors: ['input[name="resume"][type="file"]'], labels: [] },
      {
        key: 'cover_letter', kind: 'cover_letter',
        fileSelectors: [], fileLabels: [],
        textSelectors: ['textarea[name="comments"]', 'textarea#additional-information'], textLabels: [/cover letter/i],
      },
    ],
  };
})(typeof globalThis !== 'undefined' ? globalThis : this);
