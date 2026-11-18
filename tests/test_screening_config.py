import os
import pytest
from applywright.models import Job
from pydantic import ValidationError
from applywright.screening.config_validator import (
    load_candidate_profile,
    load_job_scoring_policy,
    JobScoringPolicy,
    CandidateProfile,
    EvaluationPayload,
    validate_evaluation_payload,
)

CONFIG_DIR = os.path.join(os.path.dirname(__file__), "..", "config")
CANDIDATE_PROFILE_PATH = os.path.join(CONFIG_DIR, "candidate_profile.example.yaml")
JOB_SCORING_POLICY_PATH = os.path.join(CONFIG_DIR, "job_scoring_policy.example.yaml")


def EvaluationPayload_(**kwargs):
    import pydantic

    if "description_available" in kwargs:
        if kwargs["description_available"] is True:
            kwargs.setdefault("campaign_id", "cloud_platform_architecture")
            fit = kwargs.get("fit_score", 80)
            if isinstance(fit, int):
                kwargs.setdefault(
                    "score_breakdown",
                    {
                        "campaign_and_role_family_match": min(fit, 20),
                        "required_technical_skills": max(0, min(fit - 20, 25)),
                        "direct_career_evidence": max(0, min(fit - 45, 20)),
                        "seniority_and_responsibility_alignment": max(
                            0, min(fit - 65, 10)
                        ),
                        "architecture_and_leadership_alignment": max(
                            0, min(fit - 75, 10)
                        ),
                        "location_and_work_arrangement": max(0, min(fit - 85, 10)),
                        "compensation_and_employment_type": max(0, min(fit - 95, 5)),
                    },
                )
            else:
                kwargs.setdefault(
                    "score_breakdown",
                    {
                        "campaign_and_role_family_match": 20,
                        "required_technical_skills": 25,
                        "direct_career_evidence": 20,
                        "seniority_and_responsibility_alignment": 10,
                        "architecture_and_leadership_alignment": 10,
                        "location_and_work_arrangement": 10,
                        "compensation_and_employment_type": 5,
                    },
                )
            kwargs.setdefault("summary", "Summary")
            kwargs.setdefault("strengths", ["a"])
            kwargs.setdefault("gaps", ["b"])
            kwargs.setdefault("uncertainties", ["c"])
        elif kwargs["description_available"] is False:
            kwargs.setdefault("campaign_id", None)
            kwargs.setdefault("score_breakdown", None)
            kwargs.setdefault("summary", "Summary")
            kwargs.setdefault("strengths", [])
            kwargs.setdefault("gaps", [])
            kwargs.setdefault("uncertainties", ["c"])

    return pydantic.TypeAdapter(EvaluationPayload).validate_python(kwargs)


def test_valid_checked_in_candidate_profile():
    profile = load_candidate_profile(CANDIDATE_PROFILE_PATH)
    assert profile.schema_version == 1


def test_valid_checked_in_scoring_policy():
    policy = load_job_scoring_policy(JOB_SCORING_POLICY_PATH)
    assert policy.schema_version == 1


def _get_base_policy_dict():
    return {
        "schema_version": 1,
        "scoring_weights": {
            "campaign_and_role_family_match": 20,
            "required_technical_skills": 25,
            "direct_career_evidence": 20,
            "seniority_and_responsibility_alignment": 10,
            "architecture_and_leadership_alignment": 10,
            "location_and_work_arrangement": 10,
            "compensation_and_employment_type": 5,
        },
        "overrides": {"missing_description": "blocked", "hard_disqualifier": "reject"},
        "score_thresholds": [
            {"min_score": 90, "max_score": 100, "decision": "strong_recommend"},
            {"min_score": 82, "max_score": 89, "decision": "recommend"},
            {"min_score": 72, "max_score": 81, "decision": "manual_review"},
            {"min_score": 0, "max_score": 71, "decision": "reject"},
        ],
    }


