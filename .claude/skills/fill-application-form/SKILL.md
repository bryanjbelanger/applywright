---
name: fill-application-form
description: Fill an application form on any employer site (Workday, iCIMS, Taleo, custom forms) from an apply bundle with the Claude in Chrome tools. Fills standard fields, uploads the PDFs, skips legal questions, and stops before Submit. Use when the user asks to fill or pre-fill a job application form in the browser.
---

# Fill an application form

You fill the form. The user reviews it and submits it. Read `AGENTS.md` at the repository root first.

## Hard rules

- Never click Submit, Apply, Send, Finish, or any control that sends the application. Never press Enter in a way that submits the form.
- Never answer these fields. Leave them empty and list them for the user: work authorization, sponsorship, visa, citizenship, gender, race, ethnicity, veteran status, disability, pronouns, sexual orientation, "I certify", "I attest", "I agree", consent boxes, and any EEO or demographic question.
- Never invent a value. Fill only what the bundle holds.
- Do not create accounts or sign in for the user. If the site needs a login or a password, stop and tell the user.

## Steps

1. Get the bundle path from the user. It is `application_materials/apply_bundles/<slug>.json`. If it does not exist, tell the user to run `poetry run python application_materials/tools/build_apply_bundle.py <slug>`. Do not build it yourself from a draft.
2. Read the bundle with Read. Use `applicant`, `cover_letter_text`, and `files`.
3. Load the Claude in Chrome tools (ToolSearch for `mcp__claude-in-chrome__*`). Open the application page. Use `read_page` to list the form fields.
4. Fill these fields with `form_input`: first name, last name (or full name), email, phone, location or city, LinkedIn URL, GitHub URL. Fill the cover letter box with `cover_letter_text` if there is no file input for it.
5. Write the PDFs from `files.resume.base64` and `files.cover_letter.base64` to files named `Resume.pdf` and `CoverLetter.pdf` in the scratchpad directory. Upload them with `file_upload` to the resume and cover letter inputs.
6. Leave everything else empty, including salary, start date, referral source, and free-text questions.
7. Read the page again. Check each filled value.
8. Stop. Do not scroll to or touch the Submit button.

## Report to the user

List four things:

1. Fields you filled.
2. Files you uploaded.
3. Protected fields left for the user.
4. Required fields that are still empty.

Say "Not submitted. Review the form and click Submit yourself." After the user submits, they can ask you for the submission details. You may then write a `submission-<slug>.json` file with `job_id`, `package_slug`, `application_source_url`, `submitted_at`, and any confirmation text. Never call `mark_job`. Only the user authorizes it.
