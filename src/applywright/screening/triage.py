"""Advisory triage of stored JobCopilot jobs — builds a review QUEUE, not decisions.

Reads the bridge database (read-only, through `JobRepository`) and prints an ordered review queue. This is
deliberately *not* an evaluation: keyword matching cannot distinguish a required
skill from a preferred one, an "AWS or Azure or GCP" list from an "Azure required"
gate, or "8+ years of Kubernetes" from a passing mention. Deciding a job still
means reading its requirements, which is what the bridge's evaluation pipeline
does (`prepare_job_evaluation` -> LLM reads -> `validate_job_evaluation`), and
recording a decision still goes through `mark_job` with the user's explicit
authorization. This module never writes to the database.

What it does that raw keyword counting does not:

* Splits a posting into REQUIRED / PREFERRED sections and scores them separately,
  because a stack listed under "Preferred" is not a barrier and a stack listed
  under "Required" may be.
* Extracts quantified experience gates ("6+ years of SRE") and surfaces them for a
  human to check, rather than folding them into a score that hides them.
* Scopes vendor-specialty exclusions to the title and required section, so a job
  is not skipped merely because its description mentions Salesforce in passing.

Usage (run with the project environment):
    poetry run python screen_jobs.py [--db PATH] [--output PATH] [--limit N]
"""

import argparse
import os
import re
from pathlib import Path
from typing import Any

from applywright.lifecycle import TRIAGE_STATUSES
from applywright.storage.repository import JobRepository

DEFAULT_DB = Path(__file__).resolve().parents[3] / "data" / "jobs.db"

TEST_COMPANIES = {"Tech Corp", "Example Co."}

DEFAULT_STATUS = ",".join(status.value for status in TRIAGE_STATUSES)

# Vendor/discipline specialties with no supporting evidence in the shipped example profile. Edit to match your own profile.
# Matched against the TITLE and the REQUIRED section only — never a passing mention.
SPECIALTY_TERMS = {
    "Salesforce": ["salesforce", "sfdc", "revenue cloud", "apex"],
    "ServiceNow": ["servicenow"],
    "Veeva/MDM": ["veeva", "opendata", "mdm"],
    "SAP": ["sap", "abap", "s/4hana"],
    "Workday": ["workday"],
    "Adobe": ["aem", "adobe"],
    "Frontend/JS": ["react", "typescript", "node.js", "nodejs", "ui/ux"],
    ".NET": [".net", "c#"],
    "C/C++/Embedded": ["c++", "c/c++", "embedded"],
    "Mobile": ["ios", "android"],
    "AI/ML": ["machine learning", "data science", "llm", "genai"],
    "PHP": ["php"],
    "Java": ["java", "spring boot"],
    # Clouds the profile has no evidence for. Title-level ("Azure Cloud Engineer")
    # blocks; a mention inside REQUIRED only ranks the job down, so a posting
    # saying "GCP or equivalent cloud" is not mistaken for a gate.
    "Azure": ["azure", "entra id"],
    "GCP": ["gcp", "google cloud", "gke", "bigquery"],
    "Go": ["golang"],
    "Web frameworks": ["django", "fastapi", "rails"],
    "Database specialist": ["dbre", "database reliability", "dba"],
}

# A residency phrase rejects a job only when it names a place outside the US.
# "Must reside in Michigan" or "Must reside in the US" is a valid US requirement.
_FOREIGN_PLACES = (
    r"(?:canada|the uk|uk|united kingdom|england|ireland|europe|the eu|eu"
    r"|germany|france|spain|italy|portugal|poland|netherlands|the netherlands"
    r"|india|pakistan|philippines|singapore|australia|new zealand|japan|china"
    r"|brazil|argentina|colombia|mexico|chile|latam|latin america|israel"
    r"|south africa|nigeria|kenya|egypt|uae|dubai)\b"
)

