"""Tests for the advisory triage in applywright.screening.triage.

The regression these pin down: a keyword scorer ranked a job whose Kubernetes and
Terraform requirements sat under "Preferred" identically to one that demanded
"6+ years multi-cloud including Azure" under "Required". Section awareness and
gate extraction are what separate them.
"""

import sqlite3
from pathlib import Path

import pytest

from applywright.models import Job
from applywright.screening import triage as screen_jobs
from applywright.storage.repository import JobRepository


class Row(dict):
    """Stand-in for sqlite3.Row (supports __getitem__ like the real thing)."""


def make_job(**kw):
    base = {
        "job_id": "id-1",
        "external_id": "1",
        "title": "DevOps Architect",
        "company": "Acme",
        "location": None,
        "salary": None,
        "description": "",
        "decision": None,
        "source": "jobcopilot",
        "application_status": "saved",
    }
    base.update(kw)
    return Row(base)


POSTING_PREFERRED_STACK = """
About the role. You will build cloud platforms.

Requirements:
- Bachelor's degree in Computer Science.
- 8+ years of experience managing and building cloud computing platforms.
- Strong problem-solving skills.

Preferred:
- 3-6 years of experience with configuration tools like Ansible, Terraform, and Helm.
- 2-4 years with containers deployed as Docker on Kubernetes/EKS/AKS.
- Automation via scripting languages such as Bash or Python.

Benefits:
- Health insurance.
"""

POSTING_REQUIRED_STACK = """
About the role. You will keep our AI platform reliable.

Requirements
To do this you will have:
- 6+ years of progressive experience in Site Reliability Engineering (SRE)
- 6+ years hands-on experience across multi-cloud environments such as AWS, GCP, Azure
- 6+ years of deep expertise in containerization and orchestration (Kubernetes, EKS, ECS)
- 6+ years with Infrastructure as Code (Terraform, Pulumi, CloudFormation)

What we offer:
- Equity.
"""


def test_split_sections_separates_required_from_preferred():
    s = screen_jobs.split_sections(POSTING_PREFERRED_STACK)
    assert s["structured"] is True
    assert "8+ years" in s["required"]
    # Kubernetes/Terraform are preferred here, not required.
    assert "kubernetes" in s["preferred"].lower()
    assert "kubernetes" not in s["required"].lower()


def test_split_sections_falls_back_to_whole_text_when_unstructured():
    s = screen_jobs.split_sections("We need someone who knows AWS and Kubernetes.")
    assert s["structured"] is False
    assert "aws" in s["required"].lower()
    assert s["preferred"] == ""


def test_extract_gates_surfaces_quantified_requirements():
    gates = screen_jobs.extract_gates(screen_jobs.split_sections(POSTING_REQUIRED_STACK)["required"])
    joined = " | ".join(gates).lower()
    assert any("6+ years" in g for g in gates)
    assert "site reliability" in joined or "sre" in joined


def test_extract_gates_returns_empty_without_year_requirements():
    assert screen_jobs.extract_gates("Experience with Kubernetes and AWS.") == []


def test_required_signals_do_not_count_preferred_stack():
    q, _, _ = screen_jobs.screen([make_job(description=POSTING_PREFERRED_STACK)])
    job = q[0]
    assert "kubernetes" in job["preferred_signals"]
    assert "kubernetes" not in job["required_signals"]


def test_preferred_stack_outranks_required_stack_because_its_stack_is_only_preferred():
    """Stack named only as preferred must not count as required."""
    q, _, _ = screen_jobs.screen(
        [
            make_job(
                job_id="required-stack",
                company="Example Required Co",
                title="Senior Site Reliability Engineer",
                description=POSTING_REQUIRED_STACK,
            ),
            make_job(
                job_id="preferred-stack",
                company="Example Preferred Co",
                title="DevOps Architect",
                description=POSTING_PREFERRED_STACK,
            ),
        ]
    )
    # The required-stack posting demands the stack; its gates must be surfaced, not silently scored.
    required = next(j for j in q if j["id"] == "required-stack")
    assert required["gates"], "quantified gates must be surfaced for a human to check"


