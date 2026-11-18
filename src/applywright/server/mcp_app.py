import os
from typing import Optional, Dict, Any, List
from mcp.server.fastmcp import FastMCP
from applywright.storage.repository import JobRepository
from applywright.adapters.json_import import import_jobs_from_json
from applywright import lifecycle

# Initialize FastMCP server
mcp = FastMCP("Applywright")

# Determine paths
BASE_DIR = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
)
DB_PATH = os.environ.get(
    "APPLYWRIGHT_DB_PATH", os.path.join(BASE_DIR, "data", "jobs.db")
)
IMPORT_DIR = os.environ.get(
    "APPLYWRIGHT_IMPORT_DIR", os.path.join(BASE_DIR, "data", "imports")
)

# Initialize repository lazily when requested to avoid early side effects
_repo = None


def get_repo() -> JobRepository:
    global _repo
    if _repo is None:
        _repo = JobRepository(DB_PATH)
    return _repo


@mcp.tool()
def list_jobs(
    application_status: Optional[str] = None,
    decision: Optional[str] = None,
    source: Optional[str] = None,
    date_from: Optional[str] = None,
    keywords: Optional[str] = None,
    limit: int = 50,
) -> List[Dict[str, Any]]:
    """List and filter jobs."""
    repo = get_repo()
    jobs = repo.list_jobs(
        status=application_status,
        decision=decision,
        source=source,
        date_from=date_from,
        keywords=keywords,
        limit=limit,
    )
    return [job.model_dump(mode="json") for job in jobs]


@mcp.tool()
def get_job(job_id: str) -> Optional[Dict[str, Any]]:
    """Retrieve a single job by its ID."""
    repo = get_repo()
    job = repo.get_job(job_id)
    return job.model_dump(mode="json") if job else None