# Eligibility facts, not fit judgments. Unlike a specialty these are binary and
# checkable from the posting alone: you either hold the certification, have the
# clearance, and can accept the terms, or you cannot. Each of these blocked a
# real job in screening, so encoding them stops the pipeline paying for an LLM
# evaluation that can only ever conclude "ineligible".
#
# Matched against the TITLE and the REQUIRED section only. That distinction is
# load-bearing: certifications listed under "Preferred" must not block, and an
# obtainable Public Trust is deliberately absent from the clearance list because
# it can be applied for, unlike an already-active investigation.
ELIGIBILITY_GATES = {
    "certification the profile does not hold": [
        r"\baz-?104\b",
        r"\baz-?305\b",
        r"\bms-?102\b",
        r"\bsc-?300\b",
        r"\bitil\b",
        r"\bsecurity\+\b",
        r"\bcomptia\b",
        r"\bcertified ethical hacker\b|\bceh\b",
        r"\bgcp associate\b|\bassociate cloud engineer\b",
        r"\bprofessional cloud architect\b|\bprofessional data engineer\b",
    ],
    "active security clearance": [
        r"\bts/sci\b",
        r"\btop secret\b",
        r"\bsecret clearance\b",
        r"\bpolygraph\b",
        r"\bactive clearance\b",
        r"\bactive t\d\b",
        r"\bclearance (?:is )?required\b",
    ],
    "offshore compensation terms": [
        r"\bctc\b",
        r"\blpa\b",
        r"\bnotice period\b",
        r"\$\s?\d[\d,]*\s*(?:-|–|to)\s*\$?\s?\d[\d,]*\s*(?:a|per)\s+month\b",
    ],
    "non-US hiring market": [
        r"\(m/f/d\)",
        r"\(h/f\)",
        r"\blatam\b",
        r"\bingénieur\b",
        r"\barquiteto\b",
        r"\bmust (?:be )?(?:located|reside) in (?:the )?" + _FOREIGN_PLACES,
    ],
}

# Stacks the candidate profile has direct evidence for. Each entry is a SIGNAL:
# one concept, with its synonyms grouped so "IaC" and "Infrastructure as Code"
# in the same sentence count once rather than twice.
#
# This list is tuned to an infrastructure and DevOps profile. Edit it to match
# your own evidence. tests/test_screen_jobs.py checks that every signal appears
# in application_materials/candidate.example.yaml, so the list and the shipped
# example cannot drift apart.
EVIDENCED_SIGNALS = {
    "aws": ["aws"],
    "kubernetes": ["kubernetes", "k8s"],
    "docker": ["docker"],
    "terraform": ["terraform"],
    "puppet": ["puppet"],
    "ansible": ["ansible"],
    "packer": ["packer"],
    "vagrant": ["vagrant"],
    "ci/cd": ["ci/cd", "cicd", "continuous delivery", "continuous integration"],
    # candidate.yaml evidences "DevSecOps"; a posting saying either word maps here.
    "devops/devsecops": ["devsecops", "devops"],
    "infrastructure": ["infrastructure"],
    "platform": ["platform"],
    "virtualization": ["virtualization", "vmware"],
    "linux": ["linux", "rhel", "red hat"],
    "jenkins": ["jenkins"],
    "git": ["git", "github", "gitlab"],
    "gitops": ["gitops", "argo cd", "argocd", "argo"],
    "artifactory": ["artifactory"],
    "hardening": ["hardening", "cis"],
    "python": ["python"],
    "bash": ["bash"],
    "immutable infrastructure": ["immutable", "infrastructure as code", "iac"],
    "app servers": ["weblogic", "websphere", "tomcat"],
}

# Section headings seen across these postings.
REQUIRED_HEADS = r"(requirements?|required|qualifications?|what we'?re looking for|what you'?ll bring|must[- ]have|minimum qualifications|you have|basic qualifications)"
PREFERRED_HEADS = (
    r"(preferred|nice[- ]to[- ]have|bonus|strong advantage|good to have|plus|desired)"
)
END_HEADS = r"(benefits?|perks?|compensation|about us|what we offer|equal opportunity|our values|why work)"

