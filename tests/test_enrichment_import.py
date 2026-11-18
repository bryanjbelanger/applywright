import pytest
import os
import json
import tempfile
from datetime import datetime, timezone
from applywright.storage.repository import JobRepository, UpdateMode
from applywright.models import Job
from applywright.adapters.json_import import import_jobs_from_json

@pytest.fixture
def repo():
    with tempfile.TemporaryDirectory() as temp_dir:
        db_path = os.path.join(temp_dir, "test.db")
        repo = JobRepository(db_path)
        yield repo, temp_dir

def _run_import(data, job_repo, temp_dir):
    file_path = os.path.join(temp_dir, "enrichment.json")
    with open(file_path, "w") as f:
        json.dump(data, f)
    return import_jobs_from_json(file_path, job_repo, temp_dir)

@pytest.fixture
def valid_envelope():
    return {
        "metadata": {"export_kind": "current_job_enrichment", "source": "jobcopilot"},
        "jobs": [{
            "external_id": "123",
            "title": "T",
            "company": "C",
            "description": "D",
            "source": "jobcopilot",
            "job_url": "https://app.jobcopilot.com/applications/review/123"
        }]
    }

def test_envelope_validation_valid(repo, valid_envelope):
    job_repo, temp_dir = repo
    job_repo.upsert_job(Job(external_id="123", dedupe_key="h", title="T", company="C", source="jobcopilot"))
    res = _run_import(valid_envelope, job_repo, temp_dir)
    assert res["errors"] == 0, res["error_details"]
    assert res["updated"] == 1

def test_envelope_validation_invalid_export_kind(repo, valid_envelope):
    job_repo, temp_dir = repo
    valid_envelope["metadata"]["export_kind"] = "other"
    # Treated as standard import, so creates a new job
    res = _run_import(valid_envelope, job_repo, temp_dir)
    assert res["created"] == 1

def test_envelope_validation_missing_metadata(repo, valid_envelope):
    job_repo, temp_dir = repo
    # 2. Zero jobs in enrichment
    valid_envelope["jobs"] = []
    with pytest.raises(ValueError, match="exactly one job must be present"):
        _run_import(valid_envelope, job_repo, temp_dir)
        
    # 3. More than one job
    valid_envelope["jobs"] = [
        {"external_id": "123", "title": "T", "company": "C", "description": "D", "source": "jobcopilot", "job_url": "https://app.jobcopilot.com/applications/review/123"},
        {"external_id": "123", "title": "T", "company": "C", "description": "D", "source": "jobcopilot", "job_url": "https://app.jobcopilot.com/applications/review/123"}
    ]
    with pytest.raises(ValueError, match="exactly one job must be present"):
        _run_import(valid_envelope, job_repo, temp_dir)
        
    # 4. Invalid metadata.source
    valid_envelope["jobs"] = [{"external_id": "123", "title": "T", "company": "C", "description": "D", "source": "jobcopilot", "job_url": "https://app.jobcopilot.com/applications/review/123"}]
    valid_envelope["metadata"]["source"] = "other"
    with pytest.raises(ValueError, match="metadata.source must be 'jobcopilot' if present"):
        _run_import(valid_envelope, job_repo, temp_dir)

@pytest.mark.parametrize("mutator, expected_error", [
    (lambda j: j.update({"source": "other"}), "job source must be 'jobcopilot'"),
    (lambda j: j.update({"external_id": " "}), "external_id must be nonblank"),
    (lambda j: j.update({"title": ""}), "title cannot be empty or whitespace-only"),
    (lambda j: j.update({"description": "   "}), "description must be nonblank")
])
def test_envelope_validation_invalid_fields(repo, valid_envelope, mutator, expected_error):
    job_repo, temp_dir = repo
    job_repo.upsert_job(Job(external_id="123", dedupe_key="h", title="T", company="C", source="jobcopilot"))
    mutator(valid_envelope["jobs"][0])
    res = _run_import(valid_envelope, job_repo, temp_dir)
    assert res["errors"] == 1
    assert expected_error in res["error_details"][0]["error"]

