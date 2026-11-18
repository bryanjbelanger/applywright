import os
import pytest
import tempfile
import json
from datetime import datetime, timezone
from applywright.storage.repository import JobRepository
from applywright.adapters.json_import import import_jobs_from_json
from applywright.models import Job, Decision, ApplicationStatus

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

def test_import_sibling_prefix_path_attack(repo, allowed_dir):
    # Setup sibling directory with prefix
    parent_dir = os.path.dirname(allowed_dir)
    base_name = os.path.basename(allowed_dir)
    sibling_dir = os.path.join(parent_dir, base_name + "_attack")
    os.makedirs(sibling_dir, exist_ok=True)
    
    json_path = os.path.join(sibling_dir, "attack.json")
    with open(json_path, "w") as f:
        json.dump([{"title": "Hacker", "company": "Evil"}], f)
        
    with pytest.raises(ValueError, match="outside the allowed import directory"):
        import_jobs_from_json(json_path, repo, allowed_dir)
        
    import shutil
    shutil.rmtree(sibling_dir)

def test_import_symlink_path_attack(repo, allowed_dir):
    parent_dir = os.path.dirname(allowed_dir)
    outside_file = os.path.join(parent_dir, "outside.json")
    with open(outside_file, "w") as f:
        json.dump([{"title": "Hacker", "company": "Evil"}], f)
        
    symlink_path = os.path.join(allowed_dir, "symlink.json")
    try:
        os.symlink(outside_file, symlink_path)
    except (OSError, NotImplementedError):
        pytest.skip("Symlink creation is unavailable on this platform.")
        
    with pytest.raises(ValueError, match="outside the allowed import directory"):
        import_jobs_from_json(symlink_path, repo, allowed_dir)
        
    os.remove(outside_file)
    if os.path.exists(symlink_path):
        os.remove(symlink_path)

def test_invalid_decision_does_not_corrupt_database(repo):
    job = Job(dedupe_key="1", title="Dev", company="Acme", source="test")
    repo.upsert_job(job)
    
    # Attempt to set invalid decision via repository directly
    with pytest.raises(ValueError, match="Invalid decision 'invalid'"):
        repo.update_job_status(job.job_id, decision="invalid")
        
    # Verify the database record remains intact and unaffected
    fetched = repo.get_job(job.job_id)
    assert fetched.decision is None

def test_application_status_and_dates_update_on_reimport(repo, allowed_dir):
    json_path = os.path.join(allowed_dir, "jobs.json")
    with open(json_path, "w") as f:
        json.dump([{
            "title": "Dev", "company": "A", "external_id": "e1", "source": "test",
            "application_status": "saved", "date_found": "2026-07-01T12:00:00Z"
        }], f)
    import_jobs_from_json(json_path, repo, allowed_dir)
    
    # Reimport with updated status and date
    with open(json_path, "w") as f:
        json.dump([{
            "title": "Dev", "company": "A", "external_id": "e1", "source": "test",
            "application_status": "applied", "date_found": "2026-07-01T12:00:00Z",
            "date_applied": "2026-07-05T12:00:00Z"
        }], f)
    import_jobs_from_json(json_path, repo, allowed_dir)
    
    jobs = repo.list_jobs()
    assert len(jobs) == 1
    assert jobs[0].application_status.value == "applied"
    assert jobs[0].date_applied is not None

def test_duplicate_external_ids_within_same_source(repo, allowed_dir):
    # It should update the same record if external_id and source match
    json_path = os.path.join(allowed_dir, "jobs.json")
    with open(json_path, "w") as f:
        json.dump([
            {"title": "Dev1", "company": "A", "external_id": "dup", "source": "test"},
            {"title": "Dev2", "company": "A", "external_id": "dup", "source": "test"}
        ], f)
    summary = import_jobs_from_json(json_path, repo, allowed_dir)
    assert summary["created"] == 1
    assert summary["updated"] == 1
    
    jobs = repo.list_jobs()
    assert len(jobs) == 1
    assert jobs[0].title == "Dev2"

def test_identical_external_ids_from_different_sources(repo, allowed_dir):
    # It should create two separate records
    json_path = os.path.join(allowed_dir, "jobs.json")
    with open(json_path, "w") as f:
        json.dump([
            {"title": "Dev1", "company": "A", "external_id": "same_id", "source": "source1"},
            {"title": "Dev1", "company": "A", "external_id": "same_id", "source": "source2"}
        ], f)
    summary = import_jobs_from_json(json_path, repo, allowed_dir)
    assert summary["created"] == 2
    
    jobs = repo.list_jobs()
    assert len(jobs) == 2

def test_partially_valid_json_imports(repo, allowed_dir):
    json_path = os.path.join(allowed_dir, "jobs.json")
    with open(json_path, "w") as f:
        json.dump([
            {"title": "Dev1", "company": "A"}, # Valid
            "invalid_job_format",              # Invalid type
            {"company": "B"},                  # Invalid (missing title)
            {"title": "Dev2", "company": "C"}  # Valid
        ], f)
    summary = import_jobs_from_json(json_path, repo, allowed_dir)
    
    assert summary["total_received"] == 4
    assert summary["created"] == 2
    assert summary["errors"] == 2
    assert len(summary["error_details"]) == 2

def test_notes_remain_unchanged_when_notes_is_omitted(repo):
    job = Job(dedupe_key="1", title="Dev", company="Acme", source="test")
    repo.upsert_job(job)
    repo.update_job_status(job.job_id, decision=Decision.APPLY.value, notes="My note")
    
    # Update decision, omit notes (pass None)
    repo.update_job_status(job.job_id, decision=Decision.SKIP.value, notes=None)
    
    fetched = repo.get_job(job.job_id)
    assert fetched.decision.value == "skip"
    assert fetched.notes == "My note"