GATE_RE = re.compile(
    r"(\d{1,2})\s*\+?\s*years?\s+(?:of\s+)?([^.\n;•]{0,70})", re.IGNORECASE
)


def keyword_pattern(keyword: str) -> re.Pattern:
    # \b misbehaves next to non-word characters like "." or "+",
    # so only anchor on sides that start/end with a word character.
    prefix = r"\b" if keyword[0].isalnum() else r"(?<!\w)"
    suffix = r"\b" if keyword[-1].isalnum() else r"(?!\w)"
    return re.compile(prefix + re.escape(keyword) + suffix, re.IGNORECASE)


SPECIALTY_PATTERNS = {
    reason: [keyword_pattern(k) for k in keywords]
    for reason, keywords in SPECIALTY_TERMS.items()
}
# Already regexes rather than literals, so compiled directly.
ELIGIBILITY_PATTERNS = {
    reason: [re.compile(p, re.IGNORECASE) for p in patterns]
    for reason, patterns in ELIGIBILITY_GATES.items()
}
# (signal name, [patterns]) so reports show "kubernetes", not the pattern source,
# and so a signal fires at most once no matter how many synonyms are present.
EVIDENCED_PATTERNS = [
    (name, [keyword_pattern(k) for k in variants])
    for name, variants in EVIDENCED_SIGNALS.items()
]


def split_sections(description: str) -> dict[str, Any]:
    """Split a posting into required / preferred text.

    Falls back to treating the whole posting as 'required' when no headings are
    found, which keeps behaviour conservative for unstructured postings.
    """
    if not description:
        return {"required": "", "preferred": "", "structured": False}

    text = description
    req_m = re.search(REQUIRED_HEADS, text, re.IGNORECASE)
    pref_m = re.search(PREFERRED_HEADS, text, re.IGNORECASE)

    if not req_m and not pref_m:
        return {"required": text, "preferred": "", "structured": False}

    # Preferred runs from its heading to the next boilerplate heading (or end).
    preferred = ""
    if pref_m:
        tail = text[pref_m.start() :]
        end_m = re.search(END_HEADS, tail[len(pref_m.group(0)) :], re.IGNORECASE)
        preferred = tail[: len(pref_m.group(0)) + end_m.start()] if end_m else tail

    # Required runs from its heading to the preferred heading (or boilerplate/end).
    required = ""
    if req_m:
        start = req_m.start()
        stop = len(text)
        if pref_m and pref_m.start() > start:
            stop = pref_m.start()
        else:
            end_m = re.search(
                END_HEADS, text[start + len(req_m.group(0)) :], re.IGNORECASE
            )
            if end_m:
                stop = start + len(req_m.group(0)) + end_m.start()
        required = text[start:stop]

    return {"required": required, "preferred": preferred, "structured": True}


def extract_gates(text: str) -> list[str]:
    """Quantified experience requirements a human must check against evidence."""
    gates = []
    for years, subject in GATE_RE.findall(text or ""):
        subject = re.sub(r"\s+", " ", subject).strip(" -–—:,")
        if subject:
            gates.append(f"{years}+ years {subject}")
    # De-duplicate, preserve order.
    seen, out = set(), []
    for g in gates:
        k = g.lower()
        if k not in seen:
            seen.add(k)
            out.append(g)
    return out[:6]


def signals(text: str) -> list[str]:
    """Evidenced signals present in the text; synonyms count once."""
    return [
        name
        for name, patterns in EVIDENCED_PATTERNS
        if any(p.search(text or "") for p in patterns)
    ]


def specialty_in(text: str) -> str | None:
    for reason, patterns in SPECIALTY_PATTERNS.items():
        if any(p.search(text or "") for p in patterns):
            return reason
    return None


