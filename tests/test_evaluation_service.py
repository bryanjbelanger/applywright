import pytest
from applywright.models import Job, ApplicationStatus, Decision
from applywright.screening.config_validator import (
    load_candidate_profile,
    load_job_scoring_policy,
    validate_evaluation_payload,
)
from applywright.screening.evaluation_service import build_evaluation_context
from applywright.server.mcp_app import (
    get_repo,
    prepare_job_evaluation,
    validate_job_evaluation,
)
import tempfile
import os
import shutil
import applywright.server.mcp_app as mcp_app


@pytest.fixture
def mcp_setup():
    fd, db_path = tempfile.mkstemp()
    os.close(fd)
    import_dir = tempfile.mkdtemp()

    old_db = mcp_app.DB_PATH
    old_import = mcp_app.IMPORT_DIR
    old_repo = mcp_app._repo

    mcp_app.DB_PATH = db_path
    mcp_app.IMPORT_DIR = import_dir
    mcp_app._repo = None

    yield db_path

    mcp_app.DB_PATH = old_db
    mcp_app.IMPORT_DIR = old_import
    mcp_app._repo = old_repo

    os.remove(db_path)
    shutil.rmtree(import_dir)


@pytest.fixture
def profile():
    return load_candidate_profile()


@pytest.fixture
def policy():
    return load_job_scoring_policy()


@pytest.fixture
def test_job():
    return Job(
        external_id="123",
        dedupe_key="abc",
        title="Software Engineer",
        company="Tech Corp",
        location="Remote",
        remote_status="Yes",
        salary="$100k",
        employment_type="Full-time",
        job_url="https://example.com/job",
        description="Looking for an engineer.",
        application_status=ApplicationStatus.SAVED,
        source="test",
        decision=Decision.REVIEW,
        notes="Some test notes",
    )


def test_build_evaluation_context(test_job, profile, policy):
    context = build_evaluation_context(test_job, profile, policy)

    # Verify exact contents
    assert context["job"]["job_id"] == test_job.job_id
    assert context["job"]["title"] == "Software Engineer"

    # IMPORTANT: verify decision and notes are excluded
    assert "decision" not in context["job"]
    assert "notes" not in context["job"]

    # Verify no timestamps or random data beyond job_id
    # Repeated calls should be identical
    context2 = build_evaluation_context(test_job, profile, policy)
    assert context == context2


def test_validate_evaluation_payload_valid_strong_recommend(profile, policy, test_job):
    payload = {
        "description_available": True,
        "campaign_id": "cloud_platform_architecture",
        "fit_score": 95,
        "recommendation": "strong_recommend",
        "hard_disqualifiers": [],
        "evidence_matches": [
            {
                "requirement": "Req 1",
                "evidence_id": "exp_10yr_it",
                "strength": "strong",
                "explanation": "Exp 1",
            },
            {
                "requirement": "Req 2",
                "evidence_id": "tech_stack_devops",
                "strength": "strong",
                "explanation": "Exp 2",
            },
            {
                "requirement": "Req 3",
                "evidence_id": "aws_tf_puppet",
                "strength": "strong",
                "explanation": "Exp 3",
            },
        ],
        "summary": "Great match",
        "strengths": ["a"],
        "gaps": ["b"],
        "uncertainties": ["c"],
        "score_breakdown": {
            "campaign_and_role_family_match": 20,
            "required_technical_skills": 25,
            "direct_career_evidence": 20,
            "seniority_and_responsibility_alignment": 10,
            "architecture_and_leadership_alignment": 10,
            "location_and_work_arrangement": 5,
            "compensation_and_employment_type": 5,
        },
    }

    result = validate_evaluation_payload(payload, profile, policy, test_job)
    assert result.recommendation == "strong_recommend"