def test_title_specialty_blocks_job():
    q, blocked, _ = screen_jobs.screen(
        [make_job(title="Salesforce Technical Architect", description=POSTING_PREFERRED_STACK)]
    )
    assert q == []
    assert "Salesforce" in blocked[0]["reason"]


def test_passing_mention_of_specialty_does_not_block():
    """A job is not a Salesforce role merely because prose mentions Salesforce."""
    desc = (
        "We integrate with many systems including Salesforce.\n"
        "Requirements:\n- Strong AWS, Kubernetes, and Terraform experience.\n"
    )
    q, blocked, _ = screen_jobs.screen(
        [make_job(title="Platform Engineer", description=desc)]
    )
    assert blocked == []
    assert len(q) == 1
    assert "aws" in q[0]["required_signals"]


def test_blank_description_is_blocked_not_ranked():
    q, blocked, _ = screen_jobs.screen([make_job(description="   ")])
    assert q == []
    assert "not evaluable" in blocked[0]["reason"]


def test_already_decided_jobs_are_excluded():
    q, blocked, decided = screen_jobs.screen(
        [make_job(decision="skip", description=POSTING_PREFERRED_STACK)]
    )
    assert (q, blocked, decided) == ([], [], 1)


def test_test_source_jobs_are_ignored():
    q, blocked, decided = screen_jobs.screen(
        [make_job(source="test", description=POSTING_PREFERRED_STACK)]
    )
    assert (q, blocked, decided) == ([], [], 0)


def test_load_jobs_reads_without_writing(tmp_path):
    """The advisory contract: read-only, always."""
    db = tmp_path / "jobs.db"
    repo = JobRepository(str(db))
    repo.upsert_job(
        Job(
            dedupe_key="k",
            title="Dev",
            company="Acme",
            source="jobcopilot",
            application_status="saved",
        )
    )
    repo.upsert_job(
        Job(
            dedupe_key="k2",
            title="Old",
            company="Acme",
            source="jobcopilot",
            application_status="applied",
        )
    )
    before = db.read_bytes()

    jobs = screen_jobs.load_jobs(db, ("saved",))

    assert [j["title"] for j in jobs] == ["Dev"]
    assert db.read_bytes() == before


def test_the_triage_connection_refuses_writes(tmp_path):
    db = tmp_path / "jobs.db"
    job = Job(dedupe_key="k", title="Dev", company="Acme", source="jobcopilot")
    JobRepository(str(db)).upsert_job(job)
    reader = JobRepository(str(db), read_only=True)

    with pytest.raises(sqlite3.OperationalError):
        reader.upsert_job(
            Job(dedupe_key="k2", title="Dev 2", company="Acme", source="jobcopilot")
        )
    with pytest.raises(sqlite3.OperationalError):
        reader.update_job_status(job.job_id, "skip")


def test_triage_does_not_create_a_missing_database(tmp_path):
    db = tmp_path / "missing" / "jobs.db"
    with pytest.raises(sqlite3.OperationalError):
        screen_jobs.load_jobs(db, ("saved",))
    assert not db.parent.exists()


def test_limit_does_not_distort_the_reported_queue_size():
    """A truncated display must still report the true queue length."""
    jobs = [
        make_job(job_id=f"id-{i}", description=POSTING_PREFERRED_STACK, title="DevOps Architect")
        for i in range(5)
    ]
    queue, blocked, decided = screen_jobs.screen(jobs)
    report = screen_jobs.format_report(queue, blocked, decided, shown=2)
    assert "Queued for review: 5" in report
    assert "showing the first 2" in report


