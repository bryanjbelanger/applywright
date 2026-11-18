"""The apply bundle: contact data, PDFs, and cover letter text for one package."""

import base64
import json

import pytest
import yaml

from applywright.application_packages.apply_bundle import (
    ApplyBundleError,
    build_apply_bundle,
)

SLUG = "example-co-devops"
RESUME_BYTES = b"%PDF-1.4 resume"
LETTER_BYTES = b"%PDF-1.4 letter"


def write_fixture(root, slug=SLUG, *, area="jobs", review="passed", pdfs=True):
    materials = root / "application_materials"
    package = materials / area / slug
    output = package / "output"
    output.mkdir(parents=True)
    materials.joinpath("candidate.yaml").write_text(
        yaml.safe_dump(
            {
                "name": "Ada Q Lovelace",
                "email": "ada@example.com",
                "phone": "555-0100",
                "location": "Somewhere, MI",
                "linkedin": "linkedin.com/in/ada",
                "github": "github.com/ada",
            }
        ),
        encoding="utf-8",
    )
    (package / "job.json").write_text(
        json.dumps(
            {
                "company": "Example Co.",
                "title": "DevOps Engineer",
                "job_url": "https://app.jobcopilot.com/applications/review/9",
            }
        ),
        encoding="utf-8",
    )
    (package / "payload.json").write_text(
        json.dumps(
            {
                "job_id": "job-123",
                "job_slug": slug,
                "cover_letter": {
                    "company_name": "Example Co.",
                    "position": "DevOps Engineer",
                    "paragraphs": ["First.", "Second."],
                },
            }
        ),
        encoding="utf-8",
    )
    if pdfs:
        (output / "Resume.pdf").write_bytes(RESUME_BYTES)
        (output / "CoverLetter.pdf").write_bytes(LETTER_BYTES)
    pngs = [f"application_materials/{area}/{slug}/output/Resume-page-1.png"]
    (output / "Resume-page-1.png").write_bytes(b"png")
    (output / "validation.json").write_text(
        json.dumps(
            {
                "automated_validation": {"passed": True},
                "visual_review": {"status": review, "reviewed_pages": pngs},
            }
        ),
        encoding="utf-8",
    )


def test_bundle_content(tmp_path):
    write_fixture(tmp_path)
    bundle = build_apply_bundle(tmp_path, SLUG)

    assert bundle["bundle_version"] == 1
    assert bundle["slug"] == SLUG
    assert bundle["job_id"] == "job-123"
    assert bundle["company"] == "Example Co."
    assert bundle["title"] == "DevOps Engineer"
    assert bundle["job_url"] == "https://app.jobcopilot.com/applications/review/9"
    assert bundle["applicant"] == {
        "first_name": "Ada",
        "last_name": "Q Lovelace",
        "full_name": "Ada Q Lovelace",
        "email": "ada@example.com",
        "phone": "555-0100",
        "location": "Somewhere, MI",
        "linkedin_url": "https://linkedin.com/in/ada",
        "github_url": "https://github.com/ada",
    }
    resume = bundle["files"]["resume"]
    assert resume["filename"] == "Resume.pdf"
    assert resume["mime_type"] == "application/pdf"
    assert base64.b64decode(resume["base64"]) == RESUME_BYTES
    letter = bundle["files"]["cover_letter"]
    assert letter["filename"] == "CoverLetter.pdf"
    assert base64.b64decode(letter["base64"]) == LETTER_BYTES
    assert bundle["cover_letter_text"] == "First.\n\nSecond."
    assert bundle["built_at"]
    text = json.dumps(bundle).lower()
    assert "authoriz" not in text and "eeo" not in text


def test_refuses_missing_package(tmp_path):
    (tmp_path / "application_materials" / "jobs").mkdir(parents=True)
    with pytest.raises(ApplyBundleError, match="No promoted package"):
        build_apply_bundle(tmp_path, SLUG)


def test_refuses_draft_only(tmp_path):
    write_fixture(tmp_path, area="work")
    (tmp_path / "application_materials" / "jobs").mkdir()
    with pytest.raises(ApplyBundleError, match="No promoted package"):
        build_apply_bundle(tmp_path, SLUG)


@pytest.mark.parametrize("name", ["Resume.pdf", "CoverLetter.pdf"])
def test_refuses_missing_pdf(tmp_path, name):
    write_fixture(tmp_path)
    (tmp_path / "application_materials" / "jobs" / SLUG / "output" / name).unlink()
    with pytest.raises(ApplyBundleError, match=name):
        build_apply_bundle(tmp_path, SLUG)


def test_refuses_failing_review(tmp_path):
    write_fixture(tmp_path, review="pending")
    with pytest.raises(ApplyBundleError, match="Visual review has not passed"):
        build_apply_bundle(tmp_path, SLUG)


def test_refuses_missing_review_record(tmp_path):
    write_fixture(tmp_path)
    (
        tmp_path
        / "application_materials"
        / "jobs"
        / SLUG
        / "output"
        / "validation.json"
    ).unlink()
    with pytest.raises(ApplyBundleError, match="Visual review record is missing"):
        build_apply_bundle(tmp_path, SLUG)
