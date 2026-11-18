# Agent Rules

These rules apply to every agent task in this repository. "The user" is the person who runs this toolkit for their own job search.

## Human Approval Boundary

- Never submit a job application.
- Never click an application submission button.
- Never answer legal questions. These include work authorization, sponsorship, visa, citizenship, EEO, gender, race, ethnicity, veteran status, disability, pronouns, attestations, certifications of truth, and consent boxes.
- Never call `mark_job` without the user's explicit authorization.
- Never change `decision`, `notes`, `application_status`, or `date_applied` during evaluation, enrichment, ranking, or document generation.
- Never invent experience, dates, employers, titles, certifications, skills, compensation, locations, metrics, or contact information.

## Source of Truth

For resumes and application materials, use sources in this order:

1. `application_materials/candidate.yaml`, the user's evidence catalog.
2. The job description. Use it for selection and tailoring only. It is never evidence for a claim.

The screening profile in `config/candidate_profile.yaml` supports job screening only. Do not turn its evidence IDs into resume claims.

When sources conflict, report the conflict. Do not combine incompatible numbers or claims.

## Application Materials

Before you change anything under `application_materials/`, read `application_materials/README.md`. Every visible resume claim must cite an evidence ID from `candidate.yaml`. Render only through the shared tools. Do not edit generated output by hand.

A package is "ready" only after automated validation passes and the user has seen the rendered pages. If you did not inspect the page images, say so.

## Change Scope

- Change only what the task asks for.
- Do not change code, database files, or MCP tools during an application-material task.
- Before you commit, run `git diff --name-only` and check that every changed file is in scope.

## Verification

Do not report success because a command exited with code 0. Check the source content, the PDF text, the page count, that no placeholders remain, the required sections, the layout, and `git status`.

## Local Data

These paths hold personal data and are Git-ignored: `application_materials/candidate.yaml`, `application_materials/jobs/`, `application_materials/work/`, `application_materials/apply_bundles/`, `config/candidate_profile.yaml`, `config/job_scoring_policy.yaml`, and `data/`. Never commit them. Never copy their content into code, tests, or docs.