def test_synonyms_count_as_one_signal():
    """'IaC' and 'Infrastructure as Code' in one posting are one concept."""
    text = "Requirements:\n- Deep Infrastructure as Code (IaC) experience.\n"
    assert screen_jobs.signals(text).count("immutable infrastructure") == 1
    k8s = "Requirements:\n- Kubernetes (K8s) at scale.\n"
    assert screen_jobs.signals(k8s).count("kubernetes") == 1


def test_every_evidenced_signal_is_traceable_to_candidate_yaml():
    """The screener must not claim evidence the candidate profile lacks.

    Guards against drift: if a signal is added here without matching evidence in
    candidate.example.yaml (or removed from it), this fails.
    """
    catalog = (
        (
            Path(__file__).resolve().parents[1]
            / "application_materials"
            / "candidate.example.yaml"
        )
        .read_text()
        .lower()
    )
    missing = [
        name
        for name, variants in screen_jobs.EVIDENCED_SIGNALS.items()
        if not any(v.lower() in catalog for v in variants)
    ]
    assert not missing, f"signals with no evidence in candidate.yaml: {missing}"


def test_specialty_terms_are_not_claimed_as_evidence():
    """A stack cannot be both an exclusion reason and an evidenced signal."""
    evidenced = {v.lower() for vs in screen_jobs.EVIDENCED_SIGNALS.values() for v in vs}
    specialty = {t.lower() for ts in screen_jobs.SPECIALTY_TERMS.values() for t in ts}
    assert not (evidenced & specialty), evidenced & specialty


# --- LLM requirement extraction (advisory layer) ---------------------------


class FakeClient:
    """Stands in for a local model. Returns whatever payload the test supplies."""

    def __init__(self, payload=None, error=None):
        self.payload = payload
        self.error = error
        self.calls = []

    def extract(self, section):
        self.calls.append(section)
        if self.error:
            raise RuntimeError(self.error)
        return self.payload


REQUIRED_STACK_SECTION = screen_jobs.split_sections(POSTING_REQUIRED_STACK)["required"]


def test_verify_quotes_accepts_verbatim_and_rejects_invented():
    source = "Requirements:\n- 6+ years of progressive experience in SRE\n"
    items = [
        {"quote": "6+ years of progressive experience in SRE", "skill": "SRE"},
        {"quote": "10+ years of Azure architecture", "skill": "Azure"},  # invented
    ]
    verified, unverified = screen_jobs.verify_quotes(items, source)
    assert [i["skill"] for i in verified] == ["SRE"]
    assert [i["skill"] for i in unverified] == ["Azure"]


def test_verify_quotes_tolerates_whitespace_differences():
    source = "Requirements:\n-  6+   years   of\n   SRE experience\n"
    items = [{"quote": "6+ years of SRE experience", "skill": "SRE"}]
    verified, unverified = screen_jobs.verify_quotes(items, source)
    assert len(verified) == 1 and unverified == []


def test_hard_gates_excludes_alternatives_and_preferred():
    items = [
        {"skill": "Azure", "necessity": "required", "is_alternative": True},
        {"skill": "Kubernetes", "necessity": "preferred", "is_alternative": False},
        {"skill": "SRE", "necessity": "required", "is_alternative": False},
    ]
    assert [g["skill"] for g in screen_jobs.hard_gates(items)] == ["SRE"]


def test_extraction_separates_alternative_cloud_from_required_cloud():
    """The gap regex cannot close: 'AWS, GCP, or Azure' vs 'including Azure'."""
    payload = {
        "requirements": [
            {
                "quote": "6+ years hands-on experience across multi-cloud environments such as AWS, GCP, Azure",
                "skill": "multi-cloud (AWS, GCP, Azure)",
                "years_required": 6,
                "necessity": "required",
                "is_alternative": False,
                "kind": "experience",
            },
            {
                "quote": "6+ years of progressive experience in Site Reliability Engineering (SRE)",
                "skill": "SRE",
                "years_required": 6,
                "necessity": "required",
                "is_alternative": False,
                "kind": "experience",
            },
        ]
    }
    out = screen_jobs.extract_requirements(REQUIRED_STACK_SECTION, FakeClient(payload))
    assert out["error"] is None
    assert len(out["verified"]) == 2
    gates = screen_jobs.hard_gates(out["verified"])
    assert {g["skill"] for g in gates} == {"multi-cloud (AWS, GCP, Azure)", "SRE"}