# 1. Weights
def test_valid_individual_weights_totaling_100():
    JobScoringPolicy(**_get_base_policy_dict())


def test_negative_weight_with_total_still_100():
    d = _get_base_policy_dict()
    d["scoring_weights"]["campaign_and_role_family_match"] = -10
    d["scoring_weights"]["required_technical_skills"] = 55
    with pytest.raises(ValidationError):
        JobScoringPolicy(**d)


def test_weight_above_100_with_compensating_negative_value():
    d = _get_base_policy_dict()
    d["scoring_weights"]["campaign_and_role_family_match"] = 110
    d["scoring_weights"]["required_technical_skills"] = -10
    with pytest.raises(ValidationError):
        JobScoringPolicy(**d)


def test_total_99():
    d = _get_base_policy_dict()
    d["scoring_weights"]["campaign_and_role_family_match"] = 19
    with pytest.raises(ValidationError, match="Total scoring weight must equal 100"):
        JobScoringPolicy(**d)


def test_total_101():
    d = _get_base_policy_dict()
    d["scoring_weights"]["campaign_and_role_family_match"] = 21
    with pytest.raises(ValidationError, match="Total scoring weight must equal 100"):
        JobScoringPolicy(**d)


# 2. Strict Types and Coercion
def test_string_schema_version():
    d = _get_base_policy_dict()
    d["schema_version"] = "1"
    with pytest.raises(ValidationError):
        JobScoringPolicy(**d)


def test_string_scoring_weight():
    d = _get_base_policy_dict()
    d["scoring_weights"]["campaign_and_role_family_match"] = "20"
    with pytest.raises(ValidationError):
        JobScoringPolicy(**d)


def test_boolean_scoring_weight():
    d = _get_base_policy_dict()
    d["scoring_weights"]["campaign_and_role_family_match"] = True
    with pytest.raises(ValidationError):
        JobScoringPolicy(**d)


def test_float_scoring_weight():
    d = _get_base_policy_dict()
    d["scoring_weights"]["campaign_and_role_family_match"] = 20.0
    with pytest.raises(ValidationError):
        JobScoringPolicy(**d)


def test_string_threshold_bound():
    d = _get_base_policy_dict()
    d["score_thresholds"][-1]["max_score"] = "71"
    with pytest.raises(ValidationError):
        JobScoringPolicy(**d)


def test_float_threshold_bound():
    d = _get_base_policy_dict()
    d["score_thresholds"][-1]["max_score"] = 71.0
    with pytest.raises(ValidationError):
        JobScoringPolicy(**d)


# 3. Threshold Policy
def test_exact_valid_mappings_in_normal_order():
    JobScoringPolicy(**_get_base_policy_dict())


def test_exact_valid_mappings_in_different_order():
    d = _get_base_policy_dict()
    d["score_thresholds"] = [
        {"min_score": 72, "max_score": 81, "decision": "manual_review"},
        {"min_score": 0, "max_score": 71, "decision": "reject"},
        {"min_score": 90, "max_score": 100, "decision": "strong_recommend"},
        {"min_score": 82, "max_score": 89, "decision": "recommend"},
    ]
    JobScoringPolicy(**d)


def test_wrong_decision_on_correct_range():
    d = _get_base_policy_dict()
    d["score_thresholds"][0]["decision"] = "recommend"
    with pytest.raises(ValidationError):
        JobScoringPolicy(**d)


def test_wrong_range_for_correct_decision():
    d = _get_base_policy_dict()
    d["score_thresholds"][0]["min_score"] = 91
    with pytest.raises(ValidationError):
        JobScoringPolicy(**d)


def test_extra_split_range():
    d = _get_base_policy_dict()
    d["score_thresholds"].pop()  # remove 0-71
    d["score_thresholds"].append(
        {"min_score": 0, "max_score": 35, "decision": "reject"}
    )
    d["score_thresholds"].append(
        {"min_score": 36, "max_score": 71, "decision": "reject"}
    )
    with pytest.raises(ValidationError):
        JobScoringPolicy(**d)