@mcp.tool()
def mark_job(
    job_id: str,
    decision: str,
    notes: Optional[str] = None,
    submitted_at: Optional[str] = None,
    application_source_url: Optional[str] = None,
    package_slug: Optional[str] = None,
    confirmation_number: Optional[str] = None,
    recruiter_contact: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Mark a job with a decision ('review', 'apply', 'skip', 'applied') and optional notes.
    Preserves existing notes if notes is omitted.

    When decision is 'applied', application_status transitions to 'applied' and
    date_applied is populated from submitted_at (ISO 8601) or the current UTC time.
    An existing date_applied is never overwritten, so repeating the applied call
    is idempotent. The optional submission-record fields (application_source_url,
    package_slug, confirmation_number, recruiter_contact) are appended to notes.
    """
    from datetime import datetime, timezone

    repo = get_repo()
    job = repo.get_job(job_id)
    if not job:
        return {"ok": False, "error": f"Job {job_id} not found."}
    try:
        try:
            lifecycle.parse_decision(decision)
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}

        parsed_submitted_at: Optional[datetime] = None
        if submitted_at is not None:
            try:
                parsed = datetime.fromisoformat(submitted_at.replace("Z", "+00:00"))
            except ValueError:
                return {
                    "ok": False,
                    "error": f"Invalid submitted_at '{submitted_at}'. Must be an ISO 8601 timestamp.",
                }
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            parsed_submitted_at = parsed.astimezone(timezone.utc)

        repo.update_job_status(
            job_id,
            decision,
            notes,
            submitted_at=parsed_submitted_at,
            submission=lifecycle.Submission(
                application_source_url=application_source_url,
                package_slug=package_slug,
                confirmation_number=confirmation_number,
                recruiter_contact=recruiter_contact,
            ),
        )
        return {
            "ok": True,
            "message": f"Successfully marked job {job_id} as {decision}.",
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}


def _job_digest(job) -> Dict[str, Any]:
    return {
        "job_id": job.job_id,
        "external_id": job.external_id,
        "company": job.company,
        "title": job.title,
        "application_status": (
            job.application_status.value
            if hasattr(job.application_status, "value")
            else job.application_status
        ),
        "decision": (
            job.decision.value if getattr(job.decision, "value", None) else job.decision
        ),
    }


@mcp.tool()
def delete_jobs(
    job_ids: Optional[List[str]] = None,
    application_status: Optional[str] = None,
    decision: Optional[str] = None,
    confirm: bool = False,
) -> Dict[str, Any]:
    """
    Permanently delete jobs from the database.

    Select the target set with job_ids and/or an application_status or decision
    filter (e.g. application_status='rejected'). At least one selector is
    required; the tool refuses to match every job.

    This is a two-step, destructive operation:
      - With confirm=False (default) nothing is deleted; the response previews
        what would be removed (dry_run=True).
      - With confirm=True the matched jobs are permanently deleted.

    Applied jobs are always protected and never deleted, so submission history
    is preserved; they are reported under protected_applied.

    Note: deletion is not a durable filter. If a deleted job is exported from
    JobCopilot again, a later import can re-create it. To keep a job out of the
    active queue across re-imports, mark it 'skip' (which moves it to rejected)
    rather than deleting it.
    """
    repo = get_repo()
    try:
        deletable, protected = repo.select_jobs_for_deletion(
            job_ids=job_ids,
            application_status=application_status,
            decision=decision,
        )
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}

    preview = [_job_digest(j) for j in deletable]
    protected_preview = [_job_digest(j) for j in protected]

    if not confirm:
        return {
            "ok": True,
            "dry_run": True,
            "would_delete": len(deletable),
            "protected_applied": len(protected),
            "jobs": preview,
            "protected_jobs": protected_preview,
            "message": (
                f"Dry run: {len(deletable)} job(s) would be deleted, "
                f"{len(protected)} applied job(s) protected. "
                "Re-call with confirm=true to delete."
            ),
        }

    removed = repo.delete_jobs([j.job_id for j in deletable])
    return {
        "ok": True,
        "dry_run": False,
        "deleted": removed,
        "protected_applied": len(protected),
        "jobs": preview,
        "protected_jobs": protected_preview,
        "message": f"Deleted {removed} job(s); {len(protected)} applied job(s) protected.",
    }


@mcp.tool()
def import_jobs(file_path: str, format: str = "json") -> Dict[str, Any]:
    """
    Import jobs from a file. Currently only 'json' format is supported.
    File must be within the configured data/imports directory.
    """
    if format.lower() != "json":
        return {
            "ok": False,
            "error": f"Format '{format}' is not supported. Only 'json' is supported.",
        }

    repo = get_repo()

    try:
        summary = import_jobs_from_json(file_path, repo, allowed_dir=IMPORT_DIR)
        summary["ok"] = True
        return summary
    except Exception as e:
        return {"ok": False, "error": str(e)}


@mcp.tool()
def prepare_job_evaluation(job_id: str) -> Dict[str, Any]:
    """Prepare a deterministic evaluation context for an LLM."""
    repo = get_repo()
    job = repo.get_job(job_id)
    if not job:
        return {
            "ok": False,
            "error_code": "job_not_found",
            "error": f"Job {job_id} not found.",
        }

    try:
        from applywright.screening.config_validator import (
            load_candidate_profile,
            load_job_scoring_policy,
        )
        from applywright.screening.evaluation_service import (
            build_evaluation_context,
        )

        try:
            profile = load_candidate_profile()
            policy = load_job_scoring_policy()
        except Exception:
            return {
                "ok": False,
                "error_code": "configuration_error",
                "error": "The evaluation configuration could not be loaded.",
            }

        context = build_evaluation_context(job, profile, policy)
        return {"ok": True, "evaluation_context": context}
    except Exception:
        return {
            "ok": False,
            "error_code": "evaluation_validation_failed",
            "error": "The proposed evaluation did not pass validation.",
        }


@mcp.tool()
def validate_job_evaluation(job_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    """Validate a proposed LLM evaluation deterministically against configuration rules."""
    repo = get_repo()
    job = repo.get_job(job_id)
    if not job:
        return {
            "ok": False,
            "error_code": "job_not_found",
            "error": f"Job {job_id} not found.",
        }

    try:
        from applywright.screening.config_validator import (
            load_candidate_profile,
            load_job_scoring_policy,
            validate_evaluation_payload,
        )

        try:
            profile = load_candidate_profile()
            policy = load_job_scoring_policy()
        except Exception:
            return {
                "ok": False,
                "error_code": "configuration_error",
                "error": "The evaluation configuration could not be loaded.",
            }

        try:
            validated_payload = validate_evaluation_payload(
                payload, profile, policy, job
            )
        except ValueError as ve:
            msg = str(ve)
            if "Description state mismatch" in msg:
                return {
                    "ok": False,
                    "error_code": "description_state_mismatch",
                    "error": "The evaluation description state does not match the stored job.",
                }
            if "Schema validation failed" in msg:
                return {
                    "ok": False,
                    "error_code": "payload_schema_error",
                    "error": "The evaluation payload does not match the required schema.",
                }
            return {
                "ok": False,
                "error_code": "evaluation_validation_failed",
                "error": "The proposed evaluation did not pass validation.",
            }

        return {
            "ok": True,
            "job_id": job_id,
            "validated_evaluation": validated_payload.model_dump(mode="json"),
            "canonical_recommendation": validated_payload.recommendation,
            "human_approval_required": True,
        }
    except Exception:
        return {
            "ok": False,
            "error_code": "evaluation_validation_failed",
            "error": "The proposed evaluation did not pass validation.",
        }


@mcp.tool()
def prepare_application_package(job_id: str) -> Dict[str, Any]:
    """Prepare a read-only application-package context for one selected job."""
    repo = get_repo()
    job = repo.get_job(job_id)
    if not job:
        return {
            "ok": False,
            "error_code": "job_not_found",
            "error": f"Job {job_id} not found.",
        }

    try:
        from applywright.application_packages import (
            ApplicationPackageValidationError,
            prepare_application_package_context,
        )

        context = prepare_application_package_context(job)
        return {"ok": True, "application_context": context}
    except ApplicationPackageValidationError as exc:
        error_code = (
            "missing_description"
            if "description" in str(exc).lower()
            else "application_package_validation_failed"
        )
        return {"ok": False, "error_code": error_code, "error": str(exc)}
    except Exception:
        return {
            "ok": False,
            "error_code": "application_package_validation_failed",
            "error": "The application-package context could not be prepared.",
        }


@mcp.tool()
def validate_application_package(
    job_id: str, payload: Dict[str, Any]
) -> Dict[str, Any]:
    """Validate a proposed application package without writing files or job state."""
    repo = get_repo()
    job = repo.get_job(job_id)
    if not job:
        return {
            "ok": False,
            "error_code": "job_not_found",
            "error": f"Job {job_id} not found.",
        }

    try:
        from applywright.application_packages import (
            ApplicationPackageValidationError,
            validate_application_package_payload,
        )

        validated = validate_application_package_payload(job, payload)
        return {
            "ok": True,
            "job_id": job_id,
            "validated_application_package": validated.model_dump(mode="json"),
            "human_approval_required": True,
            "database_modified": False,
        }
    except ApplicationPackageValidationError as exc:
        return {
            "ok": False,
            "error_code": "application_package_validation_failed",
            "error": str(exc),
        }
    except Exception:
        return {
            "ok": False,
            "error_code": "application_package_validation_failed",
            "error": "The proposed application package did not pass validation.",
        }


@mcp.tool()
def materialize_application_draft(
    job_id: str,
    payload: Dict[str, Any],
    human_approved: bool = False,
    replace_existing: bool = False,
) -> Dict[str, Any]:
    """Write an approved application draft to the Git-ignored local work area."""
    repo = get_repo()
    job = repo.get_job(job_id)
    if not job:
        return {
            "ok": False,
            "error_code": "job_not_found",
            "error": f"Job {job_id} not found.",
        }

    if human_approved is not True:
        return {
            "ok": False,
            "error_code": "human_approval_required",
            "error": "Explicit human approval is required before materializing a draft.",
        }

    try:
        from applywright.application_packages import (
            ApplicationPackageValidationError,
            Draft,
        )

        draft = Draft.create(
            job,
            payload,
            human_approved=True,
            replace_existing=replace_existing,
        )
        draft_path = draft.path
        slug = draft.slug
        return {
            "ok": True,
            "job_id": job_id,
            "job_slug": slug,
            "draft_path": str(draft_path),
            "render_command": (
                "poetry run python -m "
                f"application_materials.tools.render_application_draft --slug {slug}"
            ),
            "human_visual_review_required": True,
            "database_modified": False,
            "mark_job_called": False,
        }
    except ApplicationPackageValidationError as exc:
        return {
            "ok": False,
            "error_code": "application_package_validation_failed",
            "error": str(exc),
        }
    except Exception:
        return {
            "ok": False,
            "error_code": "application_draft_write_failed",
            "error": "The application draft could not be materialized.",
        }


def main():
    """Entry point for the MCP server."""
    os.makedirs(IMPORT_DIR, exist_ok=True)
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
