import os
import yaml
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    model_validator,
    StrictInt,
    StrictStr,
    StringConstraints,
)
from typing import List, Literal, Annotated, Optional, Union, Dict, Any
from applywright.models import Job

# NonBlankStrictString enforcing stripping whitespace and requiring >= 1 char
NonBlankStrictString = Annotated[
    StrictStr, StringConstraints(strip_whitespace=True, min_length=1)
]


class BaseStrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Campaign(BaseStrictModel):
    id: NonBlankStrictString
    name: NonBlankStrictString


class EvidenceItem(BaseStrictModel):
    evidence_id: NonBlankStrictString
    description: NonBlankStrictString


class HardDisqualifier(BaseStrictModel):
    disqualifier_id: NonBlankStrictString
    description: NonBlankStrictString


class CandidateProfile(BaseStrictModel):
    schema_version: StrictInt
    campaigns: List[Campaign]
    evidence_items: List[EvidenceItem] = Field(min_length=1)
    hard_disqualifiers: List[HardDisqualifier] = Field(min_length=1)

    @model_validator(mode="after")
    def check_schema_version(self):
        if self.schema_version != 1:
            raise ValueError("schema_version must be 1")
        return self

    @model_validator(mode="after")
    def check_uniqueness(self):
        c_ids = [c.id for c in self.campaigns]
        if len(c_ids) != len(set(c_ids)):
            raise ValueError("Duplicate campaign ID found")

        e_ids = [e.evidence_id for e in self.evidence_items]
        if len(e_ids) != len(set(e_ids)):
            raise ValueError("Duplicate evidence ID found")

        d_ids = [d.disqualifier_id for d in self.hard_disqualifiers]
        if len(d_ids) != len(set(d_ids)):
            raise ValueError("Duplicate hard-disqualifier ID found")
        return self


class ScoringWeights(BaseStrictModel):
    campaign_and_role_family_match: StrictInt = Field(ge=0, le=100)
    required_technical_skills: StrictInt = Field(ge=0, le=100)
    direct_career_evidence: StrictInt = Field(ge=0, le=100)
    seniority_and_responsibility_alignment: StrictInt = Field(ge=0, le=100)
    architecture_and_leadership_alignment: StrictInt = Field(ge=0, le=100)
    location_and_work_arrangement: StrictInt = Field(ge=0, le=100)
    compensation_and_employment_type: StrictInt = Field(ge=0, le=100)

    @model_validator(mode="after")
    def check_total_score(self):
        total = (
            self.campaign_and_role_family_match
            + self.required_technical_skills
            + self.direct_career_evidence
            + self.seniority_and_responsibility_alignment
            + self.architecture_and_leadership_alignment
            + self.location_and_work_arrangement
            + self.compensation_and_employment_type
        )
        if total != 100:
            raise ValueError(f"Total scoring weight must equal 100, got {total}")
        return self


class Overrides(BaseStrictModel):
    missing_description: Literal["blocked"]
    hard_disqualifier: Literal["reject"]


class ScoreThreshold(BaseStrictModel):
    min_score: StrictInt
    max_score: StrictInt
    decision: Literal["reject", "manual_review", "recommend", "strong_recommend"]


class JobScoringPolicy(BaseStrictModel):
    schema_version: StrictInt
    scoring_weights: ScoringWeights
    overrides: Overrides
    score_thresholds: List[ScoreThreshold]

    @model_validator(mode="after")
    def check_schema_version(self):
        if self.schema_version != 1:
            raise ValueError("schema_version must be 1")
        return self

    @model_validator(mode="after")
    def check_thresholds(self):
        # We require exactly these 4 thresholds, regardless of list order
        required = {
            (0, 71, "reject"),
            (72, 81, "manual_review"),
            (82, 89, "recommend"),
            (90, 100, "strong_recommend"),
        }

        actual = set()
        for t in self.score_thresholds:
            tup = (t.min_score, t.max_score, t.decision)
            if tup in actual:
                raise ValueError(f"Duplicated decision range: {tup}")
            actual.add(tup)

        if len(actual) < 4:
            raise ValueError("Fewer than four threshold ranges provided")
        if len(actual) > 4:
            raise ValueError("More than four threshold ranges provided")

        if actual != required:
            raise ValueError(
                f"Thresholds do not exactly match required mapping. Expected: {required}, Actual: {actual}"
            )

        return self


def _config_file(file_name: str) -> str:
    """Find a config file. The user's own file wins over the shipped example."""
    config_dir = os.environ.get("APPLYWRIGHT_CONFIG_DIR")
    if not config_dir:
        repo_root = os.path.dirname(
            os.path.dirname(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            )
        )
        config_dir = os.path.join(repo_root, "config")
    own = os.path.join(config_dir, file_name)
    if os.path.exists(own):
        return own
    stem, ext = os.path.splitext(file_name)
    return os.path.join(config_dir, f"{stem}.example{ext}")