def eligibility_gate(text: str) -> tuple[str, str] | None:
    """First eligibility blocker in `text`, as (reason, matched phrase).

    Callers pass the title and the REQUIRED section only. Passing the whole
    description would block on certifications listed under "Preferred" and on
    benefits boilerplate, which is the false positive this triage exists to
    avoid.
    """
    for reason, patterns in ELIGIBILITY_PATTERNS.items():
        for p in patterns:
            m = p.search(text or "")
            if m:
                return reason, m.group(0).strip()
    return None


# --------------------------------------------------------------------------
# Optional LLM requirement extraction
#
# A small local model is used strictly as an EXTRACTOR, never as a judge. It
# reads the required section and returns structured facts, each anchored to a
# verbatim quote so the output can be checked against the source. This closes
# the one gap regex cannot: telling "AWS, GCP, or Azure" (an alternative) from
# "multi-cloud including Azure" (a gate).
#
# It does not decide fit. Deciding still means matching these facts against
# candidate.yaml through the bridge's evaluation pipeline.
# --------------------------------------------------------------------------

REQUIREMENT_SCHEMA = {
    "type": "object",
    "properties": {
        "requirements": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "quote": {"type": "string"},
                    "skill": {"type": "string"},
                    "years_required": {"type": ["integer", "null"]},
                    "necessity": {"type": "string", "enum": ["required", "preferred"]},
                    "is_alternative": {"type": "boolean"},
                    "kind": {
                        "type": "string",
                        "enum": [
                            "technology",
                            "experience",
                            "credential",
                            "clearance",
                            "education",
                            "location",
                        ],
                    },
                },
                "required": [
                    "quote",
                    "skill",
                    "years_required",
                    "necessity",
                    "is_alternative",
                    "kind",
                ],
                # Required by OpenAI-style strict structured output (LM Studio).
                "additionalProperties": False,
            },
        }
    },
    "required": ["requirements"],
    "additionalProperties": False,
}

EXTRACTION_PROMPT = """You extract requirements from a job posting. You do not \
judge any candidate and you do not decide fit.

Rules:
- "quote" MUST be copied VERBATIM from the posting. Never paraphrase or invent.
- "skill" is the thing demanded (e.g. "Azure", "Kubernetes", "SRE experience").
- "years_required" is the number of years demanded, or null if unstated.
- "necessity" is "required" or "preferred" based on the heading it appears under.
- "is_alternative" is true when the item is one option in a list of acceptable
  choices ("AWS, GCP, or Azure" -> each is an alternative). It is false when the
  item is demanded on its own ("multi-cloud including Azure" -> not alternative).
- "kind" classifies the requirement.
- Extract every distinct requirement. Output JSON only.

JOB POSTING SECTION:
---
{section}
---
"""


def _post_json(url: str, payload: dict, timeout: int) -> dict:
    import json
    import urllib.request

    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # nosec B310
        return json.loads(resp.read())


class OllamaClient:
    """Minimal Ollama client (stdlib only, so the bridge gains no HTTP dependency)."""

    def __init__(self, url: str, model: str, timeout: int = 180, num_ctx: int = 16384):
        self.url = url.rstrip("/")
        self.model = model
        self.timeout = timeout
        self.num_ctx = num_ctx

    def extract(self, section: str) -> dict:
        import json

        payload = {
            "model": self.model,
            "prompt": EXTRACTION_PROMPT.format(section=section),
            "stream": False,
            # Grammar-constrained decoding: the model cannot emit malformed JSON.
            "format": REQUIREMENT_SCHEMA,
            # Ollama defaults to a 2048 context, which silently truncates these
            # postings and yields empty extractions. Be explicit.
            "options": {"num_ctx": self.num_ctx, "temperature": 0},
        }
        body = _post_json(f"{self.url}/api/generate", payload, self.timeout)
        return json.loads(body["response"])


