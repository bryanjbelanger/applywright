from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from applywright.models import Job

PLACEHOLDER_PATTERN = re.compile(
    r"(?:\[|\]|<|>|\bTODO\b|\bTBD\b|\bPLACEHOLDER\b)", re.IGNORECASE
)
SLUG_COMPONENT_PATTERN = re.compile(r"[^a-z0-9]+")


def same_identity(payload_value: str, stored_value: str) -> bool:
    """Compare a cover-letter identity field to the stored job.

    Case and whitespace are normalized because JobCopilot title-cases the names
    it serves (for example "Examplecorp" for "ExampleCorp"), and a cover letter must be
    free to spell the employer the way the employer does. The check still
    catches the failure it exists for: a letter addressed to a different
    company or role than the one being applied to.
    """
    return (
        " ".join((payload_value or "").split()).casefold()
        == " ".join((stored_value or "").split()).casefold()
    )


class ApplicationPackageValidationError(ValueError):
    """Raised when an application package fails deterministic validation."""


class EvidenceClaim(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1)
    evidence_ids: list[str] = Field(min_length=1)

    @field_validator("text")
    @classmethod
    def strip_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("text cannot be blank")
        return value

    @field_validator("evidence_ids")
    @classmethod
    def validate_evidence_ids(cls, values: list[str]) -> list[str]:
        normalized = [value.strip() for value in values]
        if any(not value for value in normalized):
            raise ValueError("evidence IDs cannot be blank")
        if len(normalized) != len(set(normalized)):
            raise ValueError("evidence IDs must be unique within a claim")
        return normalized


