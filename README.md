# Applywright

A local toolkit for tailored, evidence-backed job applications. It never submits for you.

Applywright has two parts:

- **A Python package** with a SQLite job store, triage, application package drafting, rendering, and promotion, an apply bundle builder, and an MCP server for Claude Code.
- **A Chrome extension** (Manifest V3) with form fillers for Greenhouse, Lever, and Ashby, a submission record, a LinkedIn single-job capture, and an optional JobCopilot import.

Everything runs on your computer. See [PRIVACY.md](PRIVACY.md).

## What it does

1. Stores jobs you import in a local SQLite file.
2. Helps you triage them with advisory rules.
3. Drafts a tailored resume and cover letter for one job you choose. Every claim in the draft must cite an ID from your own evidence catalog (`candidate.yaml`). A claim with no evidence is rejected.
4. Renders PDFs and page images. You review every page, then promote the package.
5. Builds an apply bundle (your details plus the two PDFs) for one promoted package.
6. The extension fills the standard fields of a Greenhouse, Lever, or Ashby form from that bundle.

## What it never does

- It never submits an application. It never clicks Submit.
- It never answers legal questions: work authorization, sponsorship, visa, citizenship, EEO, gender, race, ethnicity, veteran status, disability, pronouns, attestations, or consent boxes. The filler leaves them for you.
- It never invents experience or facts.
- It never marks a job as applied unless you authorize it.
- It sends no data anywhere.

## Requirements