@pytest.mark.parametrize("bad_url, expected_error", [
    ("http://app.jobcopilot.com/applications/review/123", "Invalid JobCopilot review URL or external ID."),
    ("https://other.com/applications/review/123", "Invalid JobCopilot review URL or external ID."),
    ("https://app.jobcopilot.com/applications/review/123/extra", "Invalid JobCopilot review URL or external ID."),
    ("https://app.jobcopilot.com/applications/connect/123", "Invalid JobCopilot review URL or external ID."),
    ("https://app.jobcopilot.com/applications/review/999", "does not match external_id"),
    ("https://app.jobcopilot.com/123", "Invalid JobCopilot review URL or external ID."),
    ("https://user:pass@app.jobcopilot.com/applications/review/123", "Invalid JobCopilot review URL or external ID."),
    ("https://app.jobcopilot.com:8080/applications/review/123", "Invalid JobCopilot review URL or external ID."),
    ("https://app.jobcopilot.com/applications/review/12%2F3", "Invalid JobCopilot review URL or external ID."),
    ("https://app.jobcopilot.com/applications/review/12 3", "Invalid JobCopilot review URL or external ID."),
    ("https://app.jobcopilot.com/applications/review/123;anything", "Invalid JobCopilot review URL or external ID."),
])
def test_url_validation_rejection(repo, valid_envelope, bad_url, expected_error):
    job_repo, temp_dir = repo
    job_repo.upsert_job(Job(external_id="123", dedupe_key="h", title="T", company="C", source="jobcopilot"))
    valid_envelope["jobs"][0]["job_url"] = bad_url
    res = _run_import(valid_envelope, job_repo, temp_dir)
    assert res["errors"] == 1
    assert expected_error in res["error_details"][0]["error"]

@pytest.mark.parametrize("good_url", [
    "https://app.jobcopilot.com/applications/review/123",
    "https://app.jobcopilot.com/applications/review/123/",
    "https://app.jobcopilot.com/applications/review/123?q=1",
    "https://app.jobcopilot.com/applications/review/123#frag"
])
def test_url_validation_acceptance(repo, valid_envelope, good_url):
    job_repo, temp_dir = repo
    job_obj = Job(external_id="123", dedupe_key="h", title="T", company="C", source="jobcopilot")
    job_repo.upsert_job(job_obj)
    valid_envelope["jobs"][0]["job_url"] = good_url
    res = _run_import(valid_envelope, job_repo, temp_dir)
    assert res["errors"] == 0
    assert res["updated"] == 1
    job = job_repo.get_job(job_obj.job_id)
    assert job.job_url == "https://app.jobcopilot.com/applications/review/123"

def test_enrichment_identity_matching(repo):
    job_repo, temp_dir = repo
    job_repo.upsert_job(Job(external_id="ext1", dedupe_key="h1", title="T1", company="C1", source="jobcopilot"))
    job_repo.upsert_job(Job(external_id="ext1", dedupe_key="h2", title="T2", company="C2", source="other"))
    job_repo.upsert_job(Job(external_id="ext3", dedupe_key="h3", title="T3", company="C3", source="jobcopilot"))

    # exact source + external_id update
    data = {
        "metadata": {"export_kind": "current_job_enrichment", "source": "jobcopilot"},
        "jobs": [{"external_id": "ext1", "title": "T1-new", "company": "C1", "description": "D", "source": "jobcopilot", "job_url": "https://app.jobcopilot.com/applications/review/ext1"}]
    }
    res = _run_import(data, job_repo, temp_dir)
    assert res["updated"] == 1
    
    # unmatched enrichment does not insert
    data["jobs"][0]["external_id"] = "ext99"
    data["jobs"][0]["job_url"] = "https://app.jobcopilot.com/applications/review/ext99"
    res = _run_import(data, job_repo, temp_dir)
    assert res["errors"] == 1
    assert "Cannot enrich a non-existent job" in res["error_details"][0]["error"]
    