def test_validate_evaluation_payload_duplicate_evidence_fails(
    profile, policy, test_job
):
    payload = {
        "description_available": True,
        "campaign_id": "cloud_platform_architecture",
        "fit_score": 95,
        "recommendation": "strong_recommend",
        "hard_disqualifiers": [],
        "evidence_matches": [
            {
                "requirement": "Req 1",
                "evidence_id": "exp_10yr_it",
                "strength": "strong",
                "explanation": "Exp 1",
            },
            {
                "requirement": "Req 2",
                "evidence_id": "exp_10yr_it",  # DUPLICATE
                "strength": "strong",
                "explanation": "Exp 2",
            },
        ],
        "summary": "Great match",
        "strengths": ["a"],
        "gaps": ["b"],
        "uncertainties": ["c"],
        "score_breakdown": {
            "campaign_and_role_family_match": 20,
            "required_technical_skills": 25,
            "direct_career_evidence": 20,
            "seniority_and_responsibility_alignment": 10,
            "architecture_and_leadership_alignment": 10,
            "location_and_work_arrangement": 5,
            "compensation_and_employment_type": 5,
        },
    }

    with pytest.raises(ValueError, match="duplicate evidence_id found"):
        validate_evaluation_payload(payload, profile, policy, test_job)


def test_validate_evaluation_payload_zero_credit_rules(profile, policy, test_job):
    # Strip test_job location and compensation fields
    test_job.location = None
    test_job.remote_status = None
    test_job.salary = None
    test_job.employment_type = None

    payload = {
        "description_available": True,
        "campaign_id": "cloud_platform_architecture",
        "fit_score": 95,
        "recommendation": "strong_recommend",
        "hard_disqualifiers": [],
        "evidence_matches": [
            {
                "requirement": "Req 1",
                "evidence_id": "exp_10yr_it",
                "strength": "strong",
                "explanation": "Exp 1",
            },
            {
                "requirement": "Req 2",
                "evidence_id": "tech_stack_devops",
                "strength": "strong",
                "explanation": "Exp 2",
            },
            {
                "requirement": "Req 3",
                "evidence_id": "aws_tf_puppet",
                "strength": "strong",
                "explanation": "Exp 3",
            },
        ],
        "summary": "Great match",
        "strengths": ["a"],
        "gaps": ["b"],
        "uncertainties": ["c"],
        "score_breakdown": {
            "campaign_and_role_family_match": 20,
            "required_technical_skills": 25,
            "direct_career_evidence": 20,
            "seniority_and_responsibility_alignment": 10,
            "architecture_and_leadership_alignment": 10,
            "location_and_work_arrangement": 5,  # INVALID positive credit when both are null
            "compensation_and_employment_type": 5,
        },
    }

    with pytest.raises(ValueError, match="location and remote_status are null"):
        validate_evaluation_payload(payload, profile, policy, test_job)


def test_validate_evaluation_payload_blocked(profile, policy, test_job):
    test_job.description = None
    payload = {
        "description_available": False,
        "campaign_id": None,
        "fit_score": None,
        "recommendation": "blocked",
        "hard_disqualifiers": [],
        "evidence_matches": [],
        "summary": "Missing description",
        "strengths": [],
        "gaps": [],
        "uncertainties": ["We don't know anything because there's no description"],
        "score_breakdown": None,
    }

    result = validate_evaluation_payload(payload, profile, policy, test_job)
    assert result.recommendation == "blocked"


def test_validate_evaluation_payload_blocked_rejects_scored_fields(
    profile, policy, test_job
):
    test_job.description = None
    payload = {
        "description_available": False,
        "campaign_id": "cloud_platform_architecture",  # Invalid for blocked
        "fit_score": None,
        "recommendation": "blocked",
        "hard_disqualifiers": [],
        "evidence_matches": [],
        "summary": "Missing description",
        "strengths": [],
        "gaps": [],
        "uncertainties": ["We don't know anything because there's no description"],
        "score_breakdown": None,
    }

    with pytest.raises(ValueError, match="Schema validation failed"):
        validate_evaluation_payload(payload, profile, policy, test_job)


