from typing import Optional
from datetime import datetime, timezone
from uuid import uuid4
from enum import Enum
from pydantic import BaseModel, Field, model_validator


class ApplicationStatus(str, Enum):
    DISCOVERED = "discovered"
    SAVED = "saved"
    APPLIED = "applied"
    SCREENING = "screening"
    INTERVIEW = "interview"
    REJECTED = "rejected"
    WITHDRAWN = "withdrawn"
    OFFER = "offer"
    UNKNOWN = "unknown"


class Decision(str, Enum):
    REVIEW = "review"
    APPLY = "apply"
    SKIP = "skip"
    APPLIED = "applied"


class Job(BaseModel):
    job_id: str = Field(default_factory=lambda: str(uuid4()))
    external_id: Optional[str] = None
    dedupe_key: str

    title: str
    company: str
    location: Optional[str] = None
    remote_status: Optional[str] = None
    salary: Optional[str] = None
    employment_type: Optional[str] = None
    job_url: Optional[str] = None
    description: Optional[str] = None
    apply_url: Optional[str] = None

    date_found: Optional[datetime] = None
    date_applied: Optional[datetime] = None

    application_status: ApplicationStatus = ApplicationStatus.DISCOVERED
    source: str

    decision: Optional[Decision] = None
    notes: Optional[str] = None

    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @model_validator(mode="before")
    @classmethod
    def normalize_optional_whitespace(cls, data: dict) -> dict:
        if isinstance(data, dict):
            # Optional source fields that should be coerced to None if whitespace-only
            for field in [
                "location",
                "remote_status",
                "salary",
                "employment_type",
                "job_url",
                "description",
                "apply_url",
            ]:
                if field in data and isinstance(data[field], str):
                    if not data[field].strip():
                        data[field] = None

            # Required fields that must be stripped and rejected if empty
            for field in ["title", "company", "source"]:
                if field in data and isinstance(data[field], str):
                    stripped = data[field].strip()
                    if not stripped:
                        raise ValueError(f"{field} cannot be empty or whitespace-only")
                    data[field] = stripped

            # external_id is optional globally, but if provided as whitespace, it shouldn't be valid
            if "external_id" in data and isinstance(data["external_id"], str):
                if not data["external_id"].strip():
                    data["external_id"] = None
                else:
                    data["external_id"] = data["external_id"].strip()
        return data
