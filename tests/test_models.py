import pytest
from pydantic import ValidationError
from applywright.models import Job

def test_valid_job_creation():
    job = Job(
        dedupe_key="123",
        title="Engineer",
        company="Acme",
        source="test",
        application_status="saved",
        decision="apply"
    )
    assert job.application_status == "saved"
    assert job.decision == "apply"

def test_invalid_application_status():
    with pytest.raises(ValidationError):
        Job(
            dedupe_key="123",
            title="Engineer",
            company="Acme",
            source="test",
            application_status="invalid_status"
        )

def test_invalid_decision():
    with pytest.raises(ValidationError):
        Job(
            dedupe_key="123",
            title="Engineer",
            company="Acme",
            source="test",
            decision="hire"
        )