def test_missing_range():
    d = _get_base_policy_dict()
    d["score_thresholds"].pop()
    with pytest.raises(
        ValidationError, match="Fewer than four threshold ranges provided"
    ):
        JobScoringPolicy(**d)


def test_duplicated_range():
    d = _get_base_policy_dict()
    d["score_thresholds"].append(d["score_thresholds"][0])
    with pytest.raises(ValidationError, match="Duplicated decision range"):
        JobScoringPolicy(**d)


def test_duplicated_decision():
    d = _get_base_policy_dict()
    d["score_thresholds"][0]["decision"] = "recommend"
    with pytest.raises(ValidationError):
        JobScoringPolicy(**d)


def test_overlap():
    d = _get_base_policy_dict()
    d["score_thresholds"][0]["min_score"] = 89
    with pytest.raises(ValidationError):
        JobScoringPolicy(**d)


def test_gap():
    d = _get_base_policy_dict()
    d["score_thresholds"][1]["max_score"] = 88
    with pytest.raises(ValidationError):
        JobScoringPolicy(**d)


# --- Evaluation Payload Tests ---


def _valid_evidence(id="e1"):
    return {
        "requirement": "req",
        "evidence_id": id,
        "strength": "strong",
        "explanation": "exp",
    }


def _get_base_profile_dict():
    return {
        "schema_version": 1,
        "campaigns": [
            {"id": "cloud_platform_architecture", "name": "c"},
            {"id": "devops_sre_automation", "name": "c"},
            {"id": "enterprise_platform_automation", "name": "c"},
        ],
        "evidence_items": [
            {"evidence_id": "e1", "description": "e1"},
            {"evidence_id": "e2", "description": "e2"},
            {"evidence_id": "e3", "description": "e3"},
        ],
        "hard_disqualifiers": [
            {"disqualifier_id": "d1", "description": "d1"},
            {"disqualifier_id": "d2", "description": "d2"},
        ],
    }


# Missing descriptions
def test_valid_blocked_evaluation_with_fit_score_null():
    EvaluationPayload_(
        description_available=False,
        recommendation="blocked",
        fit_score=None,
        hard_disqualifiers=[],
        evidence_matches=[],
    )


def test_blocked_with_available_description():
    with pytest.raises(ValidationError):
        EvaluationPayload_(
            description_available=True,
            recommendation="blocked",
            fit_score=None,
            hard_disqualifiers=[],
            evidence_matches=[],
        )


def test_blocked_with_numeric_fit_score():
    with pytest.raises(ValidationError):
        EvaluationPayload_(
            description_available=False,
            recommendation="blocked",
            fit_score=0,
            hard_disqualifiers=[],
            evidence_matches=[],
        )


def test_missing_description_with_reject():
    with pytest.raises(ValidationError):
        EvaluationPayload_(
            description_available=False,
            recommendation="reject",
            fit_score=None,
            hard_disqualifiers=[],
            evidence_matches=[],
        )


def test_missing_description_with_manual_review():
    with pytest.raises(ValidationError):
        EvaluationPayload_(
            description_available=False,
            recommendation="manual_review",
            fit_score=None,
            hard_disqualifiers=[],
            evidence_matches=[],
        )


def test_missing_description_with_recommend():
    with pytest.raises(ValidationError):
        EvaluationPayload_(
            description_available=False,
            recommendation="recommend",
            fit_score=None,
            hard_disqualifiers=[],
            evidence_matches=[],
        )


def test_missing_description_with_strong_recommend():
    with pytest.raises(ValidationError):
        EvaluationPayload_(
            description_available=False,
            recommendation="strong_recommend",
            fit_score=None,
            hard_disqualifiers=[],
            evidence_matches=[],
        )


