# Application Materials

This directory contains the canonical workflow for generating resumes and cover letters.

## Canonical Directory Structure

```text
application_materials/
  README.md
  candidate.example.yaml   # copy to candidate.yaml (Git-ignored)
  candidate.yaml
  schemas/
  templates/
  styles/
  tools/
  tests/
  work/                    # local-only, Git-ignored drafts
    <job-slug>/
      resume.yaml
      cover_letter.yaml
      evidence_matrix.md
      job.json
      generation.json
      output/
  jobs/
    <job-slug>/
      resume.yaml
      cover_letter.yaml
      evidence_matrix.md
      job.json             # optional source-job record
      generation.json      # optional audit record
      output/
        Resume.html
        Resume.pdf
        Resume-page-*.png
        CoverLetter.html
        CoverLetter.pdf
        CoverLetter-page-*.png
        application.css
        validation.json
```

- `candidate.yaml` is your candidate and evidence catalog. It is Git-ignored. Copy `candidate.example.yaml` to create it.
- `work/` is local-only staging for incomplete or unreviewed packages and must never be committed.
- `jobs/<job-slug>/resume.yaml` and `cover_letter.yaml` are the canonical job-specific content.
- `output/application.css` is a generated copy of the shared stylesheet, not job-specific source CSS.
- `evidence_matrix.md` is supporting audit documentation, not a canonical resume source.

## Source-of-Truth Order

Use sources in this order:

1. `application_materials/candidate.yaml`.
2. The job description, for selection and tailoring only. It is never evidence for a candidate claim.

The screening profile under `config/` is not an application-document evidence source. Do not silently translate screening evidence IDs into application claims.

## Workflow for a New Job

1. Create `application_materials/jobs/<job-slug>/` using a stable slug such as `company-name-jobid`.
2. Write `resume.yaml` and `cover_letter.yaml` according to the JSON schemas. The resume opening professional identity must be selected from the target role function, not automatically from a prestigious historical title.
3. Give every visible resume claim one or more valid evidence IDs from `candidate.yaml`.
4. Add exactly one evidence-matrix row for every evidence ID used by the resume.
5. Render only through the shared command below.
6. Run automated validation and the repository policy checker.
7. Open and inspect every final PNG.
8. Record the visual review in `output/validation.json` and do not rerender afterward unless content changes.

## Generate From a Selected Job

Generation starts from one explicit stored `job_id`. It never selects a job automatically, never submits an application, never calls `mark_job`, and never changes `jobs.db` or lifecycle fields.

The MCP sequence is:

```text
prepare_application_package(job_id)
validate_application_package(job_id, payload)
materialize_application_draft(job_id, payload, human_approved=true)
```

The first two tools are read-only. Materialization requires explicit human approval and writes only to the Git-ignored local staging directory:

```text
application_materials/work/<job-slug>/
```

After materialization, render the draft:

```bash
poetry run python -m application_materials.tools.render_application_draft \
  --slug <job-slug>
```

Open every PNG printed by the command. Record the final repository-relative paths printed by the command in the draft's `output/validation.json`, set `visual_review.status` to `passed`, and record truthful findings only after inspecting every page.

Then promote the completed package:

```bash
poetry run python -m application_materials.tools.promote_application_draft \
  --slug <job-slug> \
  --human-approved
```

Promotion refuses stale renders, incomplete automated validation, incomplete visual review, reviewed-page mismatches, silent overwrites, and repository-policy failures. It atomically moves the reviewed package into `application_materials/jobs/<job-slug>/` and removes the local draft only after success.

## Rendering Command

The one supported low-level rendering command is:

```bash
poetry run python -m application_materials.tools.render_application \
  --candidate application_materials/candidate.yaml \
  --resume application_materials/jobs/<job-slug>/resume.yaml \
  --cover-letter application_materials/jobs/<job-slug>/cover_letter.yaml \
  --output-dir application_materials/jobs/<job-slug>/output
```

The renderer validates YAML and schemas, renders shared Jinja2 templates, copies the shared stylesheet, generates PDFs and PNGs, validates extracted PDF content, and resets visual review to `required`.

## Validation and Visual Review

- Automated validation must pass for every render.
- Open every final `Resume-page-*.png` and `CoverLetter-page-*.png` using an image-viewing tool.
- Inspect contact information, hierarchy, typography, indentation, page breaks, clipping, overlap, malformed characters, excessive blank space, and the cover-letter signature.
- Rendering always resets `visual_review.status` to `required`.
- Set visual review to `passed` only after every final PNG has actually been opened.
- `reviewed_pages` must contain all and only the complete repository-relative paths of the final PNGs.
- Do not rerender after recording the final review unless YAML, shared templates, shared CSS, schemas, or rendering behavior changes.

Generated output must not be hand-edited. The sole permitted manual update inside generated output is recording the `visual_review` fields in `validation.json` after inspecting every final PNG. Automated-validation fields must never be manually changed.

## Local Verification — No-Cost Gate

Application-material validation is intentionally runnable without a paid GitHub Actions runner. After committing the intended changes, run:

```bash
bash application_materials/tools/verify_local.sh
```

The script installs the required Poetry groups, runs the application-material and Applywright test suites, runs the repository policy checker, checks for whitespace errors, and requires a clean working tree. A successful run is the required local merge gate when hosted CI is unavailable.

During development, the individual commands are:

```bash
poetry install --with document-rendering,dev
poetry run pytest
poetry run python -m application_materials.tools.check_repository
git diff --check
git status --short
```

## Prohibited Patterns

The following are prohibited under `application_materials/jobs/`:

- per-job `generate_and_test.py` files or other Python renderers;
- source CSS anywhere inside a job directory;
- inline `<style>` blocks or `style=` attributes in generated HTML;
- canonical `resume.md` or `cover_letter.md` files;
- copied `.j2`, `.jinja2`, or HTML templates;
- modifying generated HTML, PDF, PNG, CSS, or automated-validation results by hand;
- marking visual review passed without opening every final rendered page.

Always edit canonical YAML or shared infrastructure and rerender through the shared command.