def test_extraction_discards_hallucinated_requirements():
    payload = {
        "requirements": [
            {
                "quote": "6+ years of progressive experience in Site Reliability Engineering (SRE)",
                "skill": "SRE",
                "years_required": 6,
                "necessity": "required",
                "is_alternative": False,
                "kind": "experience",
            },
            {
                "quote": "Must hold an active TS/SCI clearance",  # never in POSTING_REQUIRED_STACK
                "skill": "TS/SCI clearance",
                "years_required": None,
                "necessity": "required",
                "is_alternative": False,
                "kind": "clearance",
            },
        ]
    }
    out = screen_jobs.extract_requirements(REQUIRED_STACK_SECTION, FakeClient(payload))
    assert [i["skill"] for i in out["verified"]] == ["SRE"]
    assert [i["skill"] for i in out["unverified"]] == ["TS/SCI clearance"]


def test_extraction_failure_degrades_and_never_raises():
    out = screen_jobs.extract_requirements(
        REQUIRED_STACK_SECTION, FakeClient(error="connection refused")
    )
    assert out["verified"] == [] and "connection refused" in out["error"]


def test_extraction_is_off_by_default():
    q, _, _ = screen_jobs.screen([make_job(description=POSTING_REQUIRED_STACK)])
    assert q[0]["extraction"] is None


def test_extraction_does_not_change_ordering():
    """The model informs; it must not silently reorder the queue."""
    jobs = [
        make_job(job_id="required-stack", title="SRE", description=POSTING_REQUIRED_STACK),
        make_job(job_id="preferred-stack", title="DevOps Architect", description=POSTING_PREFERRED_STACK),
    ]
    plain, _, _ = screen_jobs.screen(jobs)
    withllm, _, _ = screen_jobs.screen(jobs, client=FakeClient({"requirements": []}))
    assert [j["id"] for j in plain] == [j["id"] for j in withllm]


def test_report_flags_discarded_hallucinations(capsys):
    payload = {
        "requirements": [
            {
                "quote": "Must hold an active TS/SCI clearance",
                "skill": "TS/SCI clearance",
                "years_required": None,
                "necessity": "required",
                "is_alternative": False,
                "kind": "clearance",
            }
        ]
    }
    q, b, d = screen_jobs.screen(
        [make_job(description=POSTING_REQUIRED_STACK)], client=FakeClient(payload)
    )
    report = screen_jobs.format_report(q, b, d)
    assert "DISCARDED" in report


def test_client_defaults_guard_the_two_silent_setup_mistakes():
    """A 2048 context truncates postings; an unconstrained model emits bad JSON."""
    c = screen_jobs.OllamaClient("http://x:11434", "qwen3:8b")
    assert c.num_ctx >= 16384, "small context silently truncates job descriptions"

    item = screen_jobs.REQUIREMENT_SCHEMA["properties"]["requirements"]["items"]
    assert item["properties"]["necessity"]["enum"] == ["required", "preferred"]
    # Every field is mandatory, so grammar-constrained decoding cannot omit one.
    assert set(item["required"]) == {
        "quote",
        "skill",
        "years_required",
        "necessity",
        "is_alternative",
        "kind",
    }


# --- LM Studio client shape ------------------------------------------------