def test_validate_evaluation_payload_mismatched_recommendation(
    profile, policy, test_job
):
    payload = {
        "description_available": True,
        "campaign_id": "cloud_platform_architecture",
        "fit_score": 95,
        "recommendation": "recommend",  # 95 should be strong_recommend!
        "hard_disqualifiers": [],
        "evidence_matches": [
            {
                "requirement": "Req 1",
                "evidence_id": "exp_10yr_it",
                "strength": "strong",
                "explanation": "Exp 1",
            },
            {
                "requirement": "Req 2",
                "evidence_id": "tech_stack_devops",
                "strength": "strong",
                "explanation": "Exp 2",
            },
            {
                "requirement": "Req 3",
                "evidence_id": "aws_tf_puppet",
                "strength": "strong",
                "explanation": "Exp 3",
            },
        ],
        "summary": "Great match",
        "strengths": ["a"],
        "gaps": ["b"],
        "uncertainties": ["c"],
        "score_breakdown": {
            "campaign_and_role_family_match": 20,
            "required_technical_skills": 25,
            "direct_career_evidence": 20,
            "seniority_and_responsibility_alignment": 10,
            "architecture_and_leadership_alignment": 10,
            "location_and_work_arrangement": 5,
            "compensation_and_employment_type": 5,
        },
    }

    with pytest.raises(
        ValueError,
        match="Recommendation mismatch. Derived canonical recommendation is 'strong_recommend', but payload proposed 'recommend'",
    ):
        validate_evaluation_payload(payload, profile, policy, test_job)


def test_prepare_and_validate_no_side_effects(test_job, mcp_setup):
    repo = get_repo()
    repo.upsert_job(test_job)

    # Store state before
    before = repo.get_job(test_job.job_id).model_dump(mode="json")

    res1 = prepare_job_evaluation(test_job.job_id)
    assert res1["ok"]

    payload = {
        "description_available": True,
        "campaign_id": "cloud_platform_architecture",
        "fit_score": 95,
        "recommendation": "strong_recommend",
        "hard_disqualifiers": [],
        "evidence_matches": [
            {
                "requirement": "Req 1",
                "evidence_id": "exp_10yr_it",
                "strength": "strong",
                "explanation": "Exp 1",
            },
            {
                "requirement": "Req 2",
                "evidence_id": "tech_stack_devops",
                "strength": "strong",
                "explanation": "Exp 2",
            },
            {
                "requirement": "Req 3",
                "evidence_id": "aws_tf_puppet",
                "strength": "strong",
                "explanation": "Exp 3",
            },
        ],
        "summary": "Great match",
        "strengths": ["a"],
        "gaps": ["b"],
        "uncertainties": ["c"],
        "score_breakdown": {
            "campaign_and_role_family_match": 20,
            "required_technical_skills": 25,
            "direct_career_evidence": 20,
            "seniority_and_responsibility_alignment": 10,
            "architecture_and_leadership_alignment": 10,
            "location_and_work_arrangement": 5,
            "compensation_and_employment_type": 5,
        },
    }

    res2 = validate_job_evaluation(test_job.job_id, payload)
    assert res2["ok"]

    # Store state after
    after = repo.get_job(test_job.job_id).model_dump(mode="json")

    # Assert completely identical
    assert before == after


def test_blocked_context_schema(test_job):
    test_job.description = None
    from applywright.screening.evaluation_service import build_evaluation_context
    from applywright.screening.config_validator import load_candidate_profile, load_job_scoring_policy
    
    ctx = build_evaluation_context(test_job, load_candidate_profile(), load_job_scoring_policy())
    
    assert ctx["payload_kind"] == "blocked"
    assert "BlockedEvaluationPayload" in str(ctx["expected_output_schema"])
    assert any("This job has no description" in i for i in ctx["instructions"])

def test_scored_context_schema(test_job):
    test_job.description = "Some description"
    from applywright.screening.evaluation_service import build_evaluation_context
    from applywright.screening.config_validator import load_candidate_profile, load_job_scoring_policy
    
    ctx = build_evaluation_context(test_job, load_candidate_profile(), load_job_scoring_policy())
    
    assert ctx["payload_kind"] == "scored"
    assert "ScoredEvaluationPayload" in str(ctx["expected_output_schema"])
    assert not any("This job has no description" in i for i in ctx["instructions"])

def test_nonexistent_job_mcp(mcp_setup):
    from applywright.server.mcp_app import prepare_job_evaluation, validate_job_evaluation
    res_prep = prepare_job_evaluation("nonexistent")
    assert res_prep["ok"] is False
    assert res_prep["error_code"] == "job_not_found"
    
    res_val = validate_job_evaluation("nonexistent", {})
    assert res_val["ok"] is False
    assert res_val["error_code"] == "job_not_found"

