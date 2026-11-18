import os
import json
from applywright.server import mcp_app


def test_import_jobs(mcp_setup):
    db_path, import_dir = mcp_setup
    
    json_path = os.path.join(import_dir, "jobs.json")
    with open(json_path, "w") as f:
        json.dump([
            {"title": "Dev", "company": "A"},
            {"title": "QA", "company": "B"}
        ], f)
        
    res = mcp_app.import_jobs(json_path)
    assert res.get("ok") is True
    assert res["created"] == 2
    assert res["total_received"] == 2

def test_list_jobs_and_get_job(mcp_setup):
    db_path, import_dir = mcp_setup
    
    # Pre-populate using import_jobs
    json_path = os.path.join(import_dir, "jobs.json")
    with open(json_path, "w") as f:
        json.dump([
            {"title": "Frontend", "company": "Acme", "source": "src1"},
            {"title": "Backend", "company": "Beta", "source": "src2"}
        ], f)
    mcp_app.import_jobs(json_path)
    
    # Test list_jobs
    jobs = mcp_app.list_jobs()
    assert len(jobs) == 2
    
    # Filter
    filtered = mcp_app.list_jobs(source="src1")
    assert len(filtered) == 1
    assert filtered[0]["title"] == "Frontend"
    
    # Test get_job
    job_id = filtered[0]["job_id"]
    job = mcp_app.get_job(job_id)
    assert job is not None
    assert job["title"] == "Frontend"

def test_mark_job(mcp_setup):
    db_path, import_dir = mcp_setup
    
    json_path = os.path.join(import_dir, "jobs.json")
    with open(json_path, "w") as f:
        json.dump([{"title": "Dev", "company": "A"}], f)
    mcp_app.import_jobs(json_path)
    
    jobs = mcp_app.list_jobs()
    job_id = jobs[0]["job_id"]
    
    # Mark job
    res = mcp_app.mark_job(job_id, decision="apply", notes="Good one")
    assert res.get("ok") is True
    
    job = mcp_app.get_job(job_id)
    assert job["decision"] == "apply"
    assert job["notes"] == "Good one"
    
    # Mark job with invalid decision
    res = mcp_app.mark_job(job_id, decision="invalid_decision")
    assert res.get("ok") is False
    assert "Invalid decision" in res["error"]
    
    # Ensure it wasn't corrupted
    job = mcp_app.get_job(job_id)
    assert job["decision"] == "apply"
