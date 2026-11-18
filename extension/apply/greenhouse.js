// Greenhouse field map. Applies to boards.greenhouse.io and
// job-boards.greenhouse.io, including the iframe that employer sites embed.
// Selectors marked "live" were confirmed against a public job-boards page.
// The rest are in the README as unconfirmed.
(function (root) {
  'use strict';
  root.ApplyMaps = root.ApplyMaps || {};
  root.ApplyMaps.greenhouse = {
    system: 'greenhouse',
    waitMs: 5000,
    formSelectors: ['#application-form', 'form#application_form', '#first_name'],
    fields: [
      // live: #first_name, #last_name, #email, #phone, #candidate-location, #resume, #cover_letter
      { key: 'first_name', kind: 'text', applicant: 'first_name', selectors: ['#first_name', 'input[name="job_application[first_name]"]'], labels: [/^first name$/i] },
      { key: 'last_name', kind: 'text', applicant: 'last_name', selectors: ['#last_name', 'input[name="job_application[last_name]"]'], labels: [/^last name$/i] },
      { key: 'email', kind: 'text', applicant: 'email', selectors: ['#email', 'input[name="job_application[email]"]'], labels: [/^email( address)?$/i] },
      { key: 'phone', kind: 'text', applicant: 'phone', selectors: ['#phone', 'input[name="job_application[phone]"]'], labels: [/^phone( number)?$/i] },
      { key: 'location', kind: 'text', applicant: 'location', selectors: ['#candidate-location', 'input[name="job_application[location]"]'], labels: [/^location( \(city\))?$/i] },
      { key: 'linkedin', kind: 'text', applicant: 'linkedin_url', selectors: [], labels: [/^linkedin( profile| url)?$/i] },
      { key: 'github', kind: 'text', applicant: 'github_url', selectors: [], labels: [/^github( profile| url)?$/i] },
      { key: 'resume', kind: 'file', file: 'resume', selectors: ['input#resume[type="file"]', 'input[type="file"][name*="resume"]'], labels: [] },
      {
        key: 'cover_letter', kind: 'cover_letter',
        fileSelectors: ['input#cover_letter[type="file"]', 'input[type="file"][name*="cover_letter"]'], fileLabels: [],
        textSelectors: ['textarea#cover_letter_text', 'textarea[name*="cover_letter"]'], textLabels: [/^cover letter$/i],
      },
    ],
  };
})(typeof globalThis !== 'undefined' ? globalThis : this);
