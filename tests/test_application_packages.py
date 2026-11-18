import copy
import json
from pathlib import Path

import pytest
import yaml

from applywright.application_packages.service import (
    ApplicationPackageValidationError,
    expected_job_slug,
    prepare_application_package_context,
    validate_application_package_payload,
)
from applywright.models import Job

CATALOG = {
    "exp": "Twelve years of platform engineering work.",
    "skill": "Terraform, Puppet, Ansible",
    "employer": "Led infrastructure automation engagements for enterprise clients.",
    "engagement": "Designed and delivered a secure automation platform.",
}


def write_candidate(root: Path) -> None:
    application_root = root / "application_materials"
    application_root.mkdir(parents=True)
    (application_root / "candidate.yaml").write_text(
        yaml.safe_dump(
            {
                "name": "Candidate",
                "email": "candidate@example.com",
                "phone": "555-0100",
                "location": "Somewhere, MI",
                "education": [],
                "certifications": [],
                "evidence_catalog": CATALOG,
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    (application_root / "jobs").mkdir()


def make_job(**overrides) -> Job:
    values = {
        "job_id": "job-123",
        "external_id": "9876",
        "dedupe_key": "example-co-devops",
        "title": "DevOps Engineer",
        "company": "Example Co.",
        "description": "Build automation platforms using infrastructure as code.",
        "source": "jobcopilot",
        "application_status": "saved",
    }
    values.update(overrides)
    return Job(**values)


def make_payload(job: Job) -> dict:
    return {
        "job_id": job.job_id,
        "job_slug": expected_job_slug(job),
        "target_profile": {
            "role_family": "technical_architecture",
            "professional_identity": "Enterprise Technical Architect",
            "emphasis": [
                "enterprise modernization",
                "infrastructure automation",
                "technical leadership",
            ],
            "deemphasized": ["Niche-specific identity"],
            "rationale": "The target is a general Technical Architect role and does not request niche-platform experience.",
        },
        "resume": {
            "summary": {
                "text": "Senior architecture and automation consultant.",
                "evidence_ids": ["exp"],
            },
            "core_skills": [
                {
                    "text": "Infrastructure as Code: Terraform, Puppet, Ansible",
                    "evidence_ids": ["skill"],
                }
            ],
            "experience": [
                {
                    "employer": "Acme Consulting",
                    "title": "Principal Consultant",
                    "start_year": "2019",
                    "end_year": "2024",
                    "overview": {
                        "text": "Led infrastructure automation engagements for enterprise clients.",
                        "evidence_ids": ["employer"],
                    },
                    "engagements": [
                        {
                            "client": "Client One",
                            "overview": {
                                "text": "Designed and delivered a secure automation platform.",
                                "evidence_ids": ["engagement"],
                            },
                            "achievements": [],
                        }
                    ],
                }
            ],
        },
        "cover_letter": {
            "company_name": job.company,
            "position": job.title,
            "paragraphs": [
                {
                    "text": "My senior architecture and consulting background aligns with this role.",
                    "evidence_ids": ["exp"],
                }
            ],
        },
        "evidence_matrix": [
            {
                "evidence_id": "exp",
                "canonical_evidence": CATALOG["exp"],
                "requirement": "Senior architecture experience",
                "strength": "strong",
                "used_in": ["Resume Summary", "Cover Letter Paragraph 1"],
                "notes": "Direct match",
            },
            {
                "evidence_id": "skill",
                "canonical_evidence": CATALOG["skill"],
                "requirement": "Infrastructure as Code",
                "strength": "strong",
                "used_in": ["Resume Skill 1"],
                "notes": "Direct match",
            },
            {
                "evidence_id": "employer",
                "canonical_evidence": CATALOG["employer"],
                "requirement": "Enterprise consulting",
                "strength": "strong",
                "used_in": ["Acme Consulting Overview"],
                "notes": "Direct match",
            },
            {
                "evidence_id": "engagement",
                "canonical_evidence": CATALOG["engagement"],
                "requirement": "Automation platform delivery",
                "strength": "strong",
                "used_in": ["Acme Consulting / Client One Overview"],
                "notes": "Direct match",
            },
        ],
        "unsupported_requirements": [],
        "uncertainties": ["Compensation was not provided."],
        "generation_notes": ["Tailored to infrastructure automation."],
    }


def test_expected_job_slug_uses_company_and_external_id():
    assert expected_job_slug(make_job()) == "example-co-9876"


def test_expected_job_slug_falls_back_to_job_id():
    job = make_job(external_id=None, job_id="ABC_123")
    assert expected_job_slug(job) == "example-co-abc-123"


def test_prepare_context_is_read_only_and_reports_paths(tmp_path):
    write_candidate(tmp_path)
    job = make_job()
    before = job.model_dump(mode="json")

    context = prepare_application_package_context(job, tmp_path)

    assert context["expected_job_slug"] == "example-co-9876"
    assert context["evidence_catalog"] == CATALOG
    assert context["draft_exists"] is False
    assert context["final_package_exists"] is False
    assert context["human_approval_required"] is True
    assert job.model_dump(mode="json") == before


def test_prepare_rejects_missing_description(tmp_path):
    write_candidate(tmp_path)
    with pytest.raises(ApplicationPackageValidationError, match="description"):
        prepare_application_package_context(make_job(description=None), tmp_path)


def test_valid_payload_passes(tmp_path):
    write_candidate(tmp_path)
    job = make_job()
    validated = validate_application_package_payload(job, make_payload(job), tmp_path)
    assert validated.job_slug == "example-co-9876"


def test_company_mismatch_is_rejected(tmp_path):
    write_candidate(tmp_path)
    job = make_job()
    payload = make_payload(job)
    payload["cover_letter"]["company_name"] = "Wrong Company"
    with pytest.raises(ApplicationPackageValidationError, match="company_name"):
        validate_application_package_payload(job, payload, tmp_path)


def test_title_mismatch_is_rejected(tmp_path):
    write_candidate(tmp_path)
    job = make_job()
    payload = make_payload(job)
    payload["cover_letter"]["position"] = "Wrong Role"
    with pytest.raises(ApplicationPackageValidationError, match="position"):
        validate_application_package_payload(job, payload, tmp_path)


def test_slug_mismatch_is_rejected(tmp_path):
    write_candidate(tmp_path)
    job = make_job()
    payload = make_payload(job)
    payload["job_slug"] = "wrong-123"
    with pytest.raises(ApplicationPackageValidationError, match="job_slug"):
        validate_application_package_payload(job, payload, tmp_path)


def test_unknown_evidence_is_rejected(tmp_path):
    write_candidate(tmp_path)
    job = make_job()
    payload = make_payload(job)
    payload["resume"]["summary"]["evidence_ids"] = ["unknown"]
    payload["evidence_matrix"][0]["evidence_id"] = "unknown"
    payload["evidence_matrix"][0]["canonical_evidence"] = "Unknown"
    with pytest.raises(ApplicationPackageValidationError, match="Unknown evidence IDs"):
        validate_application_package_payload(job, payload, tmp_path)


def test_duplicate_evidence_rows_are_rejected(tmp_path):
    write_candidate(tmp_path)
    job = make_job()
    payload = make_payload(job)
    payload["evidence_matrix"].append(copy.deepcopy(payload["evidence_matrix"][0]))
    with pytest.raises(ApplicationPackageValidationError, match="duplicate"):
        validate_application_package_payload(job, payload, tmp_path)


def test_incomplete_evidence_matrix_is_rejected(tmp_path):
    write_candidate(tmp_path)
    job = make_job()
    payload = make_payload(job)
    payload["evidence_matrix"] = payload["evidence_matrix"][:-1]
    with pytest.raises(ApplicationPackageValidationError, match="exactly"):
        validate_application_package_payload(job, payload, tmp_path)


def test_canonical_evidence_mismatch_is_rejected(tmp_path):
    write_candidate(tmp_path)
    job = make_job()
    payload = make_payload(job)
    payload["evidence_matrix"][0]["canonical_evidence"] = "Invented claim"
    with pytest.raises(ApplicationPackageValidationError, match="Canonical evidence"):
        validate_application_package_payload(job, payload, tmp_path)


def test_cover_paragraph_without_evidence_is_rejected(tmp_path):
    write_candidate(tmp_path)
    job = make_job()
    payload = make_payload(job)
    payload["cover_letter"]["paragraphs"][0]["evidence_ids"] = []
    with pytest.raises(ApplicationPackageValidationError, match="required schema"):
        validate_application_package_payload(job, payload, tmp_path)


def test_missing_target_profile_is_rejected(tmp_path):
    write_candidate(tmp_path)
    job = make_job()
    payload = make_payload(job)
    del payload["target_profile"]
    with pytest.raises(ApplicationPackageValidationError, match="target_profile"):
        validate_application_package_payload(job, payload, tmp_path)


def test_blank_professional_identity_is_rejected(tmp_path):
    write_candidate(tmp_path)
    job = make_job()
    payload = make_payload(job)
    payload["target_profile"]["professional_identity"] = "   "
    with pytest.raises(
        ApplicationPackageValidationError,
        match="target_profile.professional_identity",
    ):
        validate_application_package_payload(job, payload, tmp_path)


def test_empty_emphasis_is_rejected(tmp_path):
    write_candidate(tmp_path)
    job = make_job()
    payload = make_payload(job)
    payload["target_profile"]["emphasis"] = []
    with pytest.raises(
        ApplicationPackageValidationError, match="target_profile.emphasis"
    ):
        validate_application_package_payload(job, payload, tmp_path)


def test_duplicate_emphasis_is_rejected(tmp_path):
    write_candidate(tmp_path)
    job = make_job()
    payload = make_payload(job)
    payload["target_profile"]["emphasis"] = ["duplicate", "duplicate"]
    with pytest.raises(ApplicationPackageValidationError, match="must be unique"):
        validate_application_package_payload(job, payload, tmp_path)


def test_extra_target_profile_field_is_rejected(tmp_path):
    write_candidate(tmp_path)
    job = make_job()
    payload = make_payload(job)
    payload["target_profile"]["extra_field"] = "foo"
    with pytest.raises(
        ApplicationPackageValidationError, match="target_profile.extra_field"
    ):
        validate_application_package_payload(job, payload, tmp_path)


def test_candidate_file_that_is_not_a_mapping_is_rejected(tmp_path):
    write_candidate(tmp_path)
    (tmp_path / "application_materials" / "candidate.yaml").write_text(
        "- not\n- a mapping\n", encoding="utf-8"
    )
    job = make_job()
    with pytest.raises(ApplicationPackageValidationError, match="must contain a mapping"):
        validate_application_package_payload(job, make_payload(job), tmp_path)


def test_catalog_claim_that_is_not_a_string_is_rejected(tmp_path):
    write_candidate(tmp_path)
    candidate_path = tmp_path / "application_materials" / "candidate.yaml"
    candidate = yaml.safe_load(candidate_path.read_text(encoding="utf-8"))
    candidate["evidence_catalog"]["exp"] = None
    candidate_path.write_text(yaml.safe_dump(candidate), encoding="utf-8")
    job = make_job()
    with pytest.raises(ApplicationPackageValidationError, match="must be strings"):
        validate_application_package_payload(job, make_payload(job), tmp_path)


def test_placeholder_is_rejected(tmp_path):
    write_candidate(tmp_path)
    job = make_job()
    payload = make_payload(job)
    payload["resume"]["summary"]["text"] = "TODO replace this summary"
    with pytest.raises(ApplicationPackageValidationError, match="Placeholder"):
        validate_application_package_payload(job, payload, tmp_path)


def test_used_in_mismatch_is_rejected(tmp_path):
    write_candidate(tmp_path)
    job = make_job()
    payload = make_payload(job)
    payload["evidence_matrix"][0]["used_in"] = ["Resume Summary"]
    with pytest.raises(ApplicationPackageValidationError, match="used_in mismatch"):
        validate_application_package_payload(job, payload, tmp_path)
