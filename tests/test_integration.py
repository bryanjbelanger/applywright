import os
import pytest
import tempfile
import json
from applywright.storage.repository import JobRepository
from applywright.adapters.json_import import import_jobs_from_json
from applywright.models import Job

@pytest.fixture
def repo():
    fd, path = tempfile.mkstemp()
    os.close(fd)
    repo = JobRepository(path)
    yield repo
    os.remove(path)

@pytest.fixture
def allowed_dir():
    dir_path = tempfile.mkdtemp()
    yield dir_path
    import shutil
    shutil.rmtree(dir_path)

def test_upsert_preserves_decision_and_notes(repo):
    job1 = Job(
        dedupe_key="hash1",
        title="Dev",
        company="Acme",
        source="test"
    )
    # Insert
    repo.upsert_job(job1)
    
    # Mark decision and notes
    repo.update_job_status(job1.job_id, decision="apply", notes="Looks good")
    
    # Simulate update with new job object but same dedupe key
    job2 = Job(
        dedupe_key="hash1",
        title="Dev II",
        company="Acme",
        source="test",
        salary="$100k"
    )
    created, updated = repo.upsert_job(job2)
    assert not created
    assert updated
    
    # Fetch and check
    fetched = repo.get_job(job1.job_id)
    assert fetched.title == "Dev II"
    assert fetched.salary == "$100k"
    assert fetched.decision == "apply"
    assert fetched.notes == "Looks good"

def test_list_jobs_filtering(repo):
    repo.upsert_job(Job(dedupe_key="1", title="Python Dev", company="Acme", source="web", application_status="applied"))
    repo.upsert_job(Job(dedupe_key="2", title="Java Dev", company="Acme", source="web", application_status="saved"))
    repo.upsert_job(Job(dedupe_key="3", title="Python Data Engineer", company="Beta", source="referral"))
    
    assert len(repo.list_jobs(keywords="Python")) == 2
    assert len(repo.list_jobs(status="applied")) == 1
    assert len(repo.list_jobs(source="referral")) == 1

def test_import_jobs_json(repo, allowed_dir):
    json_path = os.path.join(allowed_dir, "jobs.json")
    with open(json_path, "w") as f:
        json.dump([
            {"title": "Dev", "company": "A"},
            {"title": "QA", "company": "B"}
        ], f)
        
    summary = import_jobs_from_json(json_path, repo, allowed_dir)
    assert summary["total_received"] == 2
    assert summary["created"] == 2
    
    # Repeat import (no duplicates)
    summary2 = import_jobs_from_json(json_path, repo, allowed_dir)
    assert summary2["total_received"] == 2
    assert summary2["created"] == 0
    assert summary2["skipped"] == 2

def test_import_outside_allowed_dir(repo, allowed_dir):
    fd, outside_path = tempfile.mkstemp()
    os.close(fd)
    
    with pytest.raises(ValueError, match="outside the allowed import directory"):
        import_jobs_from_json(outside_path, repo, allowed_dir)
        
    os.remove(outside_path)

def test_import_malformed_json(repo, allowed_dir):
    json_path = os.path.join(allowed_dir, "bad.json")
    with open(json_path, "w") as f:
        f.write("{ bad json ]")
        
    with pytest.raises(ValueError, match="not valid JSON"):
        import_jobs_from_json(json_path, repo, allowed_dir)