def test_available_description_with_fit_score_null():
    with pytest.raises(ValidationError):
        EvaluationPayload_(
            description_available=True,
            recommendation="reject",
            fit_score=None,
            hard_disqualifiers=[],
            evidence_matches=[],
        )


# Evidence mappings
def test_three_valid_distinct_structured_evidence_mappings():
    EvaluationPayload_(
        description_available=True,
        fit_score=85,
        recommendation="recommend",
        hard_disqualifiers=[],
        evidence_matches=[
            _valid_evidence("e1"),
            _valid_evidence("e2"),
            _valid_evidence("e3"),
        ],
    )


def test_one_evidence_id_repeated_three_times():
    with pytest.raises(ValidationError):
        EvaluationPayload_(
            description_available=True,
            fit_score=85,
            recommendation="recommend",
            hard_disqualifiers=[],
            evidence_matches=[
                _valid_evidence("e1"),
                _valid_evidence("e1"),
                _valid_evidence("e1"),
            ],
        )


def test_two_distinct_ids_across_three_entries():
    with pytest.raises(ValidationError):
        EvaluationPayload_(
            description_available=True,
            fit_score=85,
            recommendation="recommend",
            hard_disqualifiers=[],
            evidence_matches=[
                _valid_evidence("e1"),
                _valid_evidence("e1"),
                _valid_evidence("e2"),
            ],
        )


def test_unknown_evidence_id():
    profile = CandidateProfile(**_get_base_profile_dict())
    p = EvaluationPayload_(
        description_available=True,
        fit_score=85,
        recommendation="recommend",
        hard_disqualifiers=[],
        evidence_matches=[
            _valid_evidence("e1"),
            _valid_evidence("e2"),
            _valid_evidence("unknown"),
        ],
    )
    with pytest.raises(ValueError, match="Unknown evidence ID: unknown"):
        validate_evaluation_payload(
            p,
            profile,
            load_job_scoring_policy(JOB_SCORING_POLICY_PATH),
            Job(
                dedupe_key="abc",
                title="A",
                company="B",
                source="C",
                location="L",
                salary="S",
                description="Test"
            ),
        )


def test_invalid_strength():
    with pytest.raises(ValidationError):
        _valid_evidence()["strength"] = "foo"
        EvaluationPayload_(
            description_available=True,
            fit_score=75,
            recommendation="manual_review",
            hard_disqualifiers=[],
            evidence_matches=[
                {
                    "requirement": "req",
                    "evidence_id": "e1",
                    "strength": "foo",
                    "explanation": "exp",
                }
            ],
        )


def test_empty_requirement():
    with pytest.raises(ValidationError):
        EvaluationPayload_(
            description_available=True,
            fit_score=75,
            recommendation="manual_review",
            hard_disqualifiers=[],
            evidence_matches=[
                {
                    "requirement": "",
                    "evidence_id": "e1",
                    "strength": "strong",
                    "explanation": "exp",
                }
            ],
        )


def test_whitespace_only_requirement():
    with pytest.raises(ValidationError):
        EvaluationPayload_(
            description_available=True,
            fit_score=75,
            recommendation="manual_review",
            hard_disqualifiers=[],
            evidence_matches=[
                {
                    "requirement": "   ",
                    "evidence_id": "e1",
                    "strength": "strong",
                    "explanation": "exp",
                }
            ],
        )


def test_empty_explanation():
    with pytest.raises(ValidationError):
        EvaluationPayload_(
            description_available=True,
            fit_score=75,
            recommendation="manual_review",
            hard_disqualifiers=[],
            evidence_matches=[
                {
                    "requirement": "r",
                    "evidence_id": "e1",
                    "strength": "strong",
                    "explanation": "",
                }
            ],
        )


