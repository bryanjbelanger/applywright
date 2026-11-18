import json
from pathlib import Path

import pytest
import yaml

from application_materials.tools import promote_application_draft as promote_module
from application_materials.tools.render_application import (
    RenderError,
    RenderInputError,
)
from application_materials.tools.promote_application_draft import (
    promote_application_draft,
)
from application_materials.tools.render_application_draft import (
    render_application_draft,
)
from applywright.application_packages import Draft, DraftError
from applywright.models import Job

SLUG = "example-co-9876"


def write_json(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def setup_repository(root: Path) -> Path:
    """Create a repository root that holds one real draft, made by the bridge."""
    app = root / "application_materials"
    (app / "schemas").mkdir(parents=True)
    (app / "jobs").mkdir()

    candidate = {
        "name": "Candidate",
        "email": "candidate@example.com",
        "phone": "555-0100",
        "location": "Somewhere, MI",
        "education": [],
        "certifications": [],
        "evidence_catalog": {"exp": "Architecture experience"},
    }
    (app / "candidate.yaml").write_text(
        yaml.safe_dump(candidate, sort_keys=False), encoding="utf-8"
    )
    permissive_schema = {"type": "object"}
    for name in (
        "candidate.schema.json",
        "resume.schema.json",
        "cover_letter.schema.json",
    ):
        write_json(app / "schemas" / name, permissive_schema)

    job = Job(
        job_id="job-123",
        external_id="9876",
        dedupe_key="example-co-devops-engineer",
        company="Example Co.",
        title="DevOps Engineer",
        description="Build automation platforms.",
        source="jobcopilot",
    )
    claim = {"text": "Architecture experience", "evidence_ids": ["exp"]}
    payload = {
        "job_id": job.job_id,
        "job_slug": SLUG,
        "target_profile": {
            "role_family": "technical_architecture",
            "professional_identity": "Enterprise Technical Architect",
            "emphasis": ["enterprise modernization", "infrastructure automation"],
            "deemphasized": ["Pega-specific identity"],
            "rationale": "The target is a general Technical Architect role.",
        },
        "resume": {
            "summary": {"text": "Architecture leader", "evidence_ids": ["exp"]},
            "core_skills": [
                {"text": "Infrastructure automation", "evidence_ids": ["exp"]}
            ],
            "experience": [
                {
                    "employer": "Acme",
                    "title": "Architect",
                    "start_year": "2019",
                    "end_year": "2024",
                    "overview": claim,
                    "engagements": [
                        {"client": "Client One", "overview": claim, "achievements": []}
                    ],
                }
            ],
        },
        "cover_letter": {
            "company_name": "Example Co.",
            "position": "DevOps Engineer",
            "paragraphs": [
                {
                    "text": "My architecture experience aligns with this role.",
                    "evidence_ids": ["exp"],
                }
            ],
        },
        "evidence_matrix": [
            {
                "evidence_id": "exp",
                "canonical_evidence": "Architecture experience",
                "requirement": "Architecture experience",
                "strength": "strong",
                "used_in": [
                    "Resume Summary",
                    "Resume Skill 1",
                    "Acme Overview",
                    "Acme / Client One Overview",
                    "Cover Letter Paragraph 1",
                ],
                "notes": "Direct alignment",
            }
        ],
        "generation_notes": ["Test fixture package."],
        "uncertainties": [],
        "unsupported_requirements": [],
    }
    return Draft.create(job, payload, human_approved=True, repo_root=root).path


def fake_renderer(
    candidate_path, resume_path, cover_letter_path, output_dir, schema_dir=None
):
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    for name in (
        "Resume.html",
        "Resume.pdf",
        "CoverLetter.html",
        "CoverLetter.pdf",
        "application.css",
    ):
        (output_dir / name).write_text("generated", encoding="utf-8")
    (output_dir / "Resume-page-1.png").write_bytes(b"resume")
    (output_dir / "CoverLetter-page-1.png").write_bytes(b"cover")
    write_json(
        output_dir / "validation.json",
        {
            "automated_validation": {"passed": True},
            "visual_review": {
                "status": "required",
                "reviewed_pages": [],
                "findings": [],
            },
        },
    )


def mark_review_passed(root: Path) -> None:
    validation_path = (
        root / "application_materials" / "work" / SLUG / "output" / "validation.json"
    )
    validation = json.loads(validation_path.read_text(encoding="utf-8"))
    validation["visual_review"] = {
        "status": "passed",
        "reviewed_pages": [
            f"application_materials/jobs/{SLUG}/output/CoverLetter-page-1.png",
            f"application_materials/jobs/{SLUG}/output/Resume-page-1.png",
        ],
        "findings": ["All pages were opened and inspected."],
    }
    write_json(validation_path, validation)


def test_render_rejects_missing_draft(tmp_path):
    setup_repository(tmp_path)
    with pytest.raises(DraftError, match="does not exist"):
        render_application_draft(
            "missing-123", repo_root=tmp_path, renderer=fake_renderer
        )


def test_render_accepts_cover_letter_identity_that_differs_only_by_case(tmp_path):
    """The bridge matches company and position without regard to letter case.

    Render must agree, or a draft that the bridge materialized cannot render.
    """
    draft = setup_repository(tmp_path)
    job_path = draft / "job.json"
    job = json.loads(job_path.read_text(encoding="utf-8"))
    job["company"] = job["company"].upper()
    job["title"] = job["title"].upper()
    write_json(job_path, job)

    result = render_application_draft(SLUG, repo_root=tmp_path, renderer=fake_renderer)

    assert result["visual_review_status"] == "required"


def test_render_uses_shared_renderer_and_requires_visual_review(tmp_path):
    setup_repository(tmp_path)

    result = render_application_draft(SLUG, repo_root=tmp_path, renderer=fake_renderer)

    assert result["visual_review_status"] == "required"
    assert len(result["actual_png_paths"]) == 2
    assert result["reviewed_pages_to_record"] == [
        f"application_materials/jobs/{SLUG}/output/CoverLetter-page-1.png",
        f"application_materials/jobs/{SLUG}/output/Resume-page-1.png",
    ]
    generation = json.loads(
        (
            tmp_path / "application_materials" / "work" / SLUG / "generation.json"
        ).read_text(encoding="utf-8")
    )
    assert generation["render"]["visual_review_required"] is True
    assert set(generation["render"]["source_hashes"]) == {
        "resume.yaml",
        "cover_letter.yaml",
        "evidence_matrix.md",
        "job.json",
        "payload.json",
        "candidate.yaml",
    }


def test_renderer_failure_becomes_a_draft_error(tmp_path):
    setup_repository(tmp_path)

    def failing_renderer(**_):
        raise RenderError("Rendering or output validation failed: boom")

    with pytest.raises(DraftError, match="renderer failed: .*boom"):
        render_application_draft(SLUG, repo_root=tmp_path, renderer=failing_renderer)


def test_renderer_input_failure_becomes_a_draft_input_error(tmp_path):
    setup_repository(tmp_path)

    def rejecting_renderer(**_):
        raise RenderInputError("Input validation failed", "bad resume")

    with pytest.raises(DraftError, match="Draft input validation failed: bad resume"):
        render_application_draft(SLUG, repo_root=tmp_path, renderer=rejecting_renderer)


def test_promotion_requires_explicit_approval(tmp_path):
    setup_repository(tmp_path)
    with pytest.raises(DraftError, match="approval"):
        promote_application_draft(SLUG, human_approved=False, repo_root=tmp_path)


def test_promotion_refuses_unrendered_draft(tmp_path):
    setup_repository(tmp_path)
    with pytest.raises(DraftError, match="validation.json"):
        promote_application_draft(SLUG, human_approved=True, repo_root=tmp_path)


def test_promotion_refuses_incomplete_visual_review(tmp_path):
    setup_repository(tmp_path)
    render_application_draft(SLUG, repo_root=tmp_path, renderer=fake_renderer)

    with pytest.raises(DraftError, match="visual_review.status"):
        promote_application_draft(SLUG, human_approved=True, repo_root=tmp_path)


def test_promotion_refuses_reviewed_page_mismatch(tmp_path):
    setup_repository(tmp_path)
    render_application_draft(SLUG, repo_root=tmp_path, renderer=fake_renderer)
    mark_review_passed(tmp_path)

    validation_path = (
        tmp_path
        / "application_materials"
        / "work"
        / SLUG
        / "output"
        / "validation.json"
    )
    validation = json.loads(validation_path.read_text(encoding="utf-8"))
    validation["visual_review"]["reviewed_pages"] = [
        f"application_materials/jobs/{SLUG}/output/Resume-page-1.png"
    ]
    write_json(validation_path, validation)

    with pytest.raises(DraftError, match="reviewed_pages exactly matches"):
        promote_application_draft(SLUG, human_approved=True, repo_root=tmp_path)


def test_promotion_refuses_stale_render(tmp_path):
    draft = setup_repository(tmp_path)
    render_application_draft(SLUG, repo_root=tmp_path, renderer=fake_renderer)
    mark_review_passed(tmp_path)
    resume_path = draft / "resume.yaml"
    resume = yaml.safe_load(resume_path.read_text(encoding="utf-8"))
    resume["summary"]["text"] = "Changed architecture leader"
    resume_path.write_text(yaml.safe_dump(resume, sort_keys=False), encoding="utf-8")

    payload_path = draft / "payload.json"
    payload = json.loads(payload_path.read_text(encoding="utf-8"))
    payload["resume"] = resume
    write_json(payload_path, payload)

    with pytest.raises(DraftError, match="changed after rendering"):
        promote_application_draft(SLUG, human_approved=True, repo_root=tmp_path)


def test_successful_promotion_is_atomic(tmp_path, monkeypatch):
    setup_repository(tmp_path)
    render_application_draft(SLUG, repo_root=tmp_path, renderer=fake_renderer)
    mark_review_passed(tmp_path)
    monkeypatch.setattr(promote_module, "check_package", lambda *_: True)

    destination = promote_application_draft(
        SLUG, human_approved=True, repo_root=tmp_path
    )

    assert destination == tmp_path / "application_materials" / "jobs" / SLUG
    assert destination.is_dir()
    assert not (tmp_path / "application_materials" / "work" / SLUG).exists()
    assert (destination / "output" / "Resume.pdf").is_file()


def test_promotion_checks_only_the_promoted_package(tmp_path, monkeypatch):
    setup_repository(tmp_path)
    render_application_draft(SLUG, repo_root=tmp_path, renderer=fake_renderer)
    mark_review_passed(tmp_path)
    checked = []

    monkeypatch.setattr(
        promote_module,
        "check_package",
        lambda package, *_: checked.append(package.name) or True,
    )

    promote_application_draft(SLUG, human_approved=True, repo_root=tmp_path)

    assert checked == [SLUG]


def test_policy_failure_rolls_back_to_work(tmp_path, monkeypatch):
    setup_repository(tmp_path)
    render_application_draft(SLUG, repo_root=tmp_path, renderer=fake_renderer)
    mark_review_passed(tmp_path)
    monkeypatch.setattr(promote_module, "check_package", lambda *_: False)

    with pytest.raises(DraftError, match="policy"):
        promote_application_draft(SLUG, human_approved=True, repo_root=tmp_path)

    assert (tmp_path / "application_materials" / "work" / SLUG).is_dir()
    assert not (tmp_path / "application_materials" / "jobs" / SLUG).exists()
