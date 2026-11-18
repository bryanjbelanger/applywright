# Glossary

Terms for the application package workflow and the job lifecycle. Code and tests use these words in these meanings.

**Payload.** The full proposal for one application package: resume, cover letter with evidence IDs, evidence matrix, and target profile. One implementation of the payload rules, in `applywright.application_packages`, decides if a payload is valid.

**Evidence catalog.** The map from evidence ID to canonical claim in `application_materials/candidate.yaml`. Every claim in a payload must cite an ID from it.

**Draft.** A package before promotion, in the Git-ignored directory `application_materials/work/<slug>/`. The `Draft` module is the only place that knows its files and how to create, open, render, and promote it. Opening a draft revalidates the stored payload.

**Slug.** `<company>-<external_id or job_id>`, derived from the stored job. It names the draft and the package.

**Render record.** The `render` section of a draft's `generation.json`: the hashes of the source files at render time and the final PNG paths.

**Visual review.** The check by a person of every page image, recorded by hand in `output/validation.json`. The review rule, `review_findings`, applies to a draft and to a promoted package.

**Promotion.** The checked move of a reviewed draft from `work/<slug>/` to `jobs/<slug>/`. The previous package stays until the package check has passed.

**Package.** A promoted application in `application_materials/jobs/<slug>/`.

**Job lifecycle.** The rules in `applywright/lifecycle.py` for how a job's `application_status`, `decision`, and `date_applied` change. `JobRepository` applies them. The MCP handlers and the import do not state them.

**Unworked job.** A job with status `discovered` or `saved`. An import may change its status, and a skip moves it to `rejected`. The bridge owns every other status.

**Submitted job.** A job that has a `date_applied`, decision `applied`, or a status of `applied`, `screening`, `interview`, `offer`, or `withdrawn`. It is never deleted.
