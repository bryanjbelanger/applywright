# Privacy Policy

Last updated: 2026-11-18

Applywright is a local, single-user toolkit. It has no server, no account, and no analytics.

## What the browser extension does with data

- The extension reads the page you have open only when you click one of its buttons, or on a supported application form page to fill fields after you click **Fill this form**.
- It reads the apply bundle file you choose, which holds your name, contact details, and documents. It keeps that bundle in `chrome.storage.local` in your browser so you can fill more than one form.
- It saves files to your computer through the browser download function: exported job JSON, LinkedIn captures, and submission records.
- **The extension does not send any data to any server.** It makes no network requests of its own. It has no remote code and no tracking.
- The only pages it opens are the JobCopilot pages that you ask it to open during an optional batch enrichment run.

## Permissions and why

- `storage`: keep your scan results, batch state, and apply bundle in your browser.
- `downloads`: save export and record files to your computer.
- Host access to `app.jobcopilot.com`, `boards.greenhouse.io`, `job-boards.greenhouse.io`, `jobs.lever.co`, `jobs.ashbyhq.com`, and `www.linkedin.com/jobs/`: read job data and fill forms on those sites.

## What the Python package does with data

The Python package and MCP server run on your computer. They store jobs in a local SQLite file and write your documents to local folders. They make no network requests, with one optional exception: the triage command can send job text to a local LLM server at a URL you set (default `http://localhost:1234`) when you pass `--extract`. When you use them with Claude Code, the text you ask Claude to read is sent to Claude under your own agreement with Anthropic. That is outside Applywright.

## What the extension never does

It never submits an application. It never answers questions about work authorization, sponsorship, visa status, citizenship, EEO, veteran status, disability, or attestations.

## Delete your data

Remove the extension to delete its browser storage. Delete your `data/`, `application_materials/jobs/`, `application_materials/work/`, and `application_materials/apply_bundles/` folders to delete the local files.

## Contact

Open an issue in the project repository.
