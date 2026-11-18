from pathlib import Path

import yaml

from applywright.application_packages.service import expected_job_slug
from applywright.models import Job
from applywright.server import mcp_app
from applywright.storage.repository import JobRepository

CATALOG = {
    "exp": "Twelve years of platform engineering work.",
    "skill": "Terraform, Puppet, Ansible",
    "employer": "Led infrastructure automation engagements for enterprise clients.",
    "engagement": "Designed and delivered a secure automation platform.",
}


def setup_root(root: Path) -> None:
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


def payload_for(job: Job) -> dict:
    return {
        "job_id": job.job_id,
        "job_slug": expected_job_slug(job),
        "target_profile": {
            "role_family": "devsecops",
            "professional_identity": (
                "DevSecOps and Infrastructure Automation Architect"
            ),
            "emphasis": [
                "infrastructure automation",
                "platform engineering",
                "technical leadership",
            ],
            "deemphasized": [],
            "rationale": (
                "The test target is a DevOps Engineer role focused on automation "
                "platforms and infrastructure as code."
            ),
        },
        "resume": {
            "summary": {
                "text": "Senior architecture consultant.",
                "evidence_ids": ["exp"],
            },
            "core_skills": [
                {"text": "Terraform, Puppet, Ansible", "evidence_ids": ["skill"]}
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
                    "text": "My senior architecture background aligns with this role.",
                    "evidence_ids": ["exp"],
                }
            ],
        },
        "evidence_matrix": [
            {
                "evidence_id": "exp",
                "canonical_evidence": CATALOG["exp"],
                "requirement": "Architecture experience",
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
                "requirement": "Consulting",
                "strength": "strong",
                "used_in": ["Acme Consulting Overview"],
                "notes": "Direct match",
            },
            {
                "evidence_id": "engagement",
                "canonical_evidence": CATALOG["engagement"],
                "requirement": "Platform delivery",
                "strength": "strong",
                "used_in": ["Acme Consulting / Client One Overview"],
                "notes": "Direct match",
            },
        ],
        "unsupported_requirements": [],
        "uncertainties": [],
        "generation_notes": [],
    }


def lifecycle_snapshot(job: Job) -> dict:
    return {
        "updated_at": job.updated_at,
        "decision": job.decision,
        "notes": job.notes,
        "application_status": job.application_status,
        "date_applied": job.date_applied,
    }


def test_prepare_validate_and_materialize_do_not_change_job_state(
    tmp_path, monkeypatch
):
    setup_root(tmp_path)
    monkeypatch.setenv("APPLYWRIGHT_ROOT", str(tmp_path))

    repo = JobRepository(str(tmp_path / "data" / "jobs.db"))
    job = Job(
        job_id="job-123",
        external_id="9876",
        dedupe_key="example-co-devops",
        title="DevOps Engineer",
        company="Example Co.",
        description="Build automation platforms using infrastructure as code.",
        source="jobcopilot",
        application_status="saved",
    )
    repo.upsert_job(job)
    monkeypatch.setattr(mcp_app, "_repo", repo)

    before = lifecycle_snapshot(repo.get_job(job.job_id))
    payload = payload_for(job)

    prepared = mcp_app.prepare_application_package(job.job_id)
    assert prepared["ok"] is True

    validated = mcp_app.validate_application_package(job.job_id, payload)
    assert validated["ok"] is True
    assert validated["human_approval_required"] is True
    assert validated["database_modified"] is False

    denied = mcp_app.materialize_application_draft(job.job_id, payload)
    assert denied["ok"] is False
    assert denied["error_code"] == "human_approval_required"

    materialized = mcp_app.materialize_application_draft(
        job.job_id, payload, human_approved=True
    )
    assert materialized["ok"] is True
    assert materialized["database_modified"] is False
    assert materialized["mark_job_called"] is False

    after = lifecycle_snapshot(repo.get_job(job.job_id))
    assert after == before
