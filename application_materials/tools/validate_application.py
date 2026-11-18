import json
import jsonschema
import os
import re
from pypdf import PdfReader
from bs4 import BeautifulSoup


def validate_schemas(candidate_data, resume_data, cover_letter_data, schema_dir):
    with open(os.path.join(schema_dir, "candidate.schema.json")) as f:
        candidate_schema = json.load(f)
    with open(os.path.join(schema_dir, "resume.schema.json")) as f:
        resume_schema = json.load(f)
    with open(os.path.join(schema_dir, "cover_letter.schema.json")) as f:
        cover_letter_schema = json.load(f)

    jsonschema.validate(instance=candidate_data, schema=candidate_schema)
    jsonschema.validate(instance=resume_data, schema=resume_schema)
    jsonschema.validate(instance=cover_letter_data, schema=cover_letter_schema)


def validate_chronology(resume_data):
    for exp in resume_data.get("experience", []):
        start = exp.get("start_year")
        end = exp.get("end_year")
        if end != "Present" and end < start:
            raise ValueError(
                f"Chronology error: end_year {end} is before start_year {start}"
            )


def validate_evidence(candidate_data, resume_data):
    catalog = set(candidate_data.get("evidence_catalog", {}).keys())
    if not catalog:
        raise ValueError("Evidence catalog is empty")

    def check_ids(evid_list):
        for evid in evid_list:
            if evid not in catalog:
                raise ValueError(f"Unknown evidence ID: {evid}")

    summary_ids = resume_data.get("summary", {}).get("evidence_ids", [])
    if summary_ids:
        check_ids(summary_ids)

    for skill in resume_data.get("core_skills", []):
        check_ids(skill.get("evidence_ids", []))

    for exp in resume_data.get("experience", []):
        if "overview" in exp and "evidence_ids" in exp["overview"]:
            check_ids(exp["overview"]["evidence_ids"])

        for eng in exp.get("engagements", []):
            if "overview" in eng and "evidence_ids" in eng["overview"]:
                check_ids(eng["overview"]["evidence_ids"])

            for ach in eng.get("achievements", []):
                check_ids(ach.get("evidence_ids", []))


def validate_input(candidate_data, resume_data, cover_letter_data, schema_dir):
    validate_schemas(candidate_data, resume_data, cover_letter_data, schema_dir)
    validate_chronology(resume_data)
    validate_evidence(candidate_data, resume_data)


def validate_html(html_path, resume_data):
    with open(html_path, "r", encoding="utf-8") as f:
        soup = BeautifulSoup(f.read(), "html.parser")

    # Verify engagement count
    total_engagements = sum(
        len(exp.get("engagements", [])) for exp in resume_data.get("experience", [])
    )
    rendered_engagements = soup.find_all("section", class_="engagement")
    if len(rendered_engagements) != total_engagements:
        raise ValueError(
            f"Engagement count mismatch: expected {total_engagements}, found {len(rendered_engagements)}"
        )

    # Verify employer order
    employers = soup.find_all(class_="employer-name")
    expected_employers = [exp["employer"] for exp in resume_data.get("experience", [])]
    rendered_employer_names = [emp.get_text().strip() for emp in employers]
    if rendered_employer_names != expected_employers:
        raise ValueError(
            f"Employer order mismatch: expected {expected_employers}, found {rendered_employer_names}"
        )

    # Verify engagement order
    engagements = soup.find_all(class_="client-name")
    expected_engagements = []
    for exp in resume_data.get("experience", []):
        for eng in exp.get("engagements", []):
            expected_engagements.append(eng["client"] + ":")
    rendered_engagement_names = [eng.get_text().strip() for eng in engagements]
    if rendered_engagement_names != expected_engagements:
        raise ValueError(
            f"Engagement order mismatch: expected {expected_engagements}, found {rendered_engagement_names}"
        )

    # Verify achievement order
    achievements = soup.find_all("li", class_="achievement")
    expected_achievements = []
    for exp in resume_data.get("experience", []):
        for eng in exp.get("engagements", []):
            for ach in eng.get("achievements", []):
                expected_achievements.append(ach["text"])
    rendered_achievement_texts = [ach.get_text().strip() for ach in achievements]
    if rendered_achievement_texts != expected_achievements:
        raise ValueError("Achievement order mismatch")

    # Verify achievements are direct children of ul.achievement-list and within engagement
    for ach in achievements:
        parent = ach.parent
        if parent.name != "ul" or "achievement-list" not in parent.get("class", []):
            raise ValueError("Achievement is not a direct child of ul.achievement-list")
        engagement = ach.find_parent("section", class_="engagement")
        if not engagement:
            raise ValueError("Achievement exists outside an engagement")

    # Verify required sections exist
    for section_id in [
        "summary",
        "skills",
        "experience",
        "education",
        "certifications",
    ]:
        if not soup.find(id=section_id):
            raise ValueError(f"Required section missing: {section_id}")