def test_protected_fields_and_idempotency(repo):
    job_repo, temp_dir = repo
    job = Job(
        external_id="123",
        dedupe_key="hash123",
        title="Software Engineer",
        company="Tech Corp",
        application_status="applied",
        date_applied=datetime(2023, 1, 1, tzinfo=timezone.utc),
        source="jobcopilot",
        decision="apply",
        notes="Looks good"
    )
    job_repo.upsert_job(job)
    orig_job = job_repo.get_job(job.job_id)
    
    # First Import
    data = {
        "metadata": {"export_kind": "current_job_enrichment", "source": "jobcopilot"},
        "jobs": [{
            "external_id": "123",
            "title": "Senior Software Engineer", # Changed
            "company": "Tech Corp",
            "application_status": "saved", # Should NOT overwrite "applied"
            "date_applied": None, # Should NOT overwrite real date
            "description": "New description",
            "source": "jobcopilot",
            "decision": "skip", # Should NOT overwrite
            "notes": "Bad notes", # Should NOT overwrite
            "job_url": "https://app.jobcopilot.com/applications/review/123",
            "location": "  " # Whitespace string should NOT overwrite None to " "
        }]
    }
    res = _run_import(data, job_repo, temp_dir)
    assert res["updated"] == 1
    
    updated_job = job_repo.get_job(job.job_id)
    assert updated_job.title == "Senior Software Engineer"
    assert updated_job.description == "New description"
    
    # Protected fields unchanged
    assert updated_job.job_id == orig_job.job_id
    assert updated_job.external_id == orig_job.external_id
    assert updated_job.source == orig_job.source
    assert updated_job.dedupe_key == orig_job.dedupe_key
    assert updated_job.decision == "apply"
    assert updated_job.notes == "Looks good"
    assert updated_job.created_at == orig_job.created_at
    assert updated_job.application_status == "applied"
    assert updated_job.date_applied == orig_job.date_applied
    
    # Blank handling
    assert updated_job.location is None
    
    first_updated_at = updated_job.updated_at
    
    # Second Identical Import (Idempotency)
    res = _run_import(data, job_repo, temp_dir)
    assert res["updated"] == 0
    assert res["skipped"] == 1
    
    final_job = job_repo.get_job(job.job_id)
    assert final_job.updated_at == first_updated_at

def test_unsupported_update_mode(repo):
    job_repo, _ = repo
    job = Job(external_id="123", dedupe_key="h", title="T", company="C", source="jobcopilot")
    with pytest.raises(ValueError, match="Invalid update_mode: invalid_mode"):
        job_repo.upsert_job(job, update_mode="invalid_mode")

@pytest.fixture
def valid_batch_envelope():
    return {
        "metadata": {"export_kind": "batch_enrichment", "source": "jobcopilot"},
        "jobs": [
            {
                "external_id": "100",
                "title": "T1",
                "company": "C1",
                "description": "D1",
                "source": "jobcopilot",
                "job_url": "https://app.jobcopilot.com/applications/review/100"
            },
            {
                "external_id": "200",
                "title": "T2",
                "company": "C2",
                "description": "D2",
                "source": "jobcopilot",
                "job_url": "https://app.jobcopilot.com/applications/review/200"
            }
        ]
    }

def test_batch_enrichment_two_jobs(repo, valid_batch_envelope):
    job_repo, temp_dir = repo
    j1_obj = Job(external_id="100", dedupe_key="h1", title="T1", company="C1", source="jobcopilot")
    j2_obj = Job(external_id="200", dedupe_key="h2", title="T2", company="C2", source="jobcopilot")
    job_repo.upsert_job(j1_obj)
    job_repo.upsert_job(j2_obj)
    
    res = _run_import(valid_batch_envelope, job_repo, temp_dir)
    assert res["errors"] == 0
    assert res["updated"] == 2
    
    j1 = job_repo.get_job(j1_obj.job_id)
    j2 = job_repo.get_job(j2_obj.job_id)
    assert j1.description == "D1"
    assert j2.description == "D2"

def test_batch_enrichment_rejects_empty(repo, valid_batch_envelope):
    job_repo, temp_dir = repo
    valid_batch_envelope["jobs"] = []
    with pytest.raises(ValueError, match="batch must contain between 1 and 20 jobs"):
        _run_import(valid_batch_envelope, job_repo, temp_dir)

def test_batch_enrichment_rejects_over_20(repo, valid_batch_envelope):
    job_repo, temp_dir = repo
    valid_batch_envelope["jobs"] = [valid_batch_envelope["jobs"][0].copy() for _ in range(21)]
    with pytest.raises(ValueError, match="batch must contain between 1 and 20 jobs"):
        _run_import(valid_batch_envelope, job_repo, temp_dir)
