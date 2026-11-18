"""The draft module: create, open, record a render, review, and promote."""

import json

import pytest

from applywright.application_packages import (
    ApplicationPackageValidationError,
    Draft,
    DraftError,
    expected_job_slug,
    review_findings,
)
from applywright.application_packages import draft as draft_module
from test_application_packages import make_job, make_payload, write_candidate

OUTPUT_FILES = (
    "Resume.html",
    "Resume.pdf",
    "CoverLetter.html",
    "CoverLetter.pdf",
    "application.css",
)


def create_draft(tmp_path, **overrides):
    write_candidate(tmp_path)
    job = make_job()
    payload = make_payload(job)
    draft = Draft.create(
        job, payload, human_approved=True, repo_root=tmp_path, **overrides
    )
    return job, payload, draft


def fake_render(draft):
    """Stand in for the renderer: write the output files a render produces."""
    draft.output_dir.mkdir(exist_ok=True)
    for name in OUTPUT_FILES:
        (draft.output_dir / name).write_text("generated", encoding="utf-8")
    (draft.output_dir / "Resume-page-1.png").write_bytes(b"resume")
    (draft.output_dir / "CoverLetter-page-1.png").write_bytes(b"cover")
    (draft.output_dir / "validation.json").write_text(
        json.dumps(
            {
                "automated_validation": {"passed": True},
                "visual_review": {"status": "required", "reviewed_pages": []},
            }
        ),
        encoding="utf-8",
    )
    return draft.record_render()


def pass_review(draft):
    path = draft.output_dir / "validation.json"
    validation = json.loads(path.read_text(encoding="utf-8"))
    validation["visual_review"] = {
        "status": "passed",
        "reviewed_pages": [
            f"application_materials/jobs/{draft.slug}/output/CoverLetter-page-1.png",
            f"application_materials/jobs/{draft.slug}/output/Resume-page-1.png",
        ],
    }
    path.write_text(json.dumps(validation), encoding="utf-8")


def test_create_writes_a_complete_draft_that_opens(tmp_path):
    job, _, draft = create_draft(tmp_path)

    assert draft.slug == expected_job_slug(job)
    for name in draft_module.SOURCE_FILES + ("generation.json",):
        assert (draft.path / name).is_file()
    assert Draft.open(draft.slug, tmp_path).path == draft.path


def test_create_writes_exactly_the_draft_files_and_leaves_no_staging(tmp_path):
    _, _, draft = create_draft(tmp_path)

    assert sorted(path.name for path in draft.path.iterdir()) == [
        "cover_letter.yaml",
        "evidence_matrix.md",
        "generation.json",
        "job.json",
        "payload.json",
        "resume.yaml",
    ]
    generation = json.loads((draft.path / "generation.json").read_text("utf-8"))
    assert generation["automated_validation"]["passed"] is True
    assert generation["human_approval"] is True
    assert not list(draft.path.parent.glob(".*.staging-*"))


def test_create_replaces_only_when_explicit(tmp_path):
    job, payload, draft = create_draft(tmp_path)
    (draft.path / "obsolete.txt").write_text("old")

    replaced = Draft.create(
        job, payload, human_approved=True, replace_existing=True, repo_root=tmp_path
    )

    assert replaced.path == draft.path
    assert not (draft.path / "obsolete.txt").exists()


def test_create_requires_human_approval(tmp_path):
    write_candidate(tmp_path)
    job = make_job()
    with pytest.raises(ApplicationPackageValidationError, match="approval"):
        Draft.create(job, make_payload(job), human_approved=False, repo_root=tmp_path)


def test_create_refuses_silent_overwrite(tmp_path):
    job, payload, _ = create_draft(tmp_path)
    with pytest.raises(ApplicationPackageValidationError, match="already exists"):
        Draft.create(job, payload, human_approved=True, repo_root=tmp_path)


def test_failed_create_leaves_no_draft_and_no_staging(tmp_path, monkeypatch):
    write_candidate(tmp_path)
    job = make_job()
    payload = make_payload(job)

    def fail(*_):
        raise RuntimeError("disk full")

    monkeypatch.setattr(draft_module, "_draft_files", fail)
    with pytest.raises(RuntimeError):
        Draft.create(job, payload, human_approved=True, repo_root=tmp_path)

    work = tmp_path / "application_materials" / "work"
    assert list(work.iterdir()) == []


