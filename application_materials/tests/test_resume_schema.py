import pytest
import jsonschema
import copy
from application_materials.tools.validate_application import (
    validate_schemas,
    validate_evidence,
    validate_chronology,
)
import os

SCHEMA_DIR = os.path.join(os.path.dirname(__file__), "..", "schemas")


@pytest.fixture
def base_candidate():
    return {
        "name": "Jane",
        "email": "j@e.com",
        "phone": "123",
        "location": "NY",
        "evidence_catalog": {"EV-1": "test"},
        "education": [{"degree": "BS", "institution": "SU"}],
        "certifications": ["cert1"],
    }


@pytest.fixture
def base_resume():
    return {
        "summary": {"text": "Sum", "evidence_ids": ["EV-1"]},
        "core_skills": [{"text": "sk1", "evidence_ids": ["EV-1"]}],
        "experience": [
            {
                "employer": "Emp1",
                "title": "T1",
                "start_year": "2020",
                "end_year": "2021",
                "overview": {"text": "O1", "evidence_ids": ["EV-1"]},
                "engagements": [
                    {
                        "client": "C1",
                        "overview": {"text": "C1-O", "evidence_ids": ["EV-1"]},
                        "achievements": [{"text": "A1", "evidence_ids": ["EV-1"]}],
                    }
                ],
            }
        ],
    }


@pytest.fixture
def base_cover_letter():
    return {"company_name": "Acme", "position": "Pos", "paragraphs": ["P1"]}


def test_valid_schemas(base_candidate, base_resume, base_cover_letter):
    validate_schemas(base_candidate, base_resume, base_cover_letter, SCHEMA_DIR)
    validate_chronology(base_resume)
    validate_evidence(base_candidate, base_resume)


def test_empty_evidence_catalog_fails(base_candidate, base_resume, base_cover_letter):
    candidate = copy.deepcopy(base_candidate)
    candidate["evidence_catalog"] = {}
    with pytest.raises(jsonschema.ValidationError):
        validate_schemas(candidate, base_resume, base_cover_letter, SCHEMA_DIR)


def test_duplicate_evidence_ids_fails(base_candidate, base_resume, base_cover_letter):
    resume = copy.deepcopy(base_resume)
    resume["summary"]["evidence_ids"] = ["EV-1", "EV-1"]
    with pytest.raises(jsonschema.ValidationError):
        validate_schemas(base_candidate, resume, base_cover_letter, SCHEMA_DIR)


def test_malformed_years_fails(base_candidate, base_resume, base_cover_letter):
    resume = copy.deepcopy(base_resume)
    resume["experience"][0]["start_year"] = "20"  # Not 4 digits
    with pytest.raises(jsonschema.ValidationError):
        validate_schemas(base_candidate, resume, base_cover_letter, SCHEMA_DIR)


def test_end_year_preceding_start_year_fails(base_resume):
    resume = copy.deepcopy(base_resume)
    resume["experience"][0]["start_year"] = "2021"
    resume["experience"][0]["end_year"] = "2020"
    with pytest.raises(ValueError, match="Chronology error"):
        validate_chronology(resume)


def test_unknown_evidence_id_fails(base_candidate, base_resume):
    resume = copy.deepcopy(base_resume)
    resume["summary"]["evidence_ids"].append("EV-UNKNOWN")
    with pytest.raises(ValueError, match="Unknown evidence ID"):
        validate_evidence(base_candidate, resume)


def test_missing_evidence_ids_fails(base_candidate, base_resume, base_cover_letter):
    resume = copy.deepcopy(base_resume)
    del resume["summary"]["evidence_ids"]
    with pytest.raises(jsonschema.ValidationError):
        validate_schemas(base_candidate, resume, base_cover_letter, SCHEMA_DIR)


def test_empty_core_skills_fails(base_candidate, base_resume, base_cover_letter):
    resume = copy.deepcopy(base_resume)
    resume["core_skills"] = []
    with pytest.raises(jsonschema.ValidationError):
        validate_schemas(base_candidate, resume, base_cover_letter, SCHEMA_DIR)


def test_empty_experience_fails(base_candidate, base_resume, base_cover_letter):
    resume = copy.deepcopy(base_resume)
    resume["experience"] = []
    with pytest.raises(jsonschema.ValidationError):
        validate_schemas(base_candidate, resume, base_cover_letter, SCHEMA_DIR)


def test_empty_candidate_education_fails(
    base_candidate, base_resume, base_cover_letter
):
    candidate = copy.deepcopy(base_candidate)
    candidate["education"] = []
    with pytest.raises(jsonschema.ValidationError):
        validate_schemas(candidate, base_resume, base_cover_letter, SCHEMA_DIR)


def test_empty_employer_engagements_fails(
    base_candidate, base_resume, base_cover_letter
):
    resume = copy.deepcopy(base_resume)
    resume["experience"][0]["engagements"] = []
    with pytest.raises(jsonschema.ValidationError):
        validate_schemas(base_candidate, resume, base_cover_letter, SCHEMA_DIR)


def test_unknown_fields_fail(base_candidate, base_resume, base_cover_letter):
    resume = copy.deepcopy(base_resume)
    resume["experience"][0]["unknown_field"] = "bad"
    with pytest.raises(jsonschema.ValidationError):
        validate_schemas(base_candidate, resume, base_cover_letter, SCHEMA_DIR)


def test_candidate_example_validates_against_schema():
    import jsonschema
    import json
    import yaml

    base = os.path.join(os.path.dirname(__file__), "..")
    with open(os.path.join(base, "candidate.example.yaml"), encoding="utf-8") as f:
        candidate = yaml.safe_load(f)
    with open(
        os.path.join(SCHEMA_DIR, "candidate.schema.json"), encoding="utf-8"
    ) as f:
        schema = json.load(f)
    jsonschema.validate(instance=candidate, schema=schema)
    assert candidate["name"] == "Alex Example"