class LMStudioClient:
    """LM Studio's local server is OpenAI-compatible, not Ollama-shaped.

    Differences that matter: the endpoint is /v1/chat/completions, structured
    output is requested via response_format.json_schema, and the payload comes
    back as a JSON string inside choices[0].message.content.

    Context length is a server-side setting in LM Studio (set it to 16384 when
    loading the model); it cannot be forced from the request, so a truncated
    posting will surface as a thin extraction rather than an error.
    """

    def __init__(self, url: str, model: str, timeout: int = 180):
        self.url = url.rstrip("/")
        self.model = model
        self.timeout = timeout

    def extract(self, section: str) -> dict:
        import json

        payload = {
            "model": self.model,
            "messages": [
                {
                    "role": "user",
                    "content": EXTRACTION_PROMPT.format(section=section),
                }
            ],
            "temperature": 0,
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "job_requirements",
                    "strict": True,
                    "schema": REQUIREMENT_SCHEMA,
                },
            },
        }
        body = _post_json(f"{self.url}/v1/chat/completions", payload, self.timeout)
        return json.loads(body["choices"][0]["message"]["content"])


CLIENTS = {"lmstudio": LMStudioClient, "ollama": OllamaClient}


def make_client(api: str, url: str, model: str):
    try:
        return CLIENTS[api](url, model)
    except KeyError:
        raise SystemExit(
            f"Unknown --llm-api '{api}'. Choose from: {', '.join(CLIENTS)}"
        )


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "")).strip().lower()


def verify_quotes(items: list[dict], source: str) -> tuple[list[dict], list[dict]]:
    """Split extracted items into (verified, unverified).

    An item is verified when its quote appears verbatim in the source section.
    This is the hallucination check: a model that invents a requirement cannot
    produce a quote that is actually present.
    """
    haystack = _normalize(source)
    verified: list[dict] = []
    unverified: list[dict] = []
    for item in items:
        quote = _normalize(item.get("quote", ""))
        (verified if quote and quote in haystack else unverified).append(item)
    return verified, unverified


def extract_requirements(section: str, client) -> dict:
    """Extract structured requirements from a section.

    Returns {"verified": [...], "unverified": [...], "error": str|None}. Any
    failure degrades to empty results rather than raising: the regex gates in
    the report remain the baseline.
    """
    if not section.strip():
        return {"verified": [], "unverified": [], "error": None}
    try:
        data = client.extract(section)
        items = data.get("requirements", []) if isinstance(data, dict) else []
    except Exception as exc:  # noqa: BLE001 - advisory path must never hard-fail
        return {"verified": [], "unverified": [], "error": str(exc)}
    verified, unverified = verify_quotes(items, section)
    return {"verified": verified, "unverified": unverified, "error": None}


def hard_gates(items: list[dict]) -> list[dict]:
    """Required, non-alternative items — the ones that actually disqualify."""
    return [
        i
        for i in items
        if i.get("necessity") == "required" and not i.get("is_alternative")
    ]


def load_jobs(db_path: Path, statuses: tuple[str, ...]) -> list[dict[str, Any]]:
    """Read the jobs to screen. The database is opened read-only."""
    return JobRepository(str(db_path), read_only=True).list_jobs_for_triage(statuses)


def enrich(queue: list[dict], client, top_n: int | None = None) -> list[dict]:
    """Attach LLM-extracted requirements to the first `top_n` queued jobs.

    Runs AFTER ordering, deliberately: extraction costs ~40s per posting against
    a local 8B, so extracting all 64 queued jobs to display three would waste
    most of an hour. Ordering never depends on extraction, so this is safe.
    """
    if client is None:
        return queue
    for job in queue[:top_n] if top_n else queue:
        job["extraction"] = extract_requirements(job["required_text"], client)
    return queue