def test_lmstudio_client_posts_openai_shape_with_strict_schema(monkeypatch):
    """LM Studio is OpenAI-compatible: /v1/chat/completions + response_format."""
    seen = {}

    def fake_post(url, payload, timeout):
        seen["url"] = url
        seen["payload"] = payload
        import json as _json

        return {
            "choices": [{"message": {"content": _json.dumps({"requirements": []})}}]
        }

    monkeypatch.setattr(screen_jobs, "_post_json", fake_post)
    c = screen_jobs.LMStudioClient("http://host:1234/", "qwen2.5-7b-instruct")
    assert c.extract("Requirements: AWS.") == {"requirements": []}

    assert seen["url"] == "http://host:1234/v1/chat/completions"
    rf = seen["payload"]["response_format"]
    assert rf["type"] == "json_schema"
    assert rf["json_schema"]["strict"] is True
    assert rf["json_schema"]["schema"] is screen_jobs.REQUIREMENT_SCHEMA
    assert seen["payload"]["temperature"] == 0
    assert seen["payload"]["messages"][0]["role"] == "user"


def test_strict_schema_forbids_extra_properties():
    """OpenAI-style strict mode requires additionalProperties: false throughout."""
    schema = screen_jobs.REQUIREMENT_SCHEMA
    assert schema["additionalProperties"] is False
    assert (
        schema["properties"]["requirements"]["items"]["additionalProperties"] is False
    )


def test_make_client_selects_flavour_and_rejects_unknown():
    assert isinstance(
        screen_jobs.make_client("lmstudio", "http://h:1234", "m"),
        screen_jobs.LMStudioClient,
    )
    assert isinstance(
        screen_jobs.make_client("ollama", "http://h:11434", "m"),
        screen_jobs.OllamaClient,
    )
    import pytest as _pytest

    with _pytest.raises(SystemExit):
        screen_jobs.make_client("vllm", "http://h", "m")


def test_enrich_only_extracts_for_the_jobs_it_will_show():
    """Extraction costs ~40s per posting; do not pay for undisplayed jobs."""
    jobs = [
        make_job(job_id=f"id-{i}", description=POSTING_REQUIRED_STACK, title="SRE") for i in range(10)
    ]
    queue, _, _ = screen_jobs.screen(jobs)
    client = FakeClient({"requirements": []})
    screen_jobs.enrich(queue, client, top_n=2)
    assert len(client.calls) == 2
    assert queue[0]["extraction"] is not None
    assert queue[5]["extraction"] is None


def test_enrich_without_client_is_a_no_op():
    queue, _, _ = screen_jobs.screen([make_job(description=POSTING_REQUIRED_STACK)])
    assert screen_jobs.enrich(queue, None)[0]["extraction"] is None


# ---------------------------------------------------------------------------
# Eligibility gates
#
# Each case below is a real posting from the 2026-07-18 screening sweep. The
# negative cases matter more than the positive ones: they pin down that a
# certification under "Preferred", an obtainable Public Trust, and a cloud
# offered as an alternative all stay in the queue.
# ---------------------------------------------------------------------------

REQUIRED_CERT = """
Requirements:
- 8+ years cloud experience including 5+ years GCP.
- Professional Cloud Architect or Data Engineer certification.
- Experience with Terraform, Docker, Kubernetes.
"""

PREFERRED_CERT = """
Requirements:
- Minimum 5+ years of DevOps work experience.
- Strong understanding of Linux/UNIX administration and Bash.

Preferred:
- Technical cloud certifications (AWS, GCP, Oracle, or Azure).
- Experience with configuration management systems (Puppet, Chef).
"""

# Isolated to the clearance gate. A posting may also demand Security+, but
# a fixture that trips two gates cannot prove which one fired -- whichever is
# checked first wins, and the reported reason is that first match.
ACTIVE_CLEARANCE = """
Requirements:
- Active T3 investigation, with the ability to obtain and maintain clearances.
- 3+ years technical experience in systems administration.
- Experience with Linux and cloud computing (AWS preferred).
"""

