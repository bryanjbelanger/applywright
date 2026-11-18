import pydantic
from typing import Dict, Any
from applywright.models import Job
from applywright.screening.config_validator import (
    CandidateProfile,
    JobScoringPolicy,
    ScoredEvaluationPayload,
    BlockedEvaluationPayload,
)


def build_evaluation_context(
    job: Job, profile: CandidateProfile, policy: JobScoringPolicy
) -> Dict[str, Any]:
    """
    Deterministically build an evaluation context for an LLM to evaluate a job.
    This performs no side-effects and contains no timestamps.
    """

    has_description = bool(job.description and job.description.strip())

    if has_description:
        schema = pydantic.TypeAdapter(ScoredEvaluationPayload).json_schema()
        payload_kind = "scored"
    else:
        schema = pydantic.TypeAdapter(BlockedEvaluationPayload).json_schema()
        payload_kind = "blocked"

    context: Dict[str, Any] = {
        "payload_kind": payload_kind,
        "job": {
            "job_id": job.job_id,
            "external_id": job.external_id,
            "title": job.title,
            "company": job.company,
            "location": job.location,
            "remote_status": job.remote_status,
            "salary": job.salary,
            "employment_type": job.employment_type,
            "job_url": job.job_url,
            "description": job.description,
            "application_status": job.application_status.value,
            "source": job.source,
        },
        "candidate_profile": profile.model_dump(mode="json"),
        "job_scoring_policy": policy.model_dump(mode="json"),
        "expected_output_schema": schema,
        "instructions": [
            "use only facts in the job and candidate profile",
            "do not invent candidate experience",
            "do not credit presumed learning ability",
            "unknown location, compensation, employment type, or requirements are uncertainties, not positive matches",
            "cite candidate evidence using only checked-in evidence IDs",
            "identify a hard disqualifier only when the posting explicitly supports it",
            "output only a payload matching the supplied schema",
            "the result is advisory and requires human approval",
        ],
    }

    if not has_description:
        context["instructions"].append(
            "This job has no description. Output only a blocked evaluation payload."
        )

    # Document honestly that deterministic validation cannot fully prove semantic truth
    context["note"] = (
        "Deterministic validation cannot fully prove the semantic truth of an LLM explanation. "
        "Human approval remains strictly required."
    )

    return context