def test_extra_fields_rejected_mcp(test_job, mcp_setup):
    from applywright.server.mcp_app import get_repo, validate_job_evaluation
    test_job.description = "Desc"
    get_repo().upsert_job(test_job)
    
    payload = {
        "description_available": True,
        "campaign_id": "cloud_platform_architecture",
        "score_breakdown": {
            "campaign_and_role_family_match": 20,
            "required_technical_skills": 25,
            "direct_career_evidence": 20,
            "seniority_and_responsibility_alignment": 10,
            "architecture_and_leadership_alignment": 10,
            "location_and_work_arrangement": 10,
            "compensation_and_employment_type": 5
        },
        "fit_score": 100,
        "recommendation": "recommend",
        "hard_disqualifiers": [],
        "evidence_matches": [],
        "summary": "foo",
        "strengths": ["s"],
        "gaps": ["g"],
        "uncertainties": ["u"],
        "extra_unknown_field": "bad"
    }
    
    res = validate_job_evaluation(test_job.job_id, payload)
    assert res["ok"] is False
    assert res["error_code"] == "payload_schema_error"
    assert "extra_unknown_field" not in res["error"]

def test_repeated_prepare_identical(test_job, mcp_setup):
    from applywright.server.mcp_app import get_repo, prepare_job_evaluation
    get_repo().upsert_job(test_job)
    
    res1 = prepare_job_evaluation(test_job.job_id)
    res2 = prepare_job_evaluation(test_job.job_id)
    
    assert res1["ok"] is True
    assert res2["ok"] is True
    assert res1["evaluation_context"] == res2["evaluation_context"]

def test_no_write_check_fields(test_job, mcp_setup):
    from applywright.server.mcp_app import get_repo, prepare_job_evaluation
    repo = get_repo()
    test_job.decision = "review"
    test_job.notes = "initial"
    repo.upsert_job(test_job)
    
    before = repo.get_job(test_job.job_id).model_dump(mode="json")
    
    res = prepare_job_evaluation(test_job.job_id)
    assert res["ok"] is True
    
    after = repo.get_job(test_job.job_id).model_dump(mode="json")
    
    assert before["updated_at"] == after["updated_at"]
    assert before["decision"] == after["decision"]
    assert before["notes"] == after["notes"]
    assert before["application_status"] == after["application_status"]
    assert before["date_applied"] == after["date_applied"]


def test_configuration_failures_safe_mcp_errors(test_job, mcp_setup, monkeypatch):
    from applywright.server.mcp_app import get_repo, prepare_job_evaluation, validate_job_evaluation
    get_repo().upsert_job(test_job)
    
    def mock_load(*args, **kwargs):
        raise ValueError("MY_SECRET_FILE_PATH_DO_NOT_LEAK")
    
    monkeypatch.setattr("applywright.screening.config_validator.load_candidate_profile", mock_load)
    
    res_prep = prepare_job_evaluation(test_job.job_id)
    assert res_prep["ok"] is False
    assert res_prep["error_code"] == "configuration_error"
    assert "The evaluation configuration could not be loaded." in res_prep["error"]
    assert "MY_SECRET_FILE_PATH_DO_NOT_LEAK" not in res_prep["error"]
    
    res_val = validate_job_evaluation(test_job.job_id, {})
    assert res_val["ok"] is False
    assert res_val["error_code"] == "configuration_error"
    assert "The evaluation configuration could not be loaded." in res_val["error"]
    assert "MY_SECRET_FILE_PATH_DO_NOT_LEAK" not in res_val["error"]

def test_schema_failures_safe_mcp_errors(test_job, mcp_setup):
    from applywright.server.mcp_app import get_repo, validate_job_evaluation
    get_repo().upsert_job(test_job)
    
    payload = {
        "description_available": True,
        "SECRET_KEY": "DO_NOT_LEAK_ME"
    }
    
    res = validate_job_evaluation(test_job.job_id, payload)
    assert res["ok"] is False
    assert res["error_code"] == "payload_schema_error"
    assert "The evaluation payload does not match the required schema." in res["error"]
    assert "DO_NOT_LEAK_ME" not in res["error"]