def screen(
    jobs: list[dict[str, Any]], client=None
) -> tuple[list[dict], list[dict], int]:
    """Return (queue, blocked, already_decided).

    queue is ordered most-worth-reading-first. Ordering is advisory.

    `client` extracts for the whole queue and is kept for programmatic use; the
    CLI calls enrich() instead so it only pays for the jobs it displays.
    """
    queue: list[dict] = []
    blocked: list[dict] = []
    already_decided = 0

    for job in jobs:
        if job["source"] == "test" or job["company"] in TEST_COMPANIES:
            continue
        if job["decision"]:
            already_decided += 1
            continue

        title = job["title"] or ""
        description = job["description"] or ""
        info = {
            "id": job["job_id"],
            "ext_id": job["external_id"] or "Unknown",
            "title": title,
            "company": job["company"] or "Unknown",
            "comp": job["salary"] or "Unknown",
            "loc": job["location"] or "Unknown",
        }

        if not description.strip():
            info["reason"] = (
                "No description stored; not evaluable (enrich before review)."
            )
            blocked.append(info)
            continue

        sections = split_sections(description)
        req, pref = sections["required"], sections["preferred"]

        # Title-level specialty is a real signal; a mention buried in prose is not.
        title_specialty = specialty_in(title)
        if title_specialty:
            info["reason"] = (
                f"Title indicates a {title_specialty}-specialist role; "
                "no supporting evidence in candidate.yaml."
            )
            blocked.append(info)
            continue

        # Eligibility is binary and cheap to check, so it blocks before any
        # LLM extraction is paid for. Title + required only, never preferred.
        gate = eligibility_gate(f"{title}\n{req}")
        if gate:
            reason, phrase = gate
            info["reason"] = f"Blocked on {reason} (matched {phrase!r})."
            blocked.append(info)
            continue

        req_signals = signals(req)
        pref_signals = signals(pref)
        req_specialty = specialty_in(req)
        gates = extract_gates(req)

        info.update(
            {
                "required_signals": req_signals,
                "preferred_signals": pref_signals,
                "gates": gates,
                "required_specialty": req_specialty,
                "structured": sections["structured"],
                "required_text": req,
                "extraction": None,
            }
        )
        if client is not None:
            info["extraction"] = extract_requirements(req, client)
        queue.append(info)

    # Order: evidenced signals in the REQUIRED section first; specialty in the
    # required section pushes a job down; gates do not score, they are surfaced.
    queue.sort(
        key=lambda i: (
            -len(i["required_signals"]),
            1 if i["required_specialty"] else 0,
            -len(i["preferred_signals"]),
        )
    )
    return queue, blocked, already_decided


