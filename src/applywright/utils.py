import hashlib
import re
from urllib.parse import urlparse, urlunparse
from typing import Optional, Tuple


def canonicalize_url(url: str) -> str:
    """Canonicalize a URL for stable deduplication by stripping query params and fragments."""
    if not url:
        return ""
    try:
        parsed = urlparse(url)
        # Keep only scheme and netloc, strip path, params, query, fragment
        # Or maybe keep path but strip query?
        # A canonical URL usually keeps the path because /job/123 is the job.
        # Let's keep path, but drop query params like ?utm_source=...
        return urlunparse(
            (parsed.scheme, parsed.netloc, parsed.path, "", "", "")
        ).lower()
    except Exception:
        return url.lower()


def parse_jobcopilot_review_url(url: str) -> Optional[Tuple[str, str]]:
    """
    Parse a JobCopilot review URL and extract its canonical form and external ID.
    Returns (canonical_url, external_id) if valid, else None.
    Rules:
    - protocol exactly https
    - hostname exactly app.jobcopilot.com
    - port is empty
    - username is empty
    - password is empty
    - pathname matches exactly /applications/review/<external_id>
    - optional trailing slash accepted
    - query and fragment accepted only as input and removed from canonical output
    - external_id must match ^[A-Za-z0-9_-]+$
    """
    if not url:
        return None
    try:
        parsed = urlparse(url)
        if parsed.scheme != "https" or parsed.hostname != "app.jobcopilot.com":
            return None
        if parsed.port or parsed.username or parsed.password:
            return None
        if parsed.params:
            return None

        path = parsed.path
        if path.endswith("/"):
            path = path[:-1]

        parts = path.split("/")
        if len(parts) != 4 or parts[1] != "applications" or parts[2] != "review":
            return None

        ext_id = parts[3]
        if not re.match(r"^[A-Za-z0-9_-]+$", ext_id):
            return None

        canonical_url = f"https://app.jobcopilot.com/applications/review/{ext_id}"
        return (canonical_url, ext_id)
    except Exception:
        return None


def parse_linkedin_job_url(url: str) -> Optional[Tuple[str, str]]:
    """
    Parse a LinkedIn job URL and return (canonical_url, job_id) or None.
    Accepts https://www.linkedin.com/jobs/view/<digits>[/] with optional query
    and fragment, which are dropped from the canonical form.
    """
    if not url:
        return None
    try:
        parsed = urlparse(url)
        if parsed.scheme != "https" or parsed.hostname != "www.linkedin.com":
            return None
        if parsed.port or parsed.username or parsed.password or parsed.params:
            return None
        parts = parsed.path.rstrip("/").split("/")
        if len(parts) != 4 or parts[1] != "jobs" or parts[2] != "view":
            return None
        job_id = parts[3]
        if not re.fullmatch(r"[0-9]+", job_id):
            return None
        return (f"https://www.linkedin.com/jobs/view/{job_id}/", job_id)
    except Exception:
        return None


def generate_dedupe_key(source: str, company: str, title: str, job_url: str) -> str:
    """Generate a stable hash for deduplication based on normalized fields."""
    norm_source = (source or "").strip().lower()
    norm_company = (company or "").strip().lower()
    norm_title = (title or "").strip().lower()
    norm_url = canonicalize_url((job_url or "").strip())

    # Concatenate with a delimiter that shouldn't appear in the strings
    raw = f"{norm_source}|{norm_company}|{norm_title}|{norm_url}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()
