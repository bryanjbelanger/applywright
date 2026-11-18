import json
import os
import sqlite3
import tempfile

import pytest

from applywright.adapters.json_import import import_jobs_from_json
from applywright.models import Job
from applywright.storage.repository import JobRepository
from applywright.utils import parse_linkedin_job_url


@pytest.fixture
def env():
    with tempfile.TemporaryDirectory() as temp_dir:
        yield JobRepository(os.path.join(temp_dir, "t.db")), temp_dir


def run(data, repo, temp_dir):
    path = os.path.join(temp_dir, "cap.json")
    with open(path, "w") as f:
        json.dump(data, f)
    return import_jobs_from_json(path, repo, temp_dir)


def envelope(**over):
    job = {
        "external_id": "4001234567",
        "title": "Cloud Architect",
        "company": "Acme",
        "location": "Remote",
        "remote_status": "Remote",
        "description": "About the job",
        "job_url": "https://www.linkedin.com/jobs/view/4001234567/",
        "apply_type": "external",
        "apply_url": "https://acme.com/apply",
        "source": "linkedin",
    }
    job.update(over)
    return {
        "metadata": {"source": "linkedin", "export_kind": "linkedin_capture"},
        "jobs": [job],
    }


def get(repo, source="linkedin"):
    return repo.list_jobs(source=source)[0]


def test_parse_url():
    ok = "https://www.linkedin.com/jobs/view/123/"
    assert parse_linkedin_job_url("https://www.linkedin.com/jobs/view/123?x=1#f") == (
        ok,
        "123",
    )
    for bad in [
        "http://www.linkedin.com/jobs/view/123/",
        "https://linkedin.com/jobs/view/123/",
        "https://www.linkedin.com/jobs/view/abc/",
        "https://www.linkedin.com/jobs/view/123/extra",
        "https://evil.com/jobs/view/123/",
        "",
    ]:
        assert parse_linkedin_job_url(bad) is None


def test_accept_saved_with_apply_url(env):
    repo, d = env
    res = run(envelope(), repo, d)
    assert res["created"] == 1 and res["errors"] == 0
    job = get(repo)
    assert job.application_status == "saved"
    assert job.apply_url == "https://acme.com/apply"
    assert repo.get_job(job.job_id).apply_url == "https://acme.com/apply"


def _meta_source(e):
    e["metadata"]["source"] = "jobcopilot"


def _two_jobs(e):
    e["jobs"].append(dict(e["jobs"][0]))


def _no_jobs(e):
    e["jobs"] = []


def _job_field(**kw):
    def mutate(e):
        e["jobs"][0].update(kw)

    return mutate


@pytest.mark.parametrize(
    "mutate",
    [
        _meta_source,
        _two_jobs,
        _no_jobs,
        _job_field(source="jobcopilot"),
        _job_field(external_id="12ab"),
        _job_field(external_id=""),
        _job_field(job_url="https://www.linkedin.com/jobs/view/999/"),
        _job_field(job_url="https://example.com/jobs/view/4001234567/"),
        _job_field(job_url=None),
    ],
)
def test_rejects(env, mutate):
    repo, d = env
    e = envelope()
    mutate(e)
    try:
        res = run(e, repo, d)
        assert res["errors"] >= 1 and res["created"] == 0
    except ValueError:
        pass
    assert repo.list_jobs() == []


def test_reimport_keeps_lifecycle(env):
    repo, d = env
    run(envelope(), repo, d)
    job = get(repo)
    repo.update_job_status(job.job_id, "applied", notes="my note")
    before = repo.get_job(job.job_id)
    res = run(envelope(description="New description"), repo, d)
    assert res["updated"] == 1
    after = repo.get_job(job.job_id)
    assert after.application_status == before.application_status == "applied"
    assert after.decision == "applied"
    assert after.notes == "my note"
    assert after.date_applied == before.date_applied is not None
    assert after.description == "New description"


def test_reimport_after_skip_stays_rejected(env):
    repo, d = env
    run(envelope(), repo, d)
    job = get(repo)
    repo.update_job_status(job.job_id, "skip")
    run(envelope(), repo, d)
    after = repo.get_job(job.job_id)
    assert after.application_status == "rejected" and after.decision == "skip"


def test_null_apply_url_does_not_erase(env):
    repo, d = env
    run(envelope(), repo, d)
    run(envelope(apply_url=None), repo, d)
    assert get(repo).apply_url == "https://acme.com/apply"


def test_migration_adds_apply_url():
    with tempfile.TemporaryDirectory() as d:
        db = os.path.join(d, "old.db")
        conn = sqlite3.connect(db)
        conn.executescript("""CREATE TABLE jobs (
            job_id TEXT PRIMARY KEY, external_id TEXT, dedupe_key TEXT UNIQUE NOT NULL,
            title TEXT NOT NULL, company TEXT NOT NULL, location TEXT, remote_status TEXT,
            salary TEXT, employment_type TEXT, job_url TEXT, description TEXT,
            date_found DATETIME, date_applied DATETIME,
            application_status TEXT NOT NULL DEFAULT 'discovered', source TEXT NOT NULL,
            decision TEXT, notes TEXT,
            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP);
            INSERT INTO jobs (job_id, dedupe_key, title, company, source)
            VALUES ('old1', 'k', 'T', 'C', 'jobcopilot');""")
        conn.commit()
        conn.close()
        repo = JobRepository(db)
        JobRepository(db)  # idempotent
        old = repo.get_job("old1")
        assert old is not None and old.apply_url is None
        run(envelope(), repo, d)
        assert get(repo).apply_url == "https://acme.com/apply"


def test_duplicate_warning(env):
    repo, d = env
    other = Job(
        external_id="x",
        dedupe_key="k1",
        title="cloud  architect",
        company="ACME.",
        source="jobcopilot",
    )
    repo.upsert_job(other)
    res = run(envelope(), repo, d)
    assert res["created"] == 1
    assert len(res["warnings"]) == 1
    assert other.job_id in res["warnings"][0]


def test_no_warning_for_same_source_or_different_job(env):
    repo, d = env
    repo.upsert_job(
        Job(dedupe_key="k2", title="Other Role", company="Acme", source="jobcopilot")
    )
    res = run(envelope(), repo, d)
    assert res["warnings"] == []
    assert run(envelope(), repo, d)["warnings"] == []