def validate_cover_letter_html(html_path, candidate_data, cover_letter_data):
    with open(html_path, "r", encoding="utf-8") as f:
        soup = BeautifulSoup(f.read(), "html.parser")

    text = soup.get_text()

    if cover_letter_data["company_name"] not in text:
        raise ValueError("Missing company name in cover letter HTML")

    if cover_letter_data.get("position"):
        position = cover_letter_data["position"]
        if position not in text:
            raise ValueError(
                f"Missing target position in cover letter HTML: {position}"
            )

    if candidate_data["name"] not in text:
        raise ValueError("Missing candidate name in cover letter HTML")

    expected_paragraphs = cover_letter_data.get("paragraphs", [])
    rendered_paragraphs = [
        p.get_text().strip()
        for p in soup.find_all("p", class_="cover-letter-paragraph")
    ]
    if rendered_paragraphs != expected_paragraphs:
        raise ValueError("Paragraphs order or content mismatch in cover letter HTML")

    signatures = soup.find_all(class_="signature-block")
    if len(signatures) != 1:
        raise ValueError(f"Expected exactly 1 signature block, found {len(signatures)}")

    if "[" in text or "]" in text or "<" in text or ">" in text:
        raise ValueError("Placeholder text found in cover letter HTML")


def extract_pdf_text(pdf_path):
    reader = PdfReader(pdf_path)
    text = ""
    for page in reader.pages:
        text += page.extract_text() + "\n"
    return text


def validate_pdf_content(pdf_path, expected_strings, check_placeholders=True):
    text = extract_pdf_text(pdf_path)
    if check_placeholders:
        if "[" in text or "]" in text or "<" in text or ">" in text:
            raise ValueError(f"Placeholder text found in {pdf_path}")

    missing = []
    for s in expected_strings:
        if s not in text:
            missing.append(s)

    if missing:
        raise ValueError(f"Missing expected strings in {pdf_path}: {missing}")

    return text


