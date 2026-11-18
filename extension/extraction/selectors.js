globalThis.ApplywrightExtension = globalThis.ApplywrightExtension || {};

globalThis.ApplywrightExtension.selectors = {
  card: [
    'div.shadow-card',
    '.shadow-card',
    '[data-testid="job-card"]',
    '.job-card',
    'article'
  ],
  title: [
    'p.font-bold.text-sm.cursor-pointer.break-words',
    '[data-testid="job-title"]',
    'h2',
    'h3',
    '.job-title',
    '[aria-label*="title"]'
  ],
  company: [
    'p.font-bold.text-sm.cursor-pointer.break-words + *',
    '[data-testid="company-name"]',
    '.company',
    '.company-name',
    '[aria-label*="company"]'
  ],
  location: [
    '[data-testid="job-location"]',
    '.location'
  ],
  remote_status: [
    '[data-testid="remote-status"]',
    '.remote'
  ],
  salary: [
    '[data-testid="salary"]',
    '.salary'
  ],
  employment_type: [
    '[data-testid="employment-type"]',
    '.job-type'
  ],
  job_url: [
    'a[href^="/applications/review/"]',
    'a[href*="/applications/review/"]',
    'a[data-testid="job-link"]',
    'a.job-title-link'
  ],
  description: [
    '[data-testid="job-description"]',
    '.description'
  ],
  status: [
    '[data-testid="application-status"]',
    '.status-badge'
  ],
  external_id_attr: [
    'data-job-id',
    'data-id',
    'data-application-id'
  ]
};