def format_report(
    queue: list[dict],
    blocked: list[dict],
    already_decided: int,
    shown: int | None = None,
) -> str:
    """Render the report. `shown` limits what is printed, never what is counted."""
    displayed = queue[:shown] if shown else queue
    lines = [
        "# Advisory review queue — ordering only, NOT an evaluation",
        "",
        "Keyword matching cannot tell a required skill from a preferred one, or",
        "read a quantified gate. Decide each job by reading its requirements via",
        "the bridge evaluation pipeline; this list only says what to read first.",
        "",
        f"Queued for review: {len(queue)} | Blocked: {len(blocked)} | "
        f"Already decided (excluded): {already_decided}",
        "",
        f"# REVIEW QUEUE ({len(queue)})"
        + (
            f" — showing the first {len(displayed)}"
            if shown and shown < len(queue)
            else ""
        ),
        "",
    ]
    for i, j in enumerate(displayed, 1):
        lines.append(f"{i}. {j['title']} — {j['company']}")
        lines.append(f"   - job_id: {j['id']}  (external_id: {j['ext_id']})")
        lines.append(f"   - compensation: {j['comp']} | location: {j['loc']}")
        lines.append(
            f"   - evidenced signals in REQUIRED ({len(j['required_signals'])}): "
            f"{', '.join(j['required_signals']) or 'none'}"
        )
        lines.append(
            f"   - evidenced signals in PREFERRED ({len(j['preferred_signals'])}): "
            f"{', '.join(j['preferred_signals']) or 'none'}"
        )
        if j["gates"]:
            lines.append("   - QUANTIFIED GATES (verify against evidence):")
            for g in j["gates"]:
                lines.append(f"       * {g}")
        if j["required_specialty"]:
            lines.append(
                f"   - CAUTION: {j['required_specialty']} appears in the required "
                "section; confirm whether it is a hard requirement."
            )
        if not j["structured"]:
            lines.append(
                "   - NOTE: no required/preferred headings found; whole posting "
                "treated as required."
            )
        ex = j.get("extraction")
        if ex:
            if ex["error"]:
                lines.append(
                    f"   - extraction unavailable ({ex['error'][:60]}); "
                    "regex gates above are the baseline."
                )
            else:
                gates_x = hard_gates(ex["verified"])
                lines.append(
                    f"   - EXTRACTED REQUIREMENTS: {len(ex['verified'])} verified, "
                    f"{len(gates_x)} hard (required and not an alternative)"
                )
                for g in gates_x:
                    yrs = (
                        f"{g['years_required']}+ yrs "
                        if g.get("years_required")
                        else ""
                    )
                    lines.append(f"       ! {yrs}{g['skill']} [{g['kind']}]")
                alts = [i for i in ex["verified"] if i.get("is_alternative")]
                if alts:
                    lines.append(
                        "       ~ alternatives (one of): "
                        + ", ".join(sorted({i["skill"] for i in alts}))
                    )
                if ex["unverified"]:
                    lines.append(
                        f"       ? {len(ex['unverified'])} item(s) DISCARDED — quote "
                        "not found in the posting (model may have invented them)"
                    )
        lines.append("")

    lines.append(f"# BLOCKED ({len(blocked)})")
    lines.append("")
    for j in blocked:
        lines.append(f"- {j['title']} — {j['company']} ({j['ext_id']})")
        lines.append(f"  - reason: {j['reason']}")
        lines.append("")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--db", type=Path, default=DEFAULT_DB, help="Path to the bridge jobs.db"
    )
    parser.add_argument(
        "--output", type=Path, default=None, help="Write the report here (else stdout)"
    )
    parser.add_argument(
        "--limit", type=int, default=None, help="Only show the first N queued jobs"
    )
    parser.add_argument(
        "--status",
        default=DEFAULT_STATUS,
        help=f"Comma-separated application_status values to screen (default: {DEFAULT_STATUS})",
    )
    parser.add_argument(
        "--extract",
        action="store_true",
        help="Use a local LLM to extract structured requirements (advisory; never decides)",
    )
    parser.add_argument(
        "--llm-api",
        default=os.environ.get("SCREEN_LLM_API", "lmstudio"),
        choices=sorted(CLIENTS),
        help="Local LLM server flavour (env: SCREEN_LLM_API)",
    )
    parser.add_argument(
        "--llm-url",
        default=os.environ.get("SCREEN_LLM_URL", "http://localhost:1234"),
        help="Base URL of the local LLM server (env: SCREEN_LLM_URL)",
    )
    parser.add_argument(
        "--llm-model",
        default=os.environ.get("SCREEN_LLM_MODEL", "qwen2.5-7b-instruct"),
        help="Model name as the server reports it (env: SCREEN_LLM_MODEL)",
    )
    args = parser.parse_args()

    statuses = tuple(s.strip() for s in args.status.split(",") if s.strip())
    queue, blocked, decided = screen(load_jobs(args.db, statuses))
    if args.extract:
        # Extract only for what will be displayed: ~40s per posting on a local 8B.
        enrich(
            queue,
            make_client(args.llm_api, args.llm_url, args.llm_model),
            top_n=args.limit,
        )
    report = format_report(queue, blocked, decided, shown=args.limit)
    if args.output:
        args.output.write_text(report)
        print(f"Wrote report to {args.output}")
    else:
        print(report)


if __name__ == "__main__":
    main()