def validate_ats_resume(resume_pdf, candidate_data, resume_data):
    """ATS-parseability gate for the rendered resume PDF.

    Simulates what an applicant tracking system extracts and fails the render if
    the resume would parse badly:
      - not real/selectable text (scanned-image or near-empty render),
      - contact info (email/phone) not recoverable from the text,
      - a missing standard section heading, or
      - a skill/keyword line broken across a line wrap (e.g. 'CI/CD' rendered as
        'CI/ CD'), which defeats recruiter keyword search.
    Raises ValueError so the shared renderer aborts and cleans up the staged
    output rather than promoting an un-parseable resume.
    """
    raw = extract_pdf_text(resume_pdf)
    problems = []

    # 1. Real, selectable text (not an image / near-empty render). A scanned or
    #    empty PDF extracts next to nothing; any genuine text resume clears this
    #    comfortably, so the threshold only needs to separate "text" from "image".
    if len(raw.strip()) < 300:
        problems.append(
            f"only {len(raw.strip())} chars of selectable text extracted; "
            "resume may be image-based / not machine-readable"
        )

    # Normalize the way an ATS effectively does: join hyphen-wrapped words and
    # collapse whitespace, so ordinary line wraps do not trip the checks below.
    norm = re.sub(r"-\r?\n\s*", "-", raw)
    norm = re.sub(r"\s+", " ", norm)

    # 2. Contact info recoverable as text.
    email = (candidate_data.get("email") or "").strip()
    phone = (candidate_data.get("phone") or "").strip()
    if email and email not in norm:
        problems.append(f"email '{email}' not recoverable from resume text")
    if phone:
        phone_digits = re.sub(r"\D", "", phone)
        if phone_digits and phone_digits not in re.sub(r"\D", "", norm):
            problems.append(f"phone '{phone}' not recoverable from resume text")

    # 3. Standard section headings an ATS keys on.
    headings = [
        "Professional Summary",
        "Core Technical Skills",
        "Professional Experience",
    ]
    if candidate_data.get("education"):
        headings.append("Education")
    if candidate_data.get("certifications"):
        headings.append("Certifications")
    for heading in headings:
        if heading not in norm:
            problems.append(f"missing standard section heading '{heading}'")

    # 4. Keyword integrity: every skill line must survive extraction intact.
    #    A slash/hyphen line-wrap (e.g. 'CI/CD' -> 'CI/ CD') inserts a space that
    #    is not in the source, so the line no longer matches and the keyword is
    #    lost to recruiter search.
    for skill in resume_data.get("core_skills", []):
        skill_text = re.sub(r"\s+", " ", (skill.get("text") or "")).strip()
        if skill_text and skill_text not in norm:
            problems.append(
                "skill/keyword line not intact in the PDF text (likely a "
                f"line-wrap split): '{skill_text[:70]}'"
            )

    if problems:
        raise ValueError(
            f"ATS-parse gate failed for {resume_pdf}:\n  - " + "\n  - ".join(problems)
        )
    return raw


def validate_pdf_output(
    candidate_data,
    resume_data,
    cover_letter_data,
    resume_pdf,
    cover_letter_pdf,
):

    expected_resume_strings = [
        "Professional Summary",
        "Core Technical Skills",
        "Professional Experience",
    ]
    for exp in resume_data.get("experience", []):
        expected_resume_strings.append(exp["employer"])
        for eng in exp.get("engagements", []):
            expected_resume_strings.append(eng["client"])

    validate_pdf_content(resume_pdf, expected_resume_strings)

    # ATS-parseability gate: fail the render before promotion if the resume
    # would not survive an applicant-tracking-system parse.
    validate_ats_resume(resume_pdf, candidate_data, resume_data)

    cl_text = extract_pdf_text(cover_letter_pdf)
    cl_text = re.sub(r"-\r?\n\s*", "-", cl_text)
    cl_normalized = re.sub(r"\s+", " ", cl_text)

    if cover_letter_data["company_name"] not in cl_normalized:
        raise ValueError("Missing company name in cover letter PDF")

    if (
        cover_letter_data.get("position")
        and cover_letter_data["position"] not in cl_normalized
    ):
        raise ValueError("Missing target position in cover letter PDF")

    if candidate_data["name"] not in cl_normalized:
        raise ValueError("Missing candidate name in cover letter PDF")

    last_idx = -1
    for p in cover_letter_data.get("paragraphs", []):
        norm_p = re.sub(r"\s+", " ", p)
        idx = cl_normalized.find(norm_p)
        if idx == -1:
            raise ValueError(f"Missing paragraph in cover letter PDF: {p}")
        if idx < last_idx:
            raise ValueError("Paragraphs out of order in cover letter PDF")
        last_idx = idx

    if "[" in cl_text or "]" in cl_text or "<" in cl_text or ">" in cl_text:
        raise ValueError(f"Placeholder text found in {cover_letter_pdf}")