def test_failed_replacement_keeps_the_previous_draft(tmp_path, monkeypatch):
    job, payload, draft = create_draft(tmp_path)
    before = (draft.path / "payload.json").read_text(encoding="utf-8")

    monkeypatch.setattr(
        draft_module, "_draft_files", lambda *_: (_ for _ in ()).throw(OSError("x"))
    )
    with pytest.raises(OSError):
        Draft.create(
            job,
            payload,
            human_approved=True,
            replace_existing=True,
            repo_root=tmp_path,
        )

    assert (draft.path / "payload.json").read_text(encoding="utf-8") == before


def test_open_rejects_a_missing_draft(tmp_path):
    write_candidate(tmp_path)
    with pytest.raises(DraftError, match="does not exist"):
        Draft.open("missing-1", tmp_path)


def test_open_rejects_a_missing_payload(tmp_path):
    _, _, draft = create_draft(tmp_path)
    (draft.path / "payload.json").unlink()
    with pytest.raises(DraftError, match="payload.json"):
        Draft.open(draft.slug, tmp_path)


def test_open_revalidates_the_stored_payload(tmp_path):
    _, _, draft = create_draft(tmp_path)
    path = draft.path / "payload.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    del payload["target_profile"]
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(DraftError, match="required schema"):
        Draft.open(draft.slug, tmp_path)


def test_open_rejects_a_resume_that_no_longer_matches_the_payload(tmp_path):
    _, _, draft = create_draft(tmp_path)
    resume = draft.resume_path
    resume.write_text(
        resume.read_text(encoding="utf-8").replace("Terraform", "Changed"),
        encoding="utf-8",
    )
    with pytest.raises(DraftError, match="resume.yaml no longer matches"):
        Draft.open(draft.slug, tmp_path)


def test_open_rejects_a_generation_target_profile_mismatch(tmp_path):
    _, _, draft = create_draft(tmp_path)
    path = draft.path / "generation.json"
    generation = json.loads(path.read_text(encoding="utf-8"))
    generation["target_profile"]["professional_identity"] = "Mismatch"
    path.write_text(json.dumps(generation), encoding="utf-8")
    with pytest.raises(DraftError, match="target_profile does not match"):
        Draft.open(draft.slug, tmp_path)


def test_open_accepts_cover_letter_identity_that_differs_only_by_case(tmp_path):
    _, _, draft = create_draft(tmp_path)
    path = draft.path / "job.json"
    job = json.loads(path.read_text(encoding="utf-8"))
    job["company"] = job["company"].upper()
    path.write_text(json.dumps(job), encoding="utf-8")
    Draft.open(draft.slug, tmp_path)


def test_record_render_stores_hashes_and_returns_review_paths(tmp_path):
    _, _, draft = create_draft(tmp_path)
    record = fake_render(draft)

    assert record.reviewed_pages_to_record == [
        f"application_materials/jobs/{draft.slug}/output/CoverLetter-page-1.png",
        f"application_materials/jobs/{draft.slug}/output/Resume-page-1.png",
    ]
    generation = json.loads((draft.path / "generation.json").read_text("utf-8"))
    assert set(generation["render"]["source_hashes"]) == {
        *draft_module.SOURCE_FILES,
        "candidate.yaml",
    }
    assert generation["render"]["visual_review_required"] is True


def test_record_render_requires_page_images(tmp_path):
    _, _, draft = create_draft(tmp_path)
    with pytest.raises(DraftError, match="PNG"):
        draft.record_render()


def test_promote_requires_human_approval(tmp_path):
    _, _, draft = create_draft(tmp_path)
    with pytest.raises(DraftError, match="approval"):
        draft.promote(human_approved=False)


def test_promote_refuses_an_unrendered_draft(tmp_path):
    _, _, draft = create_draft(tmp_path)
    with pytest.raises(DraftError, match="validation.json"):
        draft.promote(human_approved=True)


def test_promote_refuses_an_unreviewed_render(tmp_path):
    _, _, draft = create_draft(tmp_path)
    fake_render(draft)
    with pytest.raises(DraftError, match="visual_review.status"):
        draft.promote(human_approved=True)