def test_whitespace_only_explanation():
    with pytest.raises(ValidationError):
        EvaluationPayload_(
            description_available=True,
            fit_score=75,
            recommendation="manual_review",
            hard_disqualifiers=[],
            evidence_matches=[
                {
                    "requirement": "r",
                    "evidence_id": "e1",
                    "strength": "strong",
                    "explanation": "   ",
                }
            ],
        )


# Hard disqualifiers
def test_known_hard_disqualifier():
    profile = CandidateProfile(**_get_base_profile_dict())
    p = EvaluationPayload_(
        description_available=True,
        fit_score=50,
        recommendation="reject",
        hard_disqualifiers=["d1"],
        evidence_matches=[],
    )
    assert validate_evaluation_payload(
        p,
        profile,
        load_job_scoring_policy(JOB_SCORING_POLICY_PATH),
        Job(
            dedupe_key="abc",
            title="A",
            company="B",
            source="C",
            location="L",
            salary="S",
            description="Test description",
        ),
    )


def test_unknown_hard_disqualifier():
    profile = CandidateProfile(**_get_base_profile_dict())
    p = EvaluationPayload_(
        description_available=True,
        fit_score=50,
        recommendation="reject",
        hard_disqualifiers=["unknown"],
        evidence_matches=[],
    )
    with pytest.raises(ValueError, match="Unknown hard disqualifier ID: unknown"):
        validate_evaluation_payload(
            p,
            profile,
            load_job_scoring_policy(JOB_SCORING_POLICY_PATH),
            Job(
                dedupe_key="abc",
                title="A",
                company="B",
                source="C",
                location="L",
                salary="S",
                description="Test"
            ),
        )


def test_duplicated_hard_disqualifier_id():
    with pytest.raises(ValidationError, match="contains duplicate IDs"):
        EvaluationPayload_(
            description_available=True,
            fit_score=50,
            recommendation="reject",
            hard_disqualifiers=["d1", "d1"],
            evidence_matches=[],
        )


def test_high_score_with_hard_disqualifier_and_reject():
    EvaluationPayload_(
        description_available=True,
        fit_score=99,
        recommendation="reject",
        hard_disqualifiers=["d1"],
        evidence_matches=[],
    )


def test_high_score_with_hard_disqualifier_and_recommendation():
    p = EvaluationPayload_(
        description_available=True,
        fit_score=99,
        recommendation="recommend",
        hard_disqualifiers=["d1"],
        evidence_matches=[],
    )
    with pytest.raises(ValueError, match="Recommendation mismatch"):
        profile = CandidateProfile(**_get_base_profile_dict())
        validate_evaluation_payload(
            p,
            profile,
            load_job_scoring_policy(JOB_SCORING_POLICY_PATH),
            Job(
                dedupe_key="abc",
                title="A",
                company="B",
                source="C",
                location="L",
                salary="S",
                description="Test"
            ),
        )


# Strict types (EvaluationPayload)
def test_numeric_string_for_fit_score():
    with pytest.raises(ValidationError):
        EvaluationPayload_(
            description_available=True,
            fit_score="82",
            recommendation="recommend",
            hard_disqualifiers=[],
            evidence_matches=[
                _valid_evidence("e1"),
                _valid_evidence("e2"),
                _valid_evidence("e3"),
            ],
        )


def test_float_fit_score():
    with pytest.raises(ValidationError):
        EvaluationPayload_(
            description_available=True,
            fit_score=82.0,
            recommendation="recommend",
            hard_disqualifiers=[],
            evidence_matches=[
                _valid_evidence("e1"),
                _valid_evidence("e2"),
                _valid_evidence("e3"),
            ],
        )


def test_boolean_fit_score():
    with pytest.raises(ValidationError):
        EvaluationPayload_(
            description_available=True,
            fit_score=True,
            recommendation="reject",
            hard_disqualifiers=[],
            evidence_matches=[],
        )


