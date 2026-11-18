"""delete_jobs is destructive, so its guardrails are the point of these tests:
dry-run by default, applied-job protection, and refusal to match everything.
"""

import json
import os

from applywright.server import mcp_app


def _seed(import_dir, specs):
    """specs: list of (title, status). Returns {title: job_id}."""
    path = os.path.join(import_dir, "jobs.json")
    with open(path, "w") as f:
        json.dump(
            [
                {"title": t, "company": f"{t} Co", "application_status": s}
                for t, s in specs
            ],
            f,
        )
    mcp_app.import_jobs(path)
    return {j["title"]: j["job_id"] for j in mcp_app.list_jobs(limit=50)}


def test_dry_run_is_the_default_and_deletes_nothing(mcp_setup):
    _, import_dir = mcp_setup
    _seed(import_dir, [("A", "rejected"), ("B", "rejected")])
    res = mcp_app.delete_jobs(application_status="rejected")
    assert res["dry_run"] is True
    assert res["would_delete"] == 2
    # Still present.
    assert len(mcp_app.list_jobs(application_status="rejected", limit=50)) == 2


def test_confirm_deletes_matched_jobs(mcp_setup):
    _, import_dir = mcp_setup
    _seed(import_dir, [("A", "rejected"), ("B", "saved")])
    res = mcp_app.delete_jobs(application_status="rejected", confirm=True)
    assert res["deleted"] == 1
    assert mcp_app.list_jobs(application_status="rejected", limit=50) == []
    assert len(mcp_app.list_jobs(application_status="saved", limit=50)) == 1


def test_applied_jobs_are_never_deleted(mcp_setup):
    _, import_dir = mcp_setup
    ids = _seed(import_dir, [("A", "saved")])
    mcp_app.mark_job(ids["A"], decision="applied", submitted_at="2026-07-17T00:00:00Z")
    # Even when explicitly targeted by id and confirmed.
    res = mcp_app.delete_jobs(job_ids=[ids["A"]], confirm=True)
    assert res["deleted"] == 0
    assert res["protected_applied"] == 1
    assert mcp_app.get_job(ids["A"]) is not None


def test_delete_by_explicit_ids(mcp_setup):
    _, import_dir = mcp_setup
    ids = _seed(import_dir, [("A", "saved"), ("B", "saved"), ("C", "saved")])
    res = mcp_app.delete_jobs(job_ids=[ids["A"], ids["C"]], confirm=True)
    assert res["deleted"] == 2
    remaining = {j["title"] for j in mcp_app.list_jobs(limit=50)}
    assert remaining == {"B"}


def test_refuses_to_match_everything(mcp_setup):
    _, import_dir = mcp_setup
    _seed(import_dir, [("A", "saved")])
    res = mcp_app.delete_jobs()
    assert res["ok"] is False
    assert "Refusing" in res["error"]
    assert len(mcp_app.list_jobs(limit=50)) == 1


def test_decision_filter_selects_correctly(mcp_setup):
    _, import_dir = mcp_setup
    ids = _seed(import_dir, [("A", "saved"), ("B", "saved")])
    mcp_app.mark_job(ids["A"], decision="skip")  # -> rejected
    res = mcp_app.delete_jobs(decision="skip", confirm=True)
    assert res["deleted"] == 1
    assert mcp_app.get_job(ids["A"]) is None
    assert mcp_app.get_job(ids["B"]) is not None