def load_candidate_profile(file_path: Optional[str] = None) -> CandidateProfile:
    if file_path is None:
        file_path = _config_file("candidate_profile.yaml")
    with open(file_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return CandidateProfile(**data)


def load_job_scoring_policy(file_path: Optional[str] = None) -> JobScoringPolicy:
    if file_path is None:
        file_path = _config_file("job_scoring_policy.yaml")
    with open(file_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return JobScoringPolicy(**data)


class EvidenceMatch(BaseStrictModel):
    requirement: NonBlankStrictString
    evidence_id: NonBlankStrictString
    strength: Literal["weak", "moderate", "strong", "very_strong"]
    explanation: NonBlankStrictString


class ScoreBreakdown(BaseStrictModel):
    campaign_and_role_family_match: StrictInt
    required_technical_skills: StrictInt
    direct_career_evidence: StrictInt
    seniority_and_responsibility_alignment: StrictInt
    architecture_and_leadership_alignment: StrictInt
    location_and_work_arrangement: StrictInt
    compensation_and_employment_type: StrictInt


class BlockedEvaluationPayload(BaseStrictModel):
    description_available: Literal[False]
    campaign_id: None
    score_breakdown: None
    fit_score: None
    recommendation: Literal["blocked"]
    hard_disqualifiers: List[NonBlankStrictString] = Field(max_length=0)
    evidence_matches: List[EvidenceMatch] = Field(max_length=0)
    summary: NonBlankStrictString
    strengths: List[NonBlankStrictString] = Field(max_length=0)
    gaps: List[NonBlankStrictString] = Field(max_length=0)
    uncertainties: List[NonBlankStrictString] = Field(min_length=1)


class ScoredEvaluationPayload(BaseStrictModel):
    description_available: Literal[True]
    campaign_id: NonBlankStrictString
    score_breakdown: ScoreBreakdown
    fit_score: StrictInt = Field(ge=0, le=100)
    recommendation: Literal["reject", "manual_review", "recommend", "strong_recommend"]
    hard_disqualifiers: List[NonBlankStrictString]
    evidence_matches: List[EvidenceMatch]
    summary: NonBlankStrictString
    strengths: List[NonBlankStrictString]
    gaps: List[NonBlankStrictString]
    uncertainties: List[NonBlankStrictString]

    @model_validator(mode="after")
    def validate_evaluation(self):
        # Enforce distinct hard disqualifiers
        if len(self.hard_disqualifiers) != len(set(self.hard_disqualifiers)):
            raise ValueError("hard_disqualifiers contains duplicate IDs")

        # Duplicate evidence IDs across ANY scored payload
        evidence_ids = [e.evidence_id for e in self.evidence_matches]
        if len(evidence_ids) != len(set(evidence_ids)):
            raise ValueError("duplicate evidence_id found in evidence_matches")

        # Sum validation
        total_breakdown = (
            self.score_breakdown.campaign_and_role_family_match
            + self.score_breakdown.required_technical_skills
            + self.score_breakdown.direct_career_evidence
            + self.score_breakdown.seniority_and_responsibility_alignment
            + self.score_breakdown.architecture_and_leadership_alignment
            + self.score_breakdown.location_and_work_arrangement
            + self.score_breakdown.compensation_and_employment_type
        )
        if total_breakdown != self.fit_score:
            raise ValueError("score_breakdown sum must exactly equal fit_score")

        return self


EvaluationPayload = Annotated[
    Union[BlockedEvaluationPayload, ScoredEvaluationPayload],
    Field(discriminator="description_available"),
]


def validate_evaluation_payload(
    payload_dict: Dict[str, Any], profile: CandidateProfile, policy: JobScoringPolicy, job: "Job"
) -> Union[BlockedEvaluationPayload, ScoredEvaluationPayload]:
    import pydantic
    
    try:
        if "description_available" in payload_dict and not isinstance(payload_dict["description_available"], bool):
            raise ValueError("Schema validation failed: description_available must be a boolean")
            
        # Pydantic's discriminator routing automatically creates the correct model
        payload: EvaluationPayload = pydantic.TypeAdapter(EvaluationPayload).validate_python(payload_dict, strict=True)
    except Exception as err:
        raise ValueError(f"Schema validation failed: {str(err)}")
        
    # Check description invariant independently
    actual_description_available = bool(job.description and job.description.strip())
    claimed_description_available = payload.description_available
    
    if actual_description_available and not claimed_description_available:
        raise ValueError("Description state mismatch: stored job has description, payload says false")
    if not actual_description_available and claimed_description_available:
        raise ValueError("Description state mismatch: stored job lacks description, payload says true")

    if not payload.description_available:
        # Blocked payload already enforced to have recommendation == 'blocked' and empty lists.
        return payload

    # Scored payload contextual validation
    # 1. campaign_id
    valid_campaigns = {c.id for c in profile.campaigns}
    if payload.campaign_id not in valid_campaigns:
        raise ValueError(f"Unknown campaign ID: {payload.campaign_id}")

    # 2. evidence_id
    valid_evidence_ids = {e.evidence_id for e in profile.evidence_items}
    for e in payload.evidence_matches:
        if e.evidence_id not in valid_evidence_ids:
            raise ValueError(f"Unknown evidence ID: {e.evidence_id}")

    # 3. hard_disqualifier
    valid_disqualifier_ids = {d.disqualifier_id for d in profile.hard_disqualifiers}
    for d in payload.hard_disqualifiers:
        if d not in valid_disqualifier_ids:
            raise ValueError(f"Unknown hard disqualifier ID: {d}")

    # 4. Zero-credit rules based on job facts
    if job.location is None and job.remote_status is None:
        if payload.score_breakdown.location_and_work_arrangement > 0:
            raise ValueError(
                "location and remote_status are null; location_and_work_arrangement score must be 0"
            )

    if job.salary is None and job.employment_type is None:
        if payload.score_breakdown.compensation_and_employment_type > 0:
            raise ValueError(
                "salary and employment_type are null; compensation_and_employment_type score must be 0"
            )

    # 5. Component <= maximum configured weight
    weights = policy.scoring_weights
    breakdown = payload.score_breakdown
    if (
        breakdown.campaign_and_role_family_match
        > weights.campaign_and_role_family_match
    ):
        raise ValueError(
            "campaign_and_role_family_match exceeds configured maximum weight"
        )
    if breakdown.required_technical_skills > weights.required_technical_skills:
        raise ValueError("required_technical_skills exceeds configured maximum weight")
    if breakdown.direct_career_evidence > weights.direct_career_evidence:
        raise ValueError("direct_career_evidence exceeds configured maximum weight")
    if (
        breakdown.seniority_and_responsibility_alignment
        > weights.seniority_and_responsibility_alignment
    ):
        raise ValueError(
            "seniority_and_responsibility_alignment exceeds configured maximum weight"
        )
    if (
        breakdown.architecture_and_leadership_alignment
        > weights.architecture_and_leadership_alignment
    ):
        raise ValueError(
            "architecture_and_leadership_alignment exceeds configured maximum weight"
        )
    if breakdown.location_and_work_arrangement > weights.location_and_work_arrangement:
        raise ValueError(
            "location_and_work_arrangement exceeds configured maximum weight"
        )
    if (
        breakdown.compensation_and_employment_type
        > weights.compensation_and_employment_type
    ):
        raise ValueError(
            "compensation_and_employment_type exceeds configured maximum weight"
        )

    # Negative components are already blocked by StrictInt combined with Pydantic not supporting negative constraints natively without Field(ge=0), wait, we need to enforce ge=0.
    # Ah, I forgot Field(ge=0, le=100) on ScoreBreakdown. I should check >= 0 manually.
    if (
        breakdown.campaign_and_role_family_match < 0
        or breakdown.required_technical_skills < 0
        or breakdown.direct_career_evidence < 0
        or breakdown.seniority_and_responsibility_alignment < 0
        or breakdown.architecture_and_leadership_alignment < 0
        or breakdown.location_and_work_arrangement < 0
        or breakdown.compensation_and_employment_type < 0
    ):
        raise ValueError("Negative component scores are not allowed")

    # 6. Canonical Recommendation derived from policy
    expected_rec: Optional[str] = None
    if len(payload.hard_disqualifiers) > 0:
        expected_rec = policy.overrides.hard_disqualifier
    else:
        for t in policy.score_thresholds:
            if t.min_score <= payload.fit_score <= t.max_score:
                expected_rec = t.decision
                break

    if expected_rec is None:
        raise ValueError(
            f"No configured decision threshold found for fit_score {payload.fit_score}"
        )

    if payload.recommendation != expected_rec:
        raise ValueError(
            f"Recommendation mismatch. Derived canonical recommendation is '{expected_rec}', but payload proposed '{payload.recommendation}'"
        )

    # 7. Evidence count requirement
    if payload.recommendation in ["recommend", "strong_recommend"]:
        if len(payload.evidence_matches) < 3:
            raise ValueError(
                f"{payload.recommendation} requires at least three distinct verified evidence IDs"
            )

    return payload