def test_string_description_available():
    with pytest.raises(ValidationError):
        EvaluationPayload_(
            description_available="true",
            fit_score=None,
            recommendation="blocked",
            hard_disqualifiers=[],
            evidence_matches=[],
        )


def test_integer_description_available():
    with pytest.raises(ValidationError):
        EvaluationPayload_(
            description_available=1,
            fit_score=50,
            recommendation="reject",
            hard_disqualifiers=[],
            evidence_matches=[],
        )


def test_blocked_missing_campaign_id():
    import pydantic
    from applywright.screening.config_validator import EvaluationPayload
    with pytest.raises(pydantic.ValidationError) as exc:
        pydantic.TypeAdapter(EvaluationPayload).validate_python(dict(
            description_available=False,
            recommendation="blocked",
            hard_disqualifiers=[],
            evidence_matches=[],
            # campaign_id missing
            score_breakdown=None,
            fit_score=None,
            summary="missing",
            strengths=[],
            gaps=[],
            uncertainties=["missing"]
        ))
    assert "campaign_id" in str(exc.value)

def test_blocked_missing_score_breakdown():
    import pydantic
    from applywright.screening.config_validator import EvaluationPayload
    with pytest.raises(pydantic.ValidationError) as exc:
        pydantic.TypeAdapter(EvaluationPayload).validate_python(dict(
            description_available=False,
            recommendation="blocked",
            hard_disqualifiers=[],
            evidence_matches=[],
            campaign_id=None,
            # score_breakdown missing
            fit_score=None,
            summary="missing",
            strengths=[],
            gaps=[],
            uncertainties=["missing"]
        ))
    assert "score_breakdown" in str(exc.value)

def test_blocked_missing_fit_score():
    import pydantic
    from applywright.screening.config_validator import EvaluationPayload
    with pytest.raises(pydantic.ValidationError) as exc:
        pydantic.TypeAdapter(EvaluationPayload).validate_python(dict(
            description_available=False,
            recommendation="blocked",
            hard_disqualifiers=[],
            evidence_matches=[],
            campaign_id=None,
            score_breakdown=None,
            # fit_score missing
            summary="missing",
            strengths=[],
            gaps=[],
            uncertainties=["missing"]
        ))
    assert "fit_score" in str(exc.value)

def test_description_state_mismatches():
    # Stored job has description, payload says false
    job_with_desc = Job(dedupe_key="abc", title="A", company="B", source="C", description="Has text")
    profile = CandidateProfile(**_get_base_profile_dict())
    policy = JobScoringPolicy(**_get_base_policy_dict())
    
    p = {
        "description_available": False,
        "campaign_id": None,
        "score_breakdown": None,
        "fit_score": None,
        "recommendation": "blocked",
        "hard_disqualifiers": [],
        "evidence_matches": [],
        "summary": "foo",
        "strengths": [],
        "gaps": [],
        "uncertainties": ["u"]
    }
    
    with pytest.raises(ValueError, match="stored job has description, payload says false"):
        validate_evaluation_payload(p, profile, policy, job_with_desc)
        
    # Stored job lacks description, payload says true
    job_no_desc = Job(dedupe_key="abc", title="A", company="B", source="C", description=None)
    p2 = {
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
        "uncertainties": ["u"]
    }
    with pytest.raises(ValueError, match="stored job lacks description, payload says true"):
        validate_evaluation_payload(p2, profile, policy, job_no_desc)