- Python 3.13 and [Poetry](https://python-poetry.org/).
- Node.js (LTS) and npm, for the extension tests only.
- Chrome, to load the extension.
- System libraries for the PDF renderer (WeasyPrint). The renderer needs Pango (with its Cairo, GObject, and HarfBuzz dependencies) and a font. `pypdfium2`, which makes the page images, ships its own binaries.
  - macOS with MacPorts: `sudo port install pango`
  - Debian or Ubuntu: `sudo apt-get install libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz-subset0 fonts-dejavu-core`
  - The stylesheet asks for Arial. If your system has no Arial, WeasyPrint uses a fallback sans-serif font.

## Install

```bash
git clone <repository-url> applywright
cd applywright
poetry env use python3.13
poetry install --with document-rendering,dev
```

## Configure

```bash
cp application_materials/candidate.example.yaml application_materials/candidate.yaml
```

Edit `candidate.yaml`. Replace every fake value with your own. The `evidence_catalog` holds your facts, one ID per claim. The file must validate against `application_materials/schemas/candidate.schema.json`. This file is Git-ignored.

Optional screening files. If you do not create them, Applywright uses the `.example.yaml` files:

```bash
cp config/candidate_profile.example.yaml config/candidate_profile.yaml
cp config/job_scoring_policy.example.yaml config/job_scoring_policy.yaml
```

Environment variables (all optional):

| Variable | Default | Meaning |
| --- | --- | --- |
| `APPLYWRIGHT_DB_PATH` | `data/jobs.db` | SQLite job store |
| `APPLYWRIGHT_IMPORT_DIR` | `data/imports` | The only folder `import_jobs` reads |
| `APPLYWRIGHT_CONFIG_DIR` | `config` | Folder for the screening files |
| `APPLYWRIGHT_ROOT` | repository root | Folder that holds `application_materials/` |

The triage rules in `src/applywright/screening/triage.py` (specialty terms, eligibility gates, evidenced signals) are tuned to an infrastructure and DevOps profile. Edit them to fit your own profile.

## Use the MCP server with Claude Code

Add the server. Use absolute paths.

```bash
claude mcp add applywright \
  --env APPLYWRIGHT_ROOT=/path/to/applywright \
  -- /path/to/applywright/.venv/bin/applywright
```

Or put this in a `.mcp.json` file (Git-ignored, because it holds paths):

```json
{
  "mcpServers": {
    "applywright": {
      "command": "/path/to/applywright/.venv/bin/applywright",
      "env": { "APPLYWRIGHT_ROOT": "/path/to/applywright" }
    }
  }
}
```

Tools: `list_jobs`, `get_job`, `mark_job`, `delete_jobs`, `import_jobs`, `prepare_job_evaluation`, `validate_job_evaluation`, `prepare_application_package`, `validate_application_package`, `materialize_application_draft`.

`mark_job` changes a job's decision and status. Agents must not call it without your explicit authorization. See [AGENTS.md](AGENTS.md).

To get jobs in, put a JSON file in `data/imports/` and call `import_jobs`. The file is a list of jobs or an object with a `jobs` array. A sample job has `title`, `company`, `location`, `remote_status`, `salary`, `employment_type`, `job_url`, `description`, and `source`. The extension can also produce import files (see below).

## Build an application package

1. In Claude Code, call `prepare_application_package` with a `job_id`. It returns the job, your evidence catalog, the job slug, and the payload schema. It writes nothing.
2. Have the model write a payload. Call `validate_application_package`. It checks structure, evidence coverage, and placeholders. It writes nothing.
3. After you approve it, call `materialize_application_draft` with `human_approved=true`. It writes a draft to `application_materials/work/<slug>/`.
4. Render the draft:
   ```bash
   poetry run python -m application_materials.tools.render_application_draft --slug <slug>
   ```
5. Open every page image the command prints. Record a truthful visual review in the draft's `output/validation.json`.
6. Promote it:
   ```bash
   poetry run python -m application_materials.tools.promote_application_draft --slug <slug> --human-approved
   ```
   The package moves to `application_materials/jobs/<slug>/`.

More detail is in [application_materials/README.md](application_materials/README.md).

## Build an apply bundle

```bash
poetry run python application_materials/tools/build_apply_bundle.py <slug>
```

This writes `application_materials/apply_bundles/<slug>.json`. It refuses without a promoted package, both PDFs, and a passing visual review. The bundle holds your contact details, the cover letter text, and both PDFs. It is Git-ignored. Treat it as private.

## Load the unpacked extension

1. Open `chrome://extensions/` and turn on **Developer mode**.
2. Click **Load unpacked** and select the `extension/` folder.
3. Pin the Applywright icon.

## Use the fillers

1. Open the popup, choose your bundle file, and click **Load apply bundle**.
2. Open a Greenhouse, Lever, or Ashby application page.
3. Click **Fill this form**. The popup lists what was filled, what was attached, what was left for you, and which required fields are still empty.
4. You answer the legal questions. You click Submit.
5. On the confirmation page, click **Save submission record**. It downloads `submission-<slug>.json`. It does not touch the database.

For other employer sites (Workday, iCIMS, Taleo, custom forms), the `fill-application-form` skill in `.claude/skills/` guides Claude in Chrome. It stops before Submit.

### Selector status

Checked on 2026-11-17 by reading public pages and public APIs only. Nothing was submitted.

Confirmed against a live page:

- Greenhouse (`job-boards.greenhouse.io`): `#first_name`, `#last_name`, `#email`, `#phone`, `#candidate-location` (a combobox, so you pick from the list), `#resume` and `#cover_letter` (hidden file inputs), question inputs with `aria-label` text such as "LinkedIn Profile", and the protected questions (authorization, gender, race, veteran, disability).
- Lever (`jobs.lever.co/<company>/<id>/apply`): `input[name="name"]`, `email`, `phone`, `location`, `urls[LinkedIn]`, `urls[GitHub]`, `input[name="resume"][type="file"]`, `textarea[name="comments"]`, and the work authorization and sponsorship radios.
- Ashby field list and paths (`_systemfield_name`, `_systemfield_email`, `_systemfield_resume`, `_systemfield_location`, custom LinkedIn question) from Ashby's public posting API.

Not confirmed on live pages:

- Ashby DOM ids and names. Ashby builds the form with JavaScript, so a plain fetch has no markup. `extension/fixtures/ashby_form.html` is rebuilt from the API field list. Label matching is the fallback.
- Old Greenhouse `boards.greenhouse.io` markup (`job_application[...]` names).
- The Greenhouse "Enter manually" cover letter text box. It appears only after a click, and the filler does not click. Use the file input.
- Phone and GitHub fields on Greenhouse and Ashby. The sampled postings had none. They are matched by label.
- Behavior of real pages on React `input` and `change` events and on `DataTransfer` file attach. Tests use jsdom with a `DataTransfer` stand-in. Test it once on a real page.
- Confirmation page text and URLs. The Greenhouse `/confirmation` and Lever `/thanks` patterns and the "thank you for applying" text are assumptions.
- **LinkedIn capture selectors** (see below). They are unverified on the live site.

## LinkedIn capture

On a `https://www.linkedin.com/jobs/*` tab, click **Capture this LinkedIn job**. The extension reads the one job you have open (job page or search split pane) and downloads `linkedin-capture-<id>.json`. Import it with `import_jobs`. The job is stored with status `saved`. A re-import never changes the status, decision, notes, or applied date of a job you have worked on. The import warns when another source already holds a job with the same company and title. The apply URL, when LinkedIn shows one, is stored in the `apply_url` field.

The content script does nothing until you click the button. It never scrolls, clicks, navigates, opens tabs, or fetches. The capture reads only the one job you have open when you click the button.

Automated extraction may conflict with LinkedIn's User Agreement. You decide whether to use this feature.

The selectors in `extension/linkedin/linkedin_extract.js` are unverified on the live LinkedIn site. No logged-in session was available. They come from known LinkedIn class names and were tested only against synthetic fixtures. If capture fails, update the selector lists at the top of that file.

## JobCopilot import (optional)

If you use JobCopilot, the extension can read your JobCopilot lists and export a JSON file that `import_jobs` accepts. It can also enrich single jobs, run a batch enrichment, and delete flagged jobs on JobCopilot. This part is optional. Nothing else needs it. See [extension/README.md](extension/README.md).

## Privacy

All data stays on your computer. The extension makes no network requests of its own and sends nothing anywhere. See [PRIVACY.md](PRIVACY.md).

## Tests

```bash
poetry run pytest
cd extension && npm ci && node --test tests/*.test.js
```

## License

MIT. See [LICENSE](LICENSE).

## Not affiliated

Applywright is not affiliated with, endorsed by, or sponsored by JobCopilot, Greenhouse, Lever, Ashby, or LinkedIn. Those names appear only to describe compatibility.