OBTAINABLE_PUBLIC_TRUST = """
Requirements:
- 10+ years of enterprise architecture experience.
- U.S. Citizen or Permanent Resident with the ability to obtain a Public Trust.
- Experience with AWS and Terraform.
"""

OFFSHORE_RATE = """
Requirements:
- Minimum 5 years in similar cloud/infrastructure roles.
- Advanced level: Terraform, Kubernetes.
- Salary: $3,200 - $3,800 a month.
"""

ALTERNATIVE_CLOUD = """
Requirements:
- 5-10+ years of experience in cloud infrastructure or SRE.
- Deep experience with Google Cloud (GCP) or equivalent cloud platforms.
- Strong expertise in Kubernetes and Infrastructure as Code (Terraform).
"""


def test_required_certification_blocks_job():
    q, blocked, _ = screen_jobs.screen(
        [make_job(title="Senior Cloud Engineer", description=REQUIRED_CERT)]
    )
    assert q == []
    assert "certification" in blocked[0]["reason"]


def test_preferred_certification_does_not_block():
    """Teramind listed certs under Preferred and scored a recommend."""
    q, blocked, _ = screen_jobs.screen(
        [make_job(title="Senior DevOps Engineer", description=PREFERRED_CERT)]
    )
    assert blocked == []
    assert len(q) == 1


def test_active_clearance_blocks_job():
    q, blocked, _ = screen_jobs.screen(
        [make_job(title="Site Reliability Engineer", description=ACTIVE_CLEARANCE)]
    )
    assert q == []
    assert "clearance" in blocked[0]["reason"]


def test_obtainable_public_trust_does_not_block():
    """An obtainable Public Trust is not an active clearance."""
    q, blocked, _ = screen_jobs.screen(
        [make_job(title="Technical Architect", description=OBTAINABLE_PUBLIC_TRUST)]
    )
    assert blocked == []
    assert len(q) == 1


def test_monthly_offshore_rate_blocks_job():
    q, blocked, _ = screen_jobs.screen(
        [make_job(title="Cloud Infrastructure Engineer", description=OFFSHORE_RATE)]
    )
    assert q == []
    assert "offshore" in blocked[0]["reason"]


def test_alternative_cloud_is_not_an_eligibility_gate():
    """'GCP or equivalent' ranks lower but must stay in the queue."""
    q, blocked, _ = screen_jobs.screen(
        [
            make_job(
                title="Senior Cloud Infrastructure Engineer",
                description=ALTERNATIVE_CLOUD,
            )
        ]
    )
    assert blocked == []
    assert len(q) == 1
    assert q[0]["required_specialty"] == "GCP"


def test_wrong_cloud_in_title_blocks_job():
    q, blocked, _ = screen_jobs.screen(
        [make_job(title="Azure Cloud Engineer", description=POSTING_PREFERRED_STACK)]
    )
    assert q == []
    assert "Azure" in blocked[0]["reason"]


@pytest.mark.parametrize(
    "phrase",
    [
        "Must reside in Michigan",
        "Must reside in US",
        "Must reside in the US",
        "Must reside in United States",
        "Must be located in the United States",
    ],
)
def test_us_residency_requirement_does_not_block(phrase):
    desc = f"Requirements:\n- {phrase}.\n- Strong AWS and Terraform experience.\n"
    _, blocked, _ = screen_jobs.screen(
        [make_job(title="Platform Engineer", description=desc)]
    )
    assert blocked == []


@pytest.mark.parametrize("place", ["Canada", "the UK", "India", "Europe", "Brazil"])
def test_foreign_residency_requirement_blocks(place):
    desc = f"Requirements:\n- Must reside in {place}.\n- Strong AWS experience.\n"
    _, blocked, _ = screen_jobs.screen(
        [make_job(title="Platform Engineer", description=desc)]
    )
    assert "non-US hiring market" in blocked[0]["reason"]