class ResumeEngagement(BaseModel):
    model_config = ConfigDict(extra="forbid")

    client: str = Field(min_length=1)
    overview: EvidenceClaim | None = None
    achievements: list[EvidenceClaim] = Field(default_factory=list)

    @field_validator("client")
    @classmethod
    def strip_client(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("client cannot be blank")
        return value

    @model_validator(mode="after")
    def require_content(self) -> "ResumeEngagement":
        if self.overview is None and not self.achievements:
            raise ValueError(
                "an engagement requires an overview or at least one achievement"
            )
        return self


class ResumeExperience(BaseModel):
    model_config = ConfigDict(extra="forbid")

    employer: str = Field(min_length=1)
    title: str = Field(min_length=1)
    start_year: str = Field(pattern=r"^[0-9]{4}$")
    end_year: str = Field(pattern=r"^([0-9]{4}|Present)$")
    overview: EvidenceClaim
    engagements: list[ResumeEngagement] = Field(min_length=1)

    @field_validator("employer", "title")
    @classmethod
    def strip_required_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("experience text cannot be blank")
        return value

    @model_validator(mode="after")
    def validate_chronology(self) -> "ResumeExperience":
        if self.end_year != "Present" and self.end_year < self.start_year:
            raise ValueError("end_year cannot be before start_year")
        return self


class ResumeDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    summary: EvidenceClaim
    core_skills: list[EvidenceClaim] = Field(min_length=1)
    experience: list[ResumeExperience] = Field(min_length=1)


class CoverLetterParagraph(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1)
    evidence_ids: list[str] = Field(min_length=1)

    @field_validator("text")
    @classmethod
    def strip_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("cover-letter paragraph cannot be blank")
        return value

    @field_validator("evidence_ids")
    @classmethod
    def validate_evidence_ids(cls, values: list[str]) -> list[str]:
        normalized = [value.strip() for value in values]
        if any(not value for value in normalized):
            raise ValueError("cover-letter evidence IDs cannot be blank")
        if len(normalized) != len(set(normalized)):
            raise ValueError(
                "cover-letter evidence IDs must be unique within a paragraph"
            )
        return normalized


class CoverLetterDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    company_name: str = Field(min_length=1)
    position: str = Field(min_length=1)
    paragraphs: list[CoverLetterParagraph] = Field(min_length=1)

    @field_validator("company_name", "position")
    @classmethod
    def strip_required_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("cover-letter metadata cannot be blank")
        return value


class EvidenceMatrixRow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    evidence_id: str = Field(min_length=1)
    canonical_evidence: str = Field(min_length=1)
    requirement: str = Field(min_length=1)
    strength: Literal["strong", "moderate", "weak"]
    used_in: list[str] = Field(min_length=1)
    notes: str = ""

    @field_validator("evidence_id", "canonical_evidence", "requirement")
    @classmethod
    def strip_required_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("evidence-matrix text cannot be blank")
        return value

    @field_validator("used_in")
    @classmethod
    def validate_used_in(cls, values: list[str]) -> list[str]:
        normalized = [value.strip() for value in values]
        if any(not value for value in normalized):
            raise ValueError("used_in entries cannot be blank")
        if len(normalized) != len(set(normalized)):
            raise ValueError("used_in entries must be unique")
        return normalized


class TargetProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role_family: str = Field(min_length=1)
    professional_identity: str = Field(min_length=1)
    emphasis: list[str] = Field(min_length=1)
    deemphasized: list[str] = Field(default_factory=list)
    rationale: str = Field(min_length=1)

    @field_validator("role_family", "professional_identity", "rationale")
    @classmethod
    def strip_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("text cannot be blank")
        return value

    @field_validator("emphasis", "deemphasized")
    @classmethod
    def validate_lists(cls, values: list[str]) -> list[str]:
        normalized = [value.strip() for value in values]
        if any(not value for value in normalized):
            raise ValueError("list entries cannot be blank")
        if len(normalized) != len(set(normalized)):
            raise ValueError("list entries must be unique")
        return normalized


class ApplicationPackagePayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job_id: str = Field(min_length=1)
    job_slug: str = Field(pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
    target_profile: TargetProfile
    resume: ResumeDraft
    cover_letter: CoverLetterDraft
    evidence_matrix: list[EvidenceMatrixRow] = Field(min_length=1)
    unsupported_requirements: list[str] = Field(default_factory=list)
    uncertainties: list[str] = Field(default_factory=list)
    generation_notes: list[str] = Field(default_factory=list)

    @field_validator("job_id")
    @classmethod
    def strip_job_id(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("job_id cannot be blank")
        return value

    @field_validator("unsupported_requirements", "uncertainties", "generation_notes")
    @classmethod
    def strip_list_text(cls, values: list[str]) -> list[str]:
        normalized = [value.strip() for value in values]
        if any(not value for value in normalized):
            raise ValueError("list entries cannot be blank")
        return normalized


def _repo_root(repo_root: Path | str | None = None) -> Path:
    if repo_root is not None:
        return Path(repo_root).resolve()
    configured = os.environ.get("APPLYWRIGHT_ROOT")
    if configured:
        return Path(configured).resolve()
    return Path(__file__).resolve().parents[3]


def _slug_component(value: str) -> str:
    normalized = SLUG_COMPONENT_PATTERN.sub("-", value.lower()).strip("-")
    return normalized or "job"


def expected_job_slug(job: Job) -> str:
    identifier = job.external_id or job.job_id
    return f"{_slug_component(job.company)}-{_slug_component(identifier)}"


def load_candidate_catalog(repo_root: Path | str | None = None) -> dict[str, str]:
    root = _repo_root(repo_root)
    candidate_path = root / "application_materials" / "candidate.yaml"
    if not candidate_path.is_file():
        raise ApplicationPackageValidationError(
            f"Canonical candidate file is missing: {candidate_path}"
        )

    try:
        data = yaml.safe_load(candidate_path.read_text(encoding="utf-8")) or {}
    except Exception as exc:
        raise ApplicationPackageValidationError(
            f"Canonical candidate file could not be loaded: {exc}"
        ) from exc

    if not isinstance(data, dict):
        raise ApplicationPackageValidationError(
            "Canonical candidate file must contain a mapping"
        )
    catalog = data.get("evidence_catalog")
    if not isinstance(catalog, dict) or not catalog:
        raise ApplicationPackageValidationError("Canonical evidence catalog is empty")

    normalized: dict[str, str] = {}
    for raw_id, raw_text in catalog.items():
        if not isinstance(raw_id, str) or not isinstance(raw_text, str):
            raise ApplicationPackageValidationError(
                "Canonical evidence catalog IDs and claims must be strings"
            )
        evidence_id = raw_id.strip()
        evidence_text = raw_text.strip()
        if not evidence_id or not evidence_text:
            raise ApplicationPackageValidationError(
                "Canonical evidence catalog contains a blank ID or claim"
            )
        normalized[evidence_id] = evidence_text
    return normalized


def _resume_evidence_locations(resume: ResumeDraft) -> dict[str, set[str]]:
    locations: dict[str, set[str]] = {}

    def add(ids: list[str], location: str) -> None:
        for evidence_id in ids:
            locations.setdefault(evidence_id, set()).add(location)

    add(resume.summary.evidence_ids, "Resume Summary")
    for index, skill in enumerate(resume.core_skills, start=1):
        add(skill.evidence_ids, f"Resume Skill {index}")
    for experience in resume.experience:
        add(experience.overview.evidence_ids, f"{experience.employer} Overview")
        for engagement in experience.engagements:
            if engagement.overview is not None:
                add(
                    engagement.overview.evidence_ids,
                    f"{experience.employer} / {engagement.client} Overview",
                )
            for achievement_index, achievement in enumerate(
                engagement.achievements, start=1
            ):
                add(
                    achievement.evidence_ids,
                    f"{experience.employer} / {engagement.client} Achievement {achievement_index}",
                )
    return locations


def collect_evidence_locations(
    payload: ApplicationPackagePayload,
) -> dict[str, set[str]]:
    locations = _resume_evidence_locations(payload.resume)
    for paragraph_index, paragraph in enumerate(
        payload.cover_letter.paragraphs, start=1
    ):
        for evidence_id in paragraph.evidence_ids:
            locations.setdefault(evidence_id, set()).add(
                f"Cover Letter Paragraph {paragraph_index}"
            )
    return locations


def _iter_visible_text(payload: ApplicationPackagePayload) -> list[str]:
    values = [
        payload.cover_letter.company_name,
        payload.cover_letter.position,
        payload.resume.summary.text,
    ]
    values.extend(skill.text for skill in payload.resume.core_skills)
    for experience in payload.resume.experience:
        values.extend(
            [
                experience.employer,
                experience.title,
                experience.overview.text,
            ]
        )
        for engagement in experience.engagements:
            values.append(engagement.client)
            if engagement.overview is not None:
                values.append(engagement.overview.text)
            values.extend(item.text for item in engagement.achievements)
    values.extend(paragraph.text for paragraph in payload.cover_letter.paragraphs)
    return values


def validate_application_package_payload(
    job: Job,
    payload: dict[str, Any] | ApplicationPackagePayload,
    repo_root: Path | str | None = None,
) -> ApplicationPackagePayload:
    if not job.description or not job.description.strip():
        raise ApplicationPackageValidationError(
            "The stored job description is missing or blank"
        )

    try:
        validated = (
            payload
            if isinstance(payload, ApplicationPackagePayload)
            else ApplicationPackagePayload.model_validate(payload)
        )
    except Exception as exc:
        raise ApplicationPackageValidationError(
            f"Application package payload does not match the required schema: {exc}"
        ) from exc

    if validated.job_id != job.job_id:
        raise ApplicationPackageValidationError(
            "Payload job_id does not match the stored job"
        )

    expected_slug = expected_job_slug(job)
    if validated.job_slug != expected_slug:
        raise ApplicationPackageValidationError(
            f"Payload job_slug must be {expected_slug}"
        )

    if not same_identity(validated.cover_letter.company_name, job.company):
        raise ApplicationPackageValidationError(
            "Cover-letter company_name does not match the stored job"
        )
    if not same_identity(validated.cover_letter.position, job.title):
        raise ApplicationPackageValidationError(
            "Cover-letter position does not match the stored job"
        )

    for visible_text in _iter_visible_text(validated):
        if PLACEHOLDER_PATTERN.search(visible_text):
            raise ApplicationPackageValidationError(
                f"Placeholder or template marker found in visible text: {visible_text}"
            )

    catalog = load_candidate_catalog(repo_root)
    evidence_locations = collect_evidence_locations(validated)
    used_ids = set(evidence_locations)

    unknown_ids = sorted(used_ids - set(catalog))
    if unknown_ids:
        raise ApplicationPackageValidationError(
            f"Unknown evidence IDs: {', '.join(unknown_ids)}"
        )

    row_ids = [row.evidence_id for row in validated.evidence_matrix]
    if len(row_ids) != len(set(row_ids)):
        raise ApplicationPackageValidationError(
            "Evidence matrix contains duplicate evidence IDs"
        )

    row_id_set = set(row_ids)
    if row_id_set != used_ids:
        missing_rows = sorted(used_ids - row_id_set)
        extra_rows = sorted(row_id_set - used_ids)
        raise ApplicationPackageValidationError(
            "Evidence matrix must contain exactly the evidence IDs used by the resume and cover letter; "
            f"missing={missing_rows}, extra={extra_rows}"
        )

    for row in validated.evidence_matrix:
        if row.evidence_id not in catalog:
            raise ApplicationPackageValidationError(
                f"Unknown evidence ID in matrix: {row.evidence_id}"
            )
        if row.canonical_evidence != catalog[row.evidence_id]:
            raise ApplicationPackageValidationError(
                f"Canonical evidence text mismatch for {row.evidence_id}"
            )

        actual_locations = evidence_locations[row.evidence_id]
        if set(row.used_in) != actual_locations:
            raise ApplicationPackageValidationError(
                f"used_in mismatch for {row.evidence_id}; "
                f"expected={sorted(actual_locations)}, actual={sorted(row.used_in)}"
            )

    return validated


def prepare_application_package_context(
    job: Job,
    repo_root: Path | str | None = None,
) -> dict[str, Any]:
    root = _repo_root(repo_root)
    if not job.description or not job.description.strip():
        raise ApplicationPackageValidationError(
            "The stored job description is missing or blank"
        )

    slug = expected_job_slug(job)
    work_dir = root / "application_materials" / "work" / slug
    final_dir = root / "application_materials" / "jobs" / slug

    return {
        "job": job.model_dump(mode="json"),
        "expected_job_slug": slug,
        "evidence_catalog": load_candidate_catalog(root),
        "payload_schema": ApplicationPackagePayload.model_json_schema(),
        "role_alignment_guidance": {
            "rule": (
                "Choose the resume opening professional identity from the target job's "
                "actual function. Do not automatically lead with the candidate's most "
                "prestigious employer, certification, or historical title."
            ),
            "examples": {
                "technical_architecture": "Enterprise Technical Architect",
                "infrastructure_architecture": "Infrastructure and Automation Architect",
                "devsecops": "DevSecOps and Infrastructure Automation Architect",
                "cloud_architecture": "Cloud Infrastructure Architect",
                "software_architecture": "Enterprise Software Architect",
                "enterprise_platform": "Enterprise Platform Architect",
            },
        },
        "draft_exists": work_dir.exists(),
        "final_package_exists": final_dir.exists(),
        "human_approval_required": True,
        "safety": {
            "database_writes": False,
            "mark_job_called": False,
            "application_submission": False,
        },
    }


def _render_evidence_matrix(
    payload: ApplicationPackagePayload,
) -> str:
    lines = [
        "# Requirement-to-Evidence Matrix",
        "",
        "Evidence source for all rows: `application_materials/candidate.yaml`",
        "",
        "| Evidence ID | Verified claim | Source file | Source location | Used in | Notes |",
        "|---|---|---|---|---|---|",
    ]

    for row in sorted(payload.evidence_matrix, key=lambda item: item.evidence_id):
        used_in = "; ".join(row.used_in)
        notes_parts = [
            f"Requirement: {row.requirement}",
            f"Strength: {row.strength}",
        ]
        if row.notes:
            notes_parts.append(row.notes)
        notes = "; ".join(notes_parts)
        claim = row.canonical_evidence.replace("|", "\\|")
        notes = notes.replace("|", "\\|")
        used_in = used_in.replace("|", "\\|")
        lines.append(
            f"| `{row.evidence_id}` | {claim} | `application_materials/candidate.yaml` | "
            f"`evidence_catalog.{row.evidence_id}` | {used_in} | {notes} |"
        )

    if payload.unsupported_requirements:
        lines.extend(["", "## Unsupported Requirements", ""])
        lines.extend(f"- {item}" for item in payload.unsupported_requirements)

    if payload.uncertainties:
        lines.extend(["", "## Uncertainties", ""])
        lines.extend(f"- {item}" for item in payload.uncertainties)

    return "\n".join(lines) + "\n"
