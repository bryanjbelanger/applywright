import json
import re
from typing import Dict, Any
from datetime import datetime
from applywright import lifecycle
from applywright.models import Job
from applywright.utils import (
    generate_dedupe_key,
    parse_jobcopilot_review_url,
    parse_linkedin_job_url,
)
from applywright.storage.repository import JobRepository, UpdateMode
from pydantic import ValidationError


def import_jobs_from_json(
    file_path: str, repo: JobRepository, allowed_dir: str
) -> Dict[str, Any]:
    """
    Import jobs from a JSON file.
    Only allows importing from the configured allowed_dir for security.
    Returns a summary of the import process.
    """
    summary: dict[str, Any] = {
        "total_received": 0,
        "created": 0,
        "updated": 0,
        "skipped": 0,
        "errors": 0,
        "error_details": [],
        "warnings": [],
    }

    import pathlib

    # Security check
    resolved_file = pathlib.Path(file_path).resolve()
    resolved_allowed = pathlib.Path(allowed_dir).resolve()

    if not resolved_file.is_relative_to(resolved_allowed):
        raise ValueError(
            f"File {file_path} is outside the allowed import directory {allowed_dir}"
        )

    if not resolved_file.exists():
        raise FileNotFoundError(f"File {file_path} not found")

    with open(resolved_file, "r", encoding="utf-8") as f:
        try:
            data = json.load(f)
        except json.JSONDecodeError:
            raise ValueError(f"File {file_path} is not valid JSON")

    jobs_data = []
    if isinstance(data, list):
        jobs_data = data
    elif isinstance(data, dict) and "jobs" in data:
        jobs_data = data["jobs"]
    else:
        raise ValueError(
            "JSON must be a list of jobs or a dictionary with a 'jobs' key"
        )

    is_enrichment = False
    is_linkedin = False
    if isinstance(data, dict) and "metadata" in data:
        metadata = data["metadata"]
        export_kind = metadata.get("export_kind")
        if export_kind in ("current_job_enrichment", "batch_enrichment"):
            is_enrichment = True
            if metadata.get("source") and metadata.get("source") != "jobcopilot":
                raise ValueError(
                    "Enrichment envelope invalid: metadata.source must be 'jobcopilot' if present"
                )
            if export_kind == "current_job_enrichment" and len(jobs_data) != 1:
                raise ValueError(
                    "Enrichment envelope invalid: exactly one job must be present"
                )
            if export_kind == "batch_enrichment" and not (1 <= len(jobs_data) <= 20):
                raise ValueError(
                    "Enrichment envelope invalid: batch must contain between 1 and 20 jobs"
                )

    if isinstance(data, dict) and "metadata" in data:
        if data["metadata"].get("export_kind") == "linkedin_capture":
            is_linkedin = True
            if data["metadata"].get("source") != "linkedin":
                raise ValueError(
                    "LinkedIn capture invalid: metadata.source must be 'linkedin'"
                )
            if len(jobs_data) != 1:
                raise ValueError(
                    "LinkedIn capture invalid: exactly one job must be present"
                )

    summary["total_received"] = len(jobs_data)

    for idx, raw_job in enumerate(jobs_data):
        if not isinstance(raw_job, dict):
            summary["errors"] += 1
            summary["error_details"].append(
                {"index": idx, "error": "Item is not a dictionary"}
            )
            continue

        job_data = raw_job.copy()
        try:
            # Add implicit source if not present
            source = job_data.get("source", "jobcopilot_import")
            job_data["source"] = source

            # Generate dedupe_key
            dedupe_key = generate_dedupe_key(
                source=source,
                company=job_data.get("company", ""),
                title=job_data.get("title", ""),
                job_url=job_data.get("job_url", ""),
            )
            job_data["dedupe_key"] = dedupe_key

            # Convert date strings to datetimes if they exist but aren't
            for date_field in ["date_found", "date_applied"]:
                if date_field in job_data and isinstance(job_data[date_field], str):
                    try:
                        job_data[date_field] = datetime.fromisoformat(
                            job_data[date_field].replace("Z", "+00:00")
                        )
                    except ValueError:
                        pass

            # Validate and create model
            job = Job(**job_data)

            update_mode = UpdateMode.DEFAULT
            if is_enrichment:
                update_mode = UpdateMode.ENRICHMENT
                if job.source != "jobcopilot":
                    raise ValueError(
                        "Enrichment envelope invalid: job source must be 'jobcopilot'"
                    )
                if not job.external_id or not str(job.external_id).strip():
                    raise ValueError(
                        "Enrichment envelope invalid: external_id must be nonblank"
                    )
                if not job.title or not str(job.title).strip():
                    raise ValueError(
                        "Enrichment envelope invalid: title must be nonblank"
                    )
                if not job.company or not str(job.company).strip():
                    raise ValueError(
                        "Enrichment envelope invalid: company must be nonblank"
                    )
                if not job.description or not str(job.description).strip():
                    raise ValueError(
                        "Enrichment envelope invalid: description must be nonblank"
                    )
                if not job.job_url:
                    raise ValueError(
                        "Enrichment envelope invalid: canonical job_url is missing"
                    )

                parsed = parse_jobcopilot_review_url(job.job_url)
                if not parsed:
                    raise ValueError(
                        "Enrichment envelope invalid: Invalid JobCopilot review URL or external ID."
                    )

                canonical_url, extracted_id = parsed
                if extracted_id != str(job.external_id):
                    raise ValueError(
                        "Enrichment envelope invalid: canonical job_url does not match external_id"
                    )

                job.job_url = canonical_url

            if is_linkedin:
                ext = str(job.external_id or "")
                if job.source != "linkedin":
                    raise ValueError(
                        "LinkedIn capture invalid: job source must be 'linkedin'"
                    )
                if not re.fullmatch(r"[0-9]+", ext):
                    raise ValueError(
                        "LinkedIn capture invalid: external_id must be digits only"
                    )
                parsed_li = parse_linkedin_job_url(job.job_url or "")
                if not parsed_li or parsed_li[1] != ext:
                    raise ValueError(
                        "LinkedIn capture invalid: job_url is missing or does not match external_id"
                    )
                job.job_url = parsed_li[0]
                job.dedupe_key = generate_dedupe_key(
                    source=job.source,
                    company=job.company,
                    title=job.title,
                    job_url=job.job_url,
                )
                lifecycle.start_capture(job)

            # Upsert
            created, updated = repo.upsert_job(job, update_mode=update_mode)
            if is_linkedin:
                for dup_id in repo.find_cross_source_duplicates(job):
                    summary["warnings"].append(
                        f"Possible duplicate of existing job {dup_id} "
                        "(same company and title, different source)"
                    )
            if created:
                summary["created"] += 1
            elif updated:
                summary["updated"] += 1
            else:
                summary["skipped"] += 1

        except ValidationError as e:
            summary["errors"] += 1
            summary["error_details"].append({"index": idx, "error": str(e)})
        except Exception as e:
            summary["errors"] += 1
            summary["error_details"].append({"index": idx, "error": str(e)})

    return summary