def test_promote_refuses_a_page_list_that_misses_a_page(tmp_path):
    _, _, draft = create_draft(tmp_path)
    fake_render(draft)
    pass_review(draft)
    path = draft.output_dir / "validation.json"
    validation = json.loads(path.read_text(encoding="utf-8"))
    validation["visual_review"]["reviewed_pages"].pop()
    path.write_text(json.dumps(validation), encoding="utf-8")
    with pytest.raises(DraftError, match="reviewed_pages exactly matches"):
        draft.promote(human_approved=True)


def test_promote_refuses_sources_changed_after_render(tmp_path):
    _, _, draft = create_draft(tmp_path)
    fake_render(draft)
    pass_review(draft)
    (draft.path / "evidence_matrix.md").write_text("changed", encoding="utf-8")
    with pytest.raises(DraftError, match="changed after rendering"):
        draft.promote(human_approved=True)


def test_promote_refuses_a_candidate_changed_after_render(tmp_path):
    """The rendered documents show the candidate's contact data."""
    _, _, draft = create_draft(tmp_path)
    fake_render(draft)
    pass_review(draft)
    candidate = draft.candidate_path
    candidate.write_text(
        candidate.read_text(encoding="utf-8").replace(
            "candidate@example.com", "new@example.com"
        ),
        encoding="utf-8",
    )
    with pytest.raises(DraftError, match="changed after rendering"):
        draft.promote(human_approved=True)


def test_promote_moves_the_draft_and_checks_the_package(tmp_path):
    _, _, draft = create_draft(tmp_path)
    fake_render(draft)
    pass_review(draft)
    seen = []

    destination = draft.promote(
        human_approved=True, verify_package=lambda path: seen.append(path) or True
    )

    assert destination == tmp_path / "application_materials" / "jobs" / draft.slug
    assert seen == [destination]
    assert (destination / "output" / "Resume.pdf").is_file()
    assert not draft.path.exists()


def test_failed_package_check_rolls_back_to_the_draft(tmp_path):
    _, _, draft = create_draft(tmp_path)
    fake_render(draft)
    pass_review(draft)

    with pytest.raises(DraftError, match="policy"):
        draft.promote(human_approved=True, verify_package=lambda _: False)

    assert draft.path.is_dir()
    assert not (draft.application_root / "jobs" / draft.slug).exists()


def test_failed_package_check_restores_the_previous_package(tmp_path):
    _, _, draft = create_draft(tmp_path)
    previous = draft.application_root / "jobs" / draft.slug
    previous.mkdir(parents=True)
    (previous / "keep.txt").write_text("previous", encoding="utf-8")
    fake_render(draft)
    pass_review(draft)

    with pytest.raises(DraftError, match="policy"):
        draft.promote(
            human_approved=True, replace_existing=True, verify_package=lambda _: False
        )

    assert (previous / "keep.txt").read_text(encoding="utf-8") == "previous"
    assert draft.path.is_dir()


def test_promote_refuses_to_replace_without_approval(tmp_path):
    _, _, draft = create_draft(tmp_path)
    (draft.application_root / "jobs" / draft.slug).mkdir(parents=True)
    fake_render(draft)
    pass_review(draft)
    with pytest.raises(DraftError, match="replacement was not approved"):
        draft.promote(human_approved=True)


def test_review_findings_pass_for_a_complete_review():
    validation = {
        "automated_validation": {"passed": True},
        "visual_review": {
            "status": "passed",
            "reviewed_pages": [
                "application_materials/jobs/x-1/output/Resume-page-1.png"
            ],
        },
    }
    assert review_findings("x-1", validation, ["Resume-page-1.png", "Resume.pdf"]) == []


@pytest.mark.parametrize(
    "validation, expected",
    [
        ({}, "automated_validation.passed"),
        (
            {"automated_validation": {"passed": True}, "visual_review": {}},
            "visual_review.status",
        ),
        (
            {
                "automated_validation": {"passed": True},
                "visual_review": {"status": "passed", "reviewed_pages": "no"},
            },
            "reviewed_pages is a list",
        ),
        (
            {
                "automated_validation": {"passed": True},
                "visual_review": {
                    "status": "passed",
                    "reviewed_pages": ["elsewhere/Resume-page-1.png"],
                },
            },
            "inside the job output directory",
        ),
    ],
)
def test_review_findings_report_each_failure(validation, expected):
    findings = review_findings("x-1", validation, ["Resume-page-1.png"])
    assert any(expected in str(finding) for finding in findings)
