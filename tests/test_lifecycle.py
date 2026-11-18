"""The rules for how a job's status, decision, and applied date may change."""

from datetime import datetime, timezone

import pytest

from applywright import lifecycle
from applywright.models import ApplicationStatus, Decision, Job
from applywright.storage.repository import UpdateMode

NOW = datetime(2026, 7, 20, 12, 0, tzinfo=timezone.utc)


def make_job(**overrides) -> Job:
    fields = dict(
        dedupe_key="k1",
        external_id="e1",
        title="Architect",
        company="Acme",
        source="jobcopilot",
        application_status=ApplicationStatus.SAVED,
    )
    fields.update(overrides)
    return Job(**fields)


# decide ---------------------------------------------------------------------


def test_applied_sets_status_and_date():
    changes = lifecycle.decide(make_job(), Decision.APPLIED, now=NOW)
    assert changes["decision"] == "applied"
    assert changes["application_status"] == "applied"
    assert changes["date_applied"] == NOW.isoformat()


def test_applied_uses_the_submission_time_when_given():
    submitted = datetime(2026, 7, 17, 1, 32, 55, tzinfo=timezone.utc)
    changes = lifecycle.decide(
        make_job(), Decision.APPLIED, submitted_at=submitted, now=NOW
    )
    assert changes["date_applied"] == submitted.isoformat()


def test_applied_never_overwrites_a_recorded_date():
    job = make_job(
        application_status=ApplicationStatus.APPLIED,
        date_applied=datetime(2026, 7, 1, tzinfo=timezone.utc),
    )
    changes = lifecycle.decide(job, Decision.APPLIED, now=NOW)
    assert "date_applied" not in changes


@pytest.mark.parametrize("decision", [Decision.REVIEW, Decision.APPLY])
def test_triage_decisions_leave_status_and_date_alone(decision):
    changes = lifecycle.decide(make_job(), decision, now=NOW)
    assert changes == {"decision": decision.value}


@pytest.mark.parametrize(
    "status", [ApplicationStatus.DISCOVERED, ApplicationStatus.SAVED]
)
def test_skip_rejects_a_job_that_is_still_in_the_queue(status):
    changes = lifecycle.decide(make_job(application_status=status), Decision.SKIP)
    assert changes["application_status"] == "rejected"


@pytest.mark.parametrize(
    "status", [ApplicationStatus.APPLIED, ApplicationStatus.INTERVIEW]
)
def test_skip_keeps_the_status_of_a_worked_job(status):
    changes = lifecycle.decide(make_job(application_status=status), Decision.SKIP)
    assert "application_status" not in changes


def test_notes_are_kept_when_omitted_and_extended_by_a_submission():
    job = make_job(notes="evaluation note")
    submission = lifecycle.Submission(package_slug="example-co-123")

    kept = lifecycle.decide(job, Decision.REVIEW)
    extended = lifecycle.decide(job, Decision.APPLIED, submission=submission)

    assert "notes" not in kept
    assert extended["notes"] == (
        "evaluation note\nApplication record: package: example-co-123"
    )


def test_submission_note_replaces_the_stored_notes_when_notes_are_given():
    submission = lifecycle.Submission(
        application_source_url="https://example.com/apply/123",
        confirmation_number="CONF-42",
        recruiter_contact="Recruiter <r@example.com>",
    )
    changes = lifecycle.decide(
        make_job(notes="old"), Decision.APPLIED, notes="new", submission=submission
    )
    assert changes["notes"] == (
        "new\nApplication record: source: https://example.com/apply/123; "
        "confirmation: CONF-42; recruiter: Recruiter <r@example.com>"
    )


def test_an_empty_submission_adds_nothing():
    assert lifecycle.Submission().note_line() is None


def test_parse_decision_names_the_valid_values():
    with pytest.raises(ValueError, match="Invalid decision 'maybe'. Must be one of"):
        lifecycle.parse_decision("maybe")


# is_protected ---------------------------------------------------------------


@pytest.mark.parametrize(
    "status",
    ["applied", "screening", "interview", "offer", "withdrawn"],
)
def test_submitted_statuses_are_protected(status):
    assert lifecycle.is_protected(make_job(application_status=status))


def test_applied_decision_and_recorded_date_are_protected():
    assert lifecycle.is_protected(make_job(decision=Decision.APPLIED))
    assert lifecycle.is_protected(
        make_job(date_applied=datetime(2026, 7, 1, tzinfo=timezone.utc))
    )


@pytest.mark.parametrize("status", ["discovered", "saved", "rejected", "unknown"])
def test_queue_and_rejected_jobs_are_not_protected(status):
    assert not lifecycle.is_protected(make_job(application_status=status))


# merge_import_status --------------------------------------------------------


def test_import_may_move_a_saved_job_forward():
    changes = lifecycle.merge_import_status(
        make_job(),
        make_job(
            application_status=ApplicationStatus.APPLIED,
            date_applied=datetime(2026, 7, 5, tzinfo=timezone.utc),
        ),
    )
    assert changes["application_status"] == "applied"
    assert changes["date_applied"].startswith("2026-07-05")


