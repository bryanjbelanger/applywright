"""The apply bundle: one promoted package, packed for filling an application form.

The bundle holds contact data, the two PDFs, and the cover letter text. It holds
no attestation, work-authorization, or demographic answers. A human answers
those on the form and submits it.

Only a promoted package under ``jobs/<slug>`` is read. A draft under ``work/``
is never read.
"""

from __future__ import annotations

import base64
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .draft import DraftError, _load_json, _load_yaml, review_findings, validate_slug

PDF_MIME_TYPE = "application/pdf"


class ApplyBundleError(DraftError):
    """Raised when a promoted package cannot be packed into an apply bundle."""


def _url(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if text.startswith(("http://", "https://")):
        return text
    return f"https://{text}"


def _applicant(candidate: dict[str, Any]) -> dict[str, str]:
    full_name = str(candidate.get("name") or "").strip()
    parts = full_name.split()
    return {
        "first_name": parts[0] if parts else "",
        "last_name": " ".join(parts[1:]),
        "full_name": full_name,
        "email": str(candidate.get("email") or "").strip(),
        "phone": str(candidate.get("phone") or "").strip(),
        "location": str(candidate.get("location") or "").strip(),
        "linkedin_url": _url(candidate.get("linkedin")),
        "github_url": _url(candidate.get("github")),
    }


def _file_entry(path: Path, filename: str) -> dict[str, str]:
    return {
        "filename": filename,
        "mime_type": PDF_MIME_TYPE,
        "base64": base64.b64encode(path.read_bytes()).decode("ascii"),
    }


def build_apply_bundle(root: Path, slug: str) -> dict[str, Any]:
    slug = validate_slug(slug)
    materials = Path(root) / "application_materials"
    package = materials / "jobs" / slug
    if not package.is_dir():
        raise ApplyBundleError(f"No promoted package at {package}")

    output = package / "output"
    resume_pdf = output / "Resume.pdf"
    letter_pdf = output / "CoverLetter.pdf"
    for pdf in (resume_pdf, letter_pdf):
        if not pdf.is_file():
            raise ApplyBundleError(f"Required PDF is missing: {pdf}")

    validation_path = output / "validation.json"
    if not validation_path.is_file():
        raise ApplyBundleError(f"Visual review record is missing: {validation_path}")
    output_names = [item.name for item in output.iterdir()]
    findings = review_findings(slug, _load_json(validation_path), output_names)
    if findings:
        raise ApplyBundleError(
            "Visual review has not passed: " + "; ".join(str(f) for f in findings)
        )

    job = _load_json(package / "job.json")
    payload = _load_json(package / "payload.json")
    candidate_path = materials / "candidate.yaml"
    if not candidate_path.is_file():
        raise ApplyBundleError(f"Candidate file is missing: {candidate_path}")
    candidate = _load_yaml(candidate_path)

    letter = payload.get("cover_letter")
    if not isinstance(letter, dict) or not isinstance(letter.get("paragraphs"), list):
        raise ApplyBundleError("payload.json has no cover_letter.paragraphs list")
    paragraphs = [str(item) for item in letter["paragraphs"]]

    return {
        "bundle_version": 1,
        "slug": slug,
        "job_id": payload.get("job_id") or job.get("job_id"),
        "company": letter.get("company_name") or job.get("company"),
        "title": letter.get("position") or job.get("title"),
        "job_url": job.get("job_url"),
        "applicant": _applicant(candidate),
        "files": {
            "resume": _file_entry(resume_pdf, "Resume.pdf"),
            "cover_letter": _file_entry(letter_pdf, "CoverLetter.pdf"),
        },
        "cover_letter_text": "\n\n".join(paragraphs),
        "built_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
