"""The application draft: one application package before it is promoted.

A draft is the Git-ignored directory ``application_materials/work/<slug>/``.
It goes through four stages: create (from a validated payload), render, a human
visual review, and promotion to ``application_materials/jobs/<slug>/``.

This module is the only place that knows the draft's file set, how to load it,
how to write it, and how to move it. Loading a draft always revalidates the
stored payload, so a stage cannot read a draft that the payload rules reject.

Rendering is not part of this module. The renderer needs WeasyPrint, so the
command-line tools run it and then call ``Draft.record_render``.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
from pathlib import Path
from typing import Any, Callable, Iterable, NamedTuple
from uuid import uuid4

import yaml

from applywright.models import Job

from .service import (
    ApplicationPackageValidationError,
    _render_evidence_matrix,
    _repo_root,
    collect_evidence_locations,
    validate_application_package_payload,
)

SOURCE_FILES = (
    "resume.yaml",
    "cover_letter.yaml",
    "evidence_matrix.md",
    "job.json",
    "payload.json",
)
REQUIRED_OUTPUT_FILES = frozenset(
    {
        "Resume.html",
        "Resume.pdf",
        "CoverLetter.html",
        "CoverLetter.pdf",
        "application.css",
        "validation.json",
    }
)
SLUG_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
PNG_PATTERN = re.compile(r"^(Resume|CoverLetter)-page-([1-9][0-9]*)\.png$")


class DraftError(ValueError):
    """Raised when a draft cannot be opened, rendered, or promoted safely."""


class ReviewFinding(NamedTuple):
    policy: str
    correction: str

    def __str__(self) -> str:
        return f"{self.policy}: {self.correction}"


class RenderRecord(NamedTuple):
    actual_png_paths: list[Path]
    reviewed_pages_to_record: list[str]


def validate_slug(slug: str) -> str:
    slug = slug.strip()
    if not SLUG_PATTERN.fullmatch(slug):
        raise DraftError(
            "Slug must contain only lowercase letters, numbers, and single hyphens"
        )
    return slug


def review_findings(
    slug: str,
    validation: dict[str, Any],
    output_file_names: Iterable[str],
) -> list[ReviewFinding]:
    """Apply the visual-review rule to one ``output/validation.json``.

    The rule is the same for a draft that is about to be promoted and for a
    package that is already in ``jobs/``. An empty list means the review passed.
    """
    findings: list[ReviewFinding] = []

    automated = validation.get("automated_validation")
    if not isinstance(automated, dict) or automated.get("passed") is not True:
        findings.append(
            ReviewFinding(
                "automated_validation.passed is true",
                "Fix validation errors and rerender",
            )
        )

    visual = validation.get("visual_review")
    if not isinstance(visual, dict):
        visual = {}
    if visual.get("status") != "passed":
        findings.append(
            ReviewFinding(
                "visual_review.status is passed",
                "Open every final PNG and record the completed review",
            )
        )

    reviewed = visual.get("reviewed_pages")
    if not isinstance(reviewed, list):
        findings.append(
            ReviewFinding(
                "visual_review.reviewed_pages is a list",
                "Record the final repository-relative PNG paths as a list",
            )
        )
        return findings

    prefix = f"application_materials/jobs/{slug}/output/"
    expected = {
        f"{prefix}{name}" for name in output_file_names if PNG_PATTERN.fullmatch(name)
    }
    recorded = {page for page in reviewed if isinstance(page, str)}
    if recorded != expected or len(recorded) != len(reviewed):
        findings.append(
            ReviewFinding(
                "reviewed_pages exactly matches every final PNG",
                "Record all and only the final repository-relative PNG paths",
            )
        )
    for page in reviewed:
        if not isinstance(page, str) or not page.startswith(prefix):
            findings.append(
                ReviewFinding(
                    "reviewed pages remain inside the job output directory",
                    f"Correct reviewed page path {page!r}",
                )
            )
    return findings


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise DraftError(f"Could not load {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise DraftError(f"Expected a JSON object in {path}")
    return value


def _load_yaml(path: Path) -> dict[str, Any]:
    try:
        value = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception as exc:
        raise DraftError(f"Could not load {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise DraftError(f"Expected a YAML object in {path}")
    return value


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _source_hashes(draft_dir: Path, candidate_path: Path) -> dict[str, str]:
    """Hash every file that the renderer reads, including the shared candidate."""
    hashes: dict[str, str] = {}
    for filename in SOURCE_FILES:
        path = draft_dir / filename
        if not path.is_file():
            raise DraftError(f"Required draft source is missing: {path}")
        hashes[filename] = _sha256(path)
    if not candidate_path.is_file():
        raise DraftError(f"Required draft source is missing: {candidate_path}")
    hashes[candidate_path.name] = _sha256(candidate_path)
    return hashes


def _png_names(output_dir: Path) -> list[str]:
    if not output_dir.is_dir():
        return []
    return sorted(
        path.name
        for path in output_dir.iterdir()
        if path.is_file() and PNG_PATTERN.fullmatch(path.name)
    )


def _replace_directory(
    staging: Path,
    destination: Path,
    backup: Path,
    *,
    after_swap: Callable[[], None] | None = None,
) -> None:
    """Move ``staging`` to ``destination``. Restore the old directory on failure.

    The previous ``destination`` is kept as ``backup`` until ``after_swap`` has
    succeeded, so a failure in either step leaves the old directory in place.
    """
    swapped = False
    try:
        if destination.exists():
            destination.rename(backup)
        staging.rename(destination)
        swapped = True
        if after_swap is not None:
            after_swap()
        if backup.exists():
            shutil.rmtree(backup)
    except Exception:
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)
        if swapped and destination.exists():
            shutil.rmtree(destination, ignore_errors=True)
        if backup.exists():
            backup.rename(destination)
        raise


def _draft_files(job: Job, validated: Any) -> dict[str, str]:
    """Every file of a new draft, as text. ``payload.json`` is one of them."""

    def dump_yaml(data: Any) -> str:
        return yaml.safe_dump(data, sort_keys=False, allow_unicode=True)

    def dump_json(data: Any) -> str:
        return json.dumps(data, indent=2, sort_keys=True) + "\n"

    evidence_locations = {
        evidence_id: sorted(locations)
        for evidence_id, locations in collect_evidence_locations(validated).items()
    }
    cover_letter = validated.cover_letter
    return {
        "resume.yaml": dump_yaml(validated.resume.model_dump(mode="python")),
        "cover_letter.yaml": dump_yaml(
            {
                "company_name": cover_letter.company_name,
                "position": cover_letter.position,
                "paragraphs": [paragraph.text for paragraph in cover_letter.paragraphs],
            }
        ),
        "evidence_matrix.md": _render_evidence_matrix(validated),
        "job.json": dump_json(job.model_dump(mode="json")),
        "payload.json": dump_json(validated.model_dump(mode="json")),
        "generation.json": dump_json(
            {
                "job_id": validated.job_id,
                "job_slug": validated.job_slug,
                "automated_validation": {"passed": True},
                "human_approval": True,
                "target_profile": validated.target_profile.model_dump(mode="json"),
                "cover_letter_evidence": [
                    {"paragraph": index, "evidence_ids": paragraph.evidence_ids}
                    for index, paragraph in enumerate(cover_letter.paragraphs, start=1)
                ],
                "evidence_locations": evidence_locations,
                "evidence_matrix": [
                    row.model_dump(mode="json") for row in validated.evidence_matrix
                ],
                "unsupported_requirements": validated.unsupported_requirements,
                "uncertainties": validated.uncertainties,
                "generation_notes": validated.generation_notes,
            }
        ),
    }


class Draft:
    """A draft that has been loaded and found consistent with its payload."""

    def __init__(
        self,
        slug: str,
        root: Path,
        source_hashes: dict[str, str],
    ) -> None:
        self.slug = slug
        self.root = root
        self.application_root = root / "application_materials"
        self.path = self.application_root / "work" / slug
        self.output_dir = self.path / "output"
        self.candidate_path = self.application_root / "candidate.yaml"
        self.resume_path = self.path / "resume.yaml"
        self.cover_letter_path = self.path / "cover_letter.yaml"
        self._source_hashes = source_hashes

    @classmethod
    def create(
        cls,
        job: Job,
        payload: dict[str, Any] | Any,
        *,
        human_approved: bool,
        replace_existing: bool = False,
        repo_root: Path | str | None = None,
    ) -> "Draft":
        """Write a new draft from a payload. The draft is complete or absent."""
        if human_approved is not True:
            raise ApplicationPackageValidationError(
                "Explicit human approval is required before materializing a draft"
            )

        root = _repo_root(repo_root)
        validated = validate_application_package_payload(job, payload, root)

        work_root = root / "application_materials" / "work"
        work_root.mkdir(parents=True, exist_ok=True)
        destination = work_root / validated.job_slug
        if destination.exists() and not replace_existing:
            raise ApplicationPackageValidationError(
                f"Draft already exists and replacement was not approved: {destination}"
            )

        staging = work_root / f".{validated.job_slug}.staging-{uuid4().hex}"
        backup = work_root / f".{validated.job_slug}.backup-{uuid4().hex}"
        staging.mkdir(parents=False, exist_ok=False)
        try:
            for name, text in _draft_files(job, validated).items():
                (staging / name).write_text(text, encoding="utf-8")
        except Exception:
            shutil.rmtree(staging, ignore_errors=True)
            raise
        _replace_directory(staging, destination, backup)

        return cls.open(validated.job_slug, root)

    @classmethod
    def open(cls, slug: str, repo_root: Path | str | None = None) -> "Draft":
        """Load a draft. Fails unless the stored files agree with the payload."""
        slug = validate_slug(slug)
        root = _repo_root(repo_root)
        path = root / "application_materials" / "work" / slug
        if not path.is_dir():
            raise DraftError(f"Application draft does not exist: {path}")

        payload = _load_json(path / "payload.json")
        job_data = _load_json(path / "job.json")
        generation = _load_json(path / "generation.json")
        resume_yaml = _load_yaml(path / "resume.yaml")
        cover_yaml = _load_yaml(path / "cover_letter.yaml")

        try:
            # Job validation normalizes its input in place, so validate a copy.
            job = Job.model_validate(dict(job_data))
        except Exception as exc:
            raise DraftError(f"Stored job.json is not a valid job: {exc}") from exc
        try:
            validate_application_package_payload(job, payload, root)
        except ApplicationPackageValidationError as exc:
            raise DraftError(str(exc)) from exc

        # The payload is valid. The checks below compare the stored files with it.
        if payload["job_slug"] != slug:
            raise DraftError("Stored payload slug does not match draft path")
        if generation.get("job_slug") != slug:
            raise DraftError("generation.json slug does not match")
        if generation.get("job_id") != job.job_id:
            raise DraftError("Stored job IDs do not match")
        if generation.get("target_profile") != payload["target_profile"]:
            raise DraftError(
                "generation.json target_profile does not match payload.json target_profile"
            )
        if payload["resume"] != resume_yaml:
            raise DraftError("resume.yaml no longer matches payload.json")
        cover = payload["cover_letter"]
        expected_cover_yaml = {
            "company_name": cover["company_name"],
            "position": cover["position"],
            "paragraphs": [paragraph["text"] for paragraph in cover["paragraphs"]],
        }
        if expected_cover_yaml != cover_yaml:
            raise DraftError("cover_letter.yaml no longer matches payload.json")

        candidate_path = root / "application_materials" / "candidate.yaml"
        return cls(slug, root, _source_hashes(path, candidate_path))

    def record_render(self) -> RenderRecord:
        """Record a finished render in ``generation.json``.

        The source hashes are those taken when the draft was opened, so a source
        file that changes during rendering is detected at promotion.
        """
        names = _png_names(self.output_dir)
        if not names:
            raise DraftError("The renderer did not produce any PNG pages")
        actual = [self.output_dir / name for name in names]
        final = [
            f"application_materials/jobs/{self.slug}/output/{name}" for name in names
        ]

        generation_path = self.path / "generation.json"
        generation = _load_json(generation_path)
        generation["render"] = {
            "source_hashes": self._source_hashes,
            "actual_png_paths": [str(path.relative_to(self.root)) for path in actual],
            "final_review_paths": final,
            "visual_review_required": True,
        }
        _write_json(generation_path, generation)
        return RenderRecord(actual, final)

    def promote(
        self,
        *,
        human_approved: bool,
        replace_existing: bool = False,
        verify_package: Callable[[Path], bool] | None = None,
    ) -> Path:
        """Move a rendered and reviewed draft to ``jobs/<slug>/``.

        ``verify_package`` receives the provisionally promoted package. If it
        returns false, the draft and any previous package are restored.
        """
        if human_approved is not True:
            raise DraftError(
                "Explicit human approval is required before promoting a draft"
            )

        jobs_root = self.application_root / "jobs"
        destination = jobs_root / self.slug
        if destination.exists() and not replace_existing:
            raise DraftError(
                f"Final package already exists and replacement was not approved: {destination}"
            )

        validation = _load_json(self.output_dir / "validation.json")
        self._require_reviewed_render(validation)

        jobs_root.mkdir(parents=True, exist_ok=True)
        staging = self.application_root / f".{self.slug}.promotion-{uuid4().hex}"
        backup = self.application_root / f".{self.slug}.backup-{uuid4().hex}"
        shutil.copytree(self.path, staging)

        def verify_then_remove_draft() -> None:
            if verify_package is not None and not verify_package(destination):
                raise DraftError(
                    "Repository policy checks failed after provisional promotion"
                )
            shutil.rmtree(self.path)

        _replace_directory(
            staging, destination, backup, after_swap=verify_then_remove_draft
        )
        return destination

    def _require_reviewed_render(self, validation: dict[str, Any]) -> None:
        generation = _load_json(self.path / "generation.json")
        render_state = generation.get("render")
        if not isinstance(render_state, dict):
            raise DraftError("Draft has not been rendered")

        recorded_hashes = render_state.get("source_hashes")
        if not isinstance(recorded_hashes, dict):
            raise DraftError("Rendered source hashes are missing")
        if recorded_hashes != _source_hashes(self.path, self.candidate_path):
            raise DraftError(
                "Draft sources changed after rendering; rerender before promotion"
            )

        names = _png_names(self.output_dir)
        if not names:
            raise DraftError("No rendered PNG pages were found")

        findings = review_findings(self.slug, validation, names)
        if findings:
            raise DraftError("; ".join(str(finding) for finding in findings))

        expected = [
            f"application_materials/jobs/{self.slug}/output/{name}" for name in names
        ]
        if sorted(render_state.get("final_review_paths") or []) != expected:
            raise DraftError(
                "generation.json final review paths do not match rendered PNGs"
            )

        output_names = {p.name for p in self.output_dir.iterdir() if p.is_file()}
        missing = sorted(REQUIRED_OUTPUT_FILES - output_names)
        if missing:
            raise DraftError(
                f"Required rendered output is missing: {', '.join(missing)}"
            )