def test_compensation_positive_score_rejected_independently():
    # Location is known (not null), but compensation is null
    job = Job(dedupe_key="abc", title="A", company="B", source="C", description="Text", location="Known", salary=None, employment_type=None)
    profile = CandidateProfile(**_get_base_profile_dict())
    policy = JobScoringPolicy(**_get_base_policy_dict())
    
    p = {
        "description_available": True,
        "campaign_id": "cloud_platform_architecture",
        "score_breakdown": {
            "campaign_and_role_family_match": 20,
            "required_technical_skills": 25,
            "direct_career_evidence": 20,
            "seniority_and_responsibility_alignment": 10,
            "architecture_and_leadership_alignment": 10,
            "location_and_work_arrangement": 10,
            "compensation_and_employment_type": 5 # POSITIVE!
        },
        "fit_score": 100,
        "recommendation": "recommend",
        "hard_disqualifiers": [],
        "evidence_matches": [],
        "summary": "foo",
        "strengths": ["s"],
        "gaps": ["g"],
        "uncertainties": ["u"]
    }
    
    with pytest.raises(ValueError, match="salary and employment_type are null; compensation_and_employment_type score must be 0"):
        validate_evaluation_payload(p, profile, policy, job)

def test_config_loading_succeeds_outside_repo(monkeypatch, tmp_path):
    import os
    from applywright.screening.config_validator import load_candidate_profile
    monkeypatch.chdir(tmp_path)
    # The default loading relies on __file__ to locate config, so it should succeed regardless of cwd
    profile = load_candidate_profile()
    assert profile.schema_version == 1



def test_missing_description_available_returns_schema_error():
    from applywright.screening.config_validator import validate_evaluation_payload
    job = Job(dedupe_key="abc", title="A", company="B", source="C", description="Has text")
    profile = CandidateProfile(**_get_base_profile_dict())
    policy = JobScoringPolicy(**_get_base_policy_dict())
    
    with pytest.raises(ValueError, match="Schema validation failed"):
        validate_evaluation_payload({
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
            "uncertainties": ["u"]
        }, profile, policy, job)

def test_string_false_description_available_returns_schema_error():
    from applywright.screening.config_validator import validate_evaluation_payload
    job = Job(dedupe_key="abc", title="A", company="B", source="C", description="Has text")
    profile = CandidateProfile(**_get_base_profile_dict())
    policy = JobScoringPolicy(**_get_base_policy_dict())
    
    with pytest.raises(ValueError, match="Schema validation failed"):
        validate_evaluation_payload({
            "description_available": "false",
            "recommendation": "blocked",
            "hard_disqualifiers": [],
            "evidence_matches": [],
            "campaign_id": None,
            "score_breakdown": None,
            "fit_score": None,
            "summary": "missing",
            "strengths": [],
            "gaps": [],
            "uncertainties": ["missing"]
        }, profile, policy, job)

def test_int_zero_description_available_returns_schema_error():
    from applywright.screening.config_validator import validate_evaluation_payload
    job = Job(dedupe_key="abc", title="A", company="B", source="C", description="Has text")
    profile = CandidateProfile(**_get_base_profile_dict())
    policy = JobScoringPolicy(**_get_base_policy_dict())
    
    with pytest.raises(ValueError, match="Schema validation failed"):
        validate_evaluation_payload({
            "description_available": 0,
            "recommendation": "blocked",
            "hard_disqualifiers": [],
            "evidence_matches": [],
            "campaign_id": None,
            "score_breakdown": None,
            "fit_score": None,
            "summary": "missing",
            "strengths": [],
            "gaps": [],
            "uncertainties": ["missing"]
        }, profile, policy, job)


def test_config_dir_env(monkeypatch, tmp_path):
    import os
    import yaml
    from applywright.screening.config_validator import load_candidate_profile
    
    # Create temp config
    os.makedirs(os.path.join(tmp_path, "config"))
    profile_path = os.path.join(tmp_path, "config", "candidate_profile.example.yaml")
    
    with open(profile_path, "w") as pf:
        yaml.dump(_get_base_profile_dict(), pf)
        
    monkeypatch.setenv("APPLYWRIGHT_CONFIG_DIR", os.path.join(tmp_path, "config"))
    # Move out to prove it doesn't use cwd or __file__ fallback
    monkeypatch.chdir("/") 
    
    profile = load_candidate_profile()
    assert profile.schema_version == 1
