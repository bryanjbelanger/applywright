# Applywright extension

A Chrome MV3 extension. It fills application forms from a local apply bundle and never submits. See the [root README](../README.md) for install and use.

## Install (unpacked)

1. Open `chrome://extensions/` and turn on **Developer mode**.
2. Click **Load unpacked** and select this `extension` directory.

## Apply form filler

Fills name, email, phone, location, LinkedIn, GitHub, the resume file, and the cover letter on Greenhouse, Lever, and Ashby pages. It never touches fields about work authorization, sponsorship, citizenship, gender, race, ethnicity, veteran status, disability, pronouns, or certification and attestation. They appear under "Left for you". The code never clicks, never calls `submit()` or `requestSubmit()`, and never dispatches `submit`. Tests enforce this.

Greenhouse is registered with `all_frames` because employer sites embed it in an iframe. Ashby renders late, so the filler waits up to 15 seconds for the form.

## LinkedIn capture

See the "LinkedIn capture" section of the root README. The selectors are unverified on the live site.

## JobCopilot import (optional)

Open `https://app.jobcopilot.com/` and sign in. The extension uses your existing session.

1. Click **Scan Current Page**, or **Scan Loaded Jobs (Auto-scroll)**.
2. Click **Export JSON** to download `jobcopilot-export-*.json`.
3. Move the file into `data/imports/` and call the MCP `import_jobs` tool.
4. **Copy Diagnostics** shows what the extension saw, for debugging selectors.

Batch enrichment loads a queue file, opens each job page in a background tab, and writes a result file. Delete Flagged removes the exact IDs in your list on JobCopilot, with one confirmation from you.

JobCopilot's live DOM can change. If extraction misses fields, update the selector arrays in `extraction/selectors.js` and reload the extension.

## Tests

```bash
npm ci
node --test tests/*.test.js
```