@pytest.mark.parametrize(
    "status",
    ["rejected", "applied", "screening", "interview", "offer", "withdrawn"],
)
def test_import_never_changes_a_status_the_bridge_owns(status):
    changes = lifecycle.merge_import_status(
        make_job(application_status=status),
        make_job(application_status=ApplicationStatus.SAVED),
    )
    assert "application_status" not in changes


def test_import_never_overwrites_a_recorded_date():
    changes = lifecycle.merge_import_status(
        make_job(date_applied=datetime(2026, 7, 1, tzinfo=timezone.utc)),
        make_job(date_applied=datetime(2026, 8, 1, tzinfo=timezone.utc)),
    )
    assert "date_applied" not in changes


# repository -----------------------------------------------------------------


def seed(repo, **overrides) -> Job:
    job = make_job(**overrides)
    repo.upsert_job(job)
    return job


def test_repository_records_applied_once(lifecycle_repo):
    job = seed(lifecycle_repo)
    first = datetime(2026, 7, 17, 1, 32, 55, tzinfo=timezone.utc)
    later = datetime(2026, 7, 18, 9, 0, tzinfo=timezone.utc)

    lifecycle_repo.update_job_status(job.job_id, "applied", submitted_at=first)
    lifecycle_repo.update_job_status(job.job_id, "applied", submitted_at=later)
    lifecycle_repo.update_job_status(job.job_id, "applied")

    stored = lifecycle_repo.get_job(job.job_id)
    assert stored.application_status == ApplicationStatus.APPLIED
    assert stored.date_applied == first


def test_repository_leaves_other_jobs_alone(lifecycle_repo):
    job = seed(lifecycle_repo)
    other = seed(lifecycle_repo, dedupe_key="k2", external_id="e2")

    lifecycle_repo.update_job_status(job.job_id, "applied")

    bystander = lifecycle_repo.get_job(other.job_id)
    assert bystander.application_status == ApplicationStatus.SAVED
    assert bystander.decision is None
    assert bystander.date_applied is None
    assert bystander.notes is None


def test_repository_returns_none_for_an_unknown_job(lifecycle_repo):
    assert lifecycle_repo.update_job_status("missing", "skip") is None


def test_reimport_keeps_a_skipped_job_rejected(lifecycle_repo):
    """F4: a list scan exports a skipped job as `saved`. Import must not revive it."""
    job = seed(lifecycle_repo)
    lifecycle_repo.update_job_status(job.job_id, "skip")

    created, updated = lifecycle_repo.upsert_job(make_job())

    stored = lifecycle_repo.get_job(job.job_id)
    assert (created, updated) == (False, False)
    assert stored.application_status == ApplicationStatus.REJECTED
    assert stored.decision == Decision.SKIP


def test_reimport_still_moves_a_saved_job_to_applied(lifecycle_repo):
    job = seed(lifecycle_repo)

    lifecycle_repo.upsert_job(
        make_job(
            application_status=ApplicationStatus.APPLIED,
            date_applied=datetime(2026, 7, 5, tzinfo=timezone.utc),
        )
    )

    stored = lifecycle_repo.get_job(job.job_id)
    assert stored.application_status == ApplicationStatus.APPLIED
    assert stored.date_applied is not None


def test_enrichment_import_never_touches_lifecycle_fields(lifecycle_repo):
    job = seed(lifecycle_repo)
    lifecycle_repo.update_job_status(job.job_id, "skip")

    lifecycle_repo.upsert_job(
        make_job(
            application_status=ApplicationStatus.APPLIED,
            description="Full description",
        ),
        update_mode=UpdateMode.ENRICHMENT,
    )

    stored = lifecycle_repo.get_job(job.job_id)
    assert stored.application_status == ApplicationStatus.REJECTED
    assert stored.description == "Full description"


def test_interview_job_with_no_date_cannot_be_deleted(lifecycle_repo):
    """A job in `interview` is protected even when no submission date was recorded."""
    job = seed(lifecycle_repo, application_status=ApplicationStatus.INTERVIEW)

    deletable, protected = lifecycle_repo.select_jobs_for_deletion(job_ids=[job.job_id])

    assert deletable == []
    assert [j.job_id for j in protected] == [job.job_id]


def test_repository_delete_refuses_a_submitted_job(lifecycle_repo):
    submitted = seed(lifecycle_repo, application_status=ApplicationStatus.OFFER)
    queued = seed(lifecycle_repo, dedupe_key="k2", external_id="e2")

    removed = lifecycle_repo.delete_jobs([submitted.job_id, queued.job_id])

    assert removed == 1
    assert lifecycle_repo.get_job(submitted.job_id) is not None
    assert lifecycle_repo.get_job(queued.job_id) is None


def test_triage_listing_with_no_statuses_returns_nothing(lifecycle_repo):
    seed(lifecycle_repo)

    assert lifecycle_repo.list_jobs_for_triage(()) == []
