"""The rules for how a job's status, decision, and applied date may change.

Every rule about those three fields lives here. `JobRepository` applies the
change sets that these functions return. The MCP handlers and the JSON import
do not state any of these rules themselves.
"""

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional

from applywright.models import ApplicationStatus, Decision, Job

# A job in one of these statuses waits for a first decision. Triage reads these.
TRIAGE_STATUSES = (ApplicationStatus.SAVED,)

# A job in one of these statuses has not been worked yet. An import may change
# its status, and a skip moves it to `rejected`. Every other status belongs to
# the bridge.
UNWORKED_STATUSES = (ApplicationStatus.DISCOVERED, ApplicationStatus.SAVED)

# A job in one of these statuses has been submitted. Its history must survive.
SUBMITTED_STATUSES = (
    ApplicationStatus.APPLIED,
    ApplicationStatus.SCREENING,
    ApplicationStatus.INTERVIEW,
    ApplicationStatus.OFFER,
    ApplicationStatus.WITHDRAWN,
)


@dataclass(frozen=True)
class Submission:
    """What a person recorded when they submitted an application."""

    application_source_url: Optional[str] = None
    package_slug: Optional[str] = None
    confirmation_number: Optional[str] = None
    recruiter_contact: Optional[str] = None

    def note_line(self) -> Optional[str]:
        parts = []
        if self.application_source_url:
            parts.append(f"source: {self.application_source_url}")
        if self.package_slug:
            parts.append(f"package: {self.package_slug}")
        if self.confirmation_number:
            parts.append(f"confirmation: {self.confirmation_number}")
        if self.recruiter_contact:
            parts.append(f"recruiter: {self.recruiter_contact}")
        if not parts:
            return None
        return "Application record: " + "; ".join(parts)


def parse_decision(value: str) -> Decision:
    try:
        return Decision(value)
    except ValueError:
        raise ValueError(
            f"Invalid decision '{value}'. Must be one of: "
            f"{', '.join(d.value for d in Decision)}"
        ) from None


def is_protected(job: Job) -> bool:
    """True when the job was submitted. A submitted job is never deleted."""
    return (
        job.date_applied is not None
        or job.decision == Decision.APPLIED
        or job.application_status in SUBMITTED_STATUSES
    )


def decide(
    job: Job,
    decision: Optional[Decision],
    notes: Optional[str] = None,
    submitted_at: Optional[datetime] = None,
    submission: Optional[Submission] = None,
    now: Optional[datetime] = None,
) -> dict[str, Any]:
    """Return the field changes that recording a decision causes.

    `applied` sets the status and records the submission date once. `skip` moves
    a job that is still in the queue to `rejected`. Other decisions leave the
    status alone. A `Submission` adds one line to the notes.
    """
    moment = now or datetime.now(timezone.utc)
    changes: dict[str, Any] = {}

    if decision is not None:
        changes["decision"] = decision.value

    line = submission.note_line() if submission else None
    if line:
        base = notes if notes is not None else (job.notes or "")
        notes = f"{base}\n{line}" if base else line
    if notes is not None:
        changes["notes"] = notes

    if decision == Decision.APPLIED:
        changes["application_status"] = ApplicationStatus.APPLIED.value
        if job.date_applied is None:
            changes["date_applied"] = (submitted_at or moment).isoformat()
    elif decision == Decision.SKIP:
        if job.application_status in UNWORKED_STATUSES:
            changes["application_status"] = ApplicationStatus.REJECTED.value

    return changes


def start_capture(job: Job) -> None:
    """Make a single-job browser capture a new queue entry.

    A capture starts as `saved` so triage reads it. It carries no decision,
    notes, or applied date. Re-import keeps a worked job's lifecycle through
    `merge_import_status`.
    """
    job.application_status = ApplicationStatus.SAVED
    job.decision = None
    job.notes = None
    job.date_applied = None


def merge_import_status(existing: Job, incoming: Job) -> dict[str, Any]:
    """Return the status fields that a default-mode import may change."""
    changes: dict[str, Any] = {}
    if (
        existing.application_status in UNWORKED_STATUSES
        and incoming.application_status != existing.application_status
    ):
        changes["application_status"] = incoming.application_status.value
    if existing.date_applied is None and incoming.date_applied is not None:
        changes["date_applied"] = incoming.date_applied.isoformat()
    return changes
