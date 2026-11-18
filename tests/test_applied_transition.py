"""One wiring test per mark_job behaviour. The rules are tested in test_lifecycle.py."""

import json
import os

from applywright.server import mcp_app


def _import_saved_job(import_dir):
    json_path = os.path.join(import_dir, "jobs.json")
    with open(json_path, "w") as f:
        json.dump(
            [
                {
                    "title": "Architect",
                    "company": "Architect Co",
                    "application_status": "saved",
                }
            ],
            f,
        )
    mcp_app.import_jobs(json_path)
    return mcp_app.list_jobs(limit=50)[0]["job_id"]


def test_mark_applied_sets_status_date_and_notes(mcp_setup):
    _, import_dir = mcp_setup
    job_id = _import_saved_job(import_dir)

    res = mcp_app.mark_job(
        job_id,
        decision="applied",
        notes="submitted",
        submitted_at="2026-07-17T01:32:55Z",
        package_slug="example-co-123",
    )
    assert res["ok"] is True

    job = mcp_app.get_job(job_id)
    assert job["decision"] == "applied"
    assert job["application_status"] == "applied"
    assert job["date_applied"].startswith("2026-07-17T01:32:55")
    assert job["notes"].startswith("submitted")
    assert "package: example-co-123" in job["notes"]


def test_invalid_submitted_at_is_rejected(mcp_setup):
    _, import_dir = mcp_setup
    job_id = _import_saved_job(import_dir)

    res = mcp_app.mark_job(job_id, decision="applied", submitted_at="not-a-timestamp")
    assert res["ok"] is False
    assert "submitted_at" in res["error"]

    job = mcp_app.get_job(job_id)
    assert job["application_status"] == "saved"
    assert job["date_applied"] is None


def test_invalid_decision_is_rejected(mcp_setup):
    _, import_dir = mcp_setup
    job_id = _import_saved_job(import_dir)

    res = mcp_app.mark_job(job_id, decision="maybe")
    assert res["ok"] is False
    assert "Invalid decision 'maybe'" in res["error"]
    assert mcp_app.get_job(job_id)["decision"] is None


def test_mark_skip_moves_job_out_of_the_saved_listing(mcp_setup):
    _, import_dir = mcp_setup
    job_id = _import_saved_job(import_dir)

    res = mcp_app.mark_job(job_id, decision="skip", notes="not a fit")
    assert res["ok"] is True

    job = mcp_app.get_job(job_id)
    assert job["application_status"] == "rejected"
    assert mcp_app.list_jobs(application_status="saved", limit=50) == []
