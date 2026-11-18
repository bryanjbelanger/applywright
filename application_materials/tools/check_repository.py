import json
import re
import sys
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

import jsonschema
import yaml

from applywright.application_packages import review_findings

FIXED_OUTPUT_FILES = {
    "Resume.html",
    "Resume.pdf",
    "CoverLetter.html",
    "CoverLetter.pdf",
    "application.css",
    "validation.json",
}
PNG_PATTERN = re.compile(r"^(Resume|CoverLetter)-page-([1-9][0-9]*)\.png$")
SOURCE_PATH_PATTERN = re.compile(r"application_materials/[A-Za-z0-9_./-]+")


class HtmlStylePolicyParser(HTMLParser):
    """Collect stylesheet and inline-style usage from generated HTML."""

    def __init__(self) -> None:
        super().__init__()
        self.style_tags = 0
        self.style_attributes = 0
        self.stylesheet_hrefs: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag_lower = tag.lower()
        attr_map = {name.lower(): value for name, value in attrs}

        if tag_lower == "style":
            self.style_tags += 1
        if "style" in attr_map:
            self.style_attributes += 1

        if tag_lower == "link":
            rel = (attr_map.get("rel") or "").lower().split()
            if "stylesheet" in rel:
                self.stylesheet_hrefs.append(attr_map.get("href") or "")


def report_error(job_slug: str, path: Path, policy: str, correction: str) -> None:
    print(f"ERROR | Job: {job_slug} | Path: {path}")
    print(f"  Policy: {policy}")
    print(f"  Correction: {correction}\n")


def _load_json(path: Path) -> Any:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def _load_yaml(path: Path) -> Any:
    with path.open(encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def _collect_evidence_ids(resume_data: dict[str, Any]) -> set[str]:
    evidence_ids: set[str] = set()
    evidence_ids.update(resume_data.get("summary", {}).get("evidence_ids", []))

    for skill in resume_data.get("core_skills", []):
        evidence_ids.update(skill.get("evidence_ids", []))

    for experience in resume_data.get("experience", []):
        evidence_ids.update(experience.get("overview", {}).get("evidence_ids", []))
        for engagement in experience.get("engagements", []):
            evidence_ids.update(engagement.get("overview", {}).get("evidence_ids", []))
            for achievement in engagement.get("achievements", []):
                evidence_ids.update(achievement.get("evidence_ids", []))

    return evidence_ids


def _parse_evidence_matrix(
    matrix_content: str,
) -> tuple[dict[str, list[str]], set[str]]:
    """Return evidence rows and source paths from markdown table rows only."""

    rows: dict[str, list[str]] = {}
    source_paths: set[str] = set()

    for raw_line in matrix_content.splitlines():
        line = raw_line.strip()
        if not line.startswith("|"):
            continue

        cells = [cell.strip() for cell in line.strip("|").split("|")]
        if len(cells) < 3:
            continue

        evidence_id = cells[0].strip("`").strip()
        if evidence_id in {"Evidence ID", "---"} or not evidence_id:
            continue
        if set(evidence_id) == {"-"}:
            continue

        source_cell = cells[2]
        rows.setdefault(evidence_id, []).append(source_cell)
        source_paths.update(SOURCE_PATH_PATTERN.findall(source_cell))

    return rows, source_paths


def _check_html_styles(job: str, html_path: Path, fail: Any) -> None:
    try:
        content = html_path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        fail(
            job,
            html_path,
            "generated HTML is readable UTF-8",
            f"Rerender the file: {exc}",
        )
        return

    parser = HtmlStylePolicyParser()
    try:
        parser.feed(content)
    except Exception as exc:
        fail(
            job,
            html_path,
            "generated HTML can be parsed",
            f"Rerender valid HTML: {exc}",
        )
        return

    if parser.style_tags:
        fail(
            job,
            html_path,
            "generated HTML contains no <style> blocks",
            "Move styling to application_materials/styles/application.css and rerender",
        )
    if parser.style_attributes:
        fail(
            job,
            html_path,
            "generated HTML contains no inline style= attributes",
            "Move styling to the shared stylesheet and rerender",
        )
    if parser.stylesheet_hrefs != ["application.css"]:
        fail(
            job,
            html_path,
            "generated HTML references exactly one stylesheet: application.css",
            "Use only the generated application.css link and rerender",
        )


def _check_job(
    job_dir: Path,
    base_dir: Path,
    repo_root: Path,
    catalog: dict[str, Any],
    fail: Any,
) -> None:
    job = job_dir.name
    resume_yaml = job_dir / "resume.yaml"
    cover_letter_yaml = job_dir / "cover_letter.yaml"
    evidence_matrix = job_dir / "evidence_matrix.md"
    output_dir = job_dir / "output"

    required_job_paths = [
        (resume_yaml, "resume.yaml exists", "Create resume.yaml"),
        (
            cover_letter_yaml,
            "cover_letter.yaml exists",
            "Create cover_letter.yaml",
        ),
        (
            evidence_matrix,
            "evidence_matrix.md exists",
            "Create evidence_matrix.md",
        ),
    ]
    for path, policy, correction in required_job_paths:
        if not path.is_file():
            fail(job, path, policy, correction)

    if not output_dir.is_dir():
        fail(
            job,
            output_dir,
            "output/ directory exists",
            "Render the application to create output/",
        )

    resume_data: dict[str, Any] = {}
    resume_schema = base_dir / "schemas" / "resume.schema.json"
    if resume_yaml.is_file() and resume_schema.is_file():
        try:
            resume_data = _load_yaml(resume_yaml) or {}
            jsonschema.validate(
                instance=resume_data,
                schema=_load_json(resume_schema),
            )
        except Exception as exc:
            fail(
                job,
                resume_yaml,
                "resume.yaml validates against resume.schema.json",
                f"Fix resume schema errors: {exc}",
            )

    cover_letter_schema = base_dir / "schemas" / "cover_letter.schema.json"
    if cover_letter_yaml.is_file() and cover_letter_schema.is_file():
        try:
            cover_letter_data = _load_yaml(cover_letter_yaml) or {}
            jsonschema.validate(
                instance=cover_letter_data,
                schema=_load_json(cover_letter_schema),
            )
        except Exception as exc:
            fail(
                job,
                cover_letter_yaml,
                "cover_letter.yaml validates against cover_letter.schema.json",
                f"Fix cover-letter schema errors: {exc}",
            )

    evidence_ids = _collect_evidence_ids(resume_data)
    for evidence_id in sorted(evidence_ids):
        if evidence_id not in catalog:
            fail(
                job,
                resume_yaml,
                "every resume evidence ID exists in candidate.yaml",
                f"Add {evidence_id} to candidate.yaml or remove the unsupported claim",
            )

    if evidence_matrix.is_file():
        try:
            matrix_content = evidence_matrix.read_text(encoding="utf-8")
            matrix_rows, source_paths = _parse_evidence_matrix(matrix_content)
        except (OSError, UnicodeError) as exc:
            fail(
                job,
                evidence_matrix,
                "evidence_matrix.md is readable UTF-8",
                f"Fix the evidence matrix: {exc}",
            )
            matrix_rows, source_paths = {}, set()

        for evidence_id in sorted(evidence_ids):
            row_count = len(matrix_rows.get(evidence_id, []))
            if row_count != 1:
                fail(
                    job,
                    evidence_matrix,
                    "every resume evidence ID has exactly one evidence-matrix row",
                    f"Expected one row for {evidence_id}; found {row_count}",
                )

        for source_path in sorted(source_paths):
            resolved = repo_root / source_path
            if not resolved.is_file():
                fail(
                    job,
                    evidence_matrix,
                    "evidence-matrix source paths resolve to repository files",
                    f"Add or correct source path {source_path}",
                )

    for path in job_dir.rglob("*"):
        if not path.is_file():
            continue
        if output_dir == path.parent or output_dir in path.parents:
            continue

        relative = path.relative_to(job_dir)
        suffix = path.suffix.lower()
        name = path.name.lower()

        if suffix == ".py":
            fail(
                job,
                path,
                "no Python renderer exists anywhere inside a job directory",
                f"Remove {relative}; use the shared renderer",
            )
        if suffix == ".css":
            fail(
                job,
                path,
                "no source CSS exists anywhere inside a job directory",
                f"Remove {relative}; use application_materials/styles/application.css",
            )
        if name in {"resume.md", "cover_letter.md"}:
            fail(
                job,
                path,
                "no canonical resume.md or cover_letter.md exists under jobs/",
                f"Remove {relative}; use YAML sources",
            )
        if suffix in {".j2", ".jinja2", ".html"}:
            fail(
                job,
                path,
                "no copied HTML or Jinja2 template exists inside a job directory",
                f"Remove {relative}; use shared templates",
            )

    if not output_dir.is_dir():
        return

    output_files = {
        path.name: path for path in output_dir.iterdir() if path.is_file()
    }
    for filename in sorted(FIXED_OUTPUT_FILES):
        if filename not in output_files:
            fail(
                job,
                output_dir / filename,
                f"expected generated file {filename} exists",
                f"Rerender to generate {filename}",
            )

    page_numbers: dict[str, list[int]] = {
        "Resume": [],
        "CoverLetter": [],
    }
    unknown_output_files: list[str] = []

    for filename in output_files:
        if filename in FIXED_OUTPUT_FILES:
            continue
        match = PNG_PATTERN.fullmatch(filename)
        if match:
            document, page_text = match.groups()
            page_numbers[document].append(int(page_text))
        else:
            unknown_output_files.append(filename)

    for filename in sorted(unknown_output_files):
        fail(
            job,
            output_dir / filename,
            "output/ contains only expected generated artifact classes",
            f"Remove unexpected output file {filename} and rerender if needed",
        )

    for document, pages in page_numbers.items():
        if not pages:
            fail(
                job,
                output_dir,
                f"at least one {document}-page-*.png exists",
                f"Rerender the {document} PDF pages",
            )
            continue

        ordered = sorted(pages)
        expected = list(range(1, max(ordered) + 1))
        if ordered != expected:
            fail(
                job,
                output_dir,
                f"{document} PNG numbering is contiguous and starts at page 1",
                f"Expected pages {expected}; found {ordered}",
            )

    validation_path = output_dir / "validation.json"
    if validation_path.is_file():
        try:
            validation_data = _load_json(validation_path)
        except Exception as exc:
            fail(
                job,
                validation_path,
                "validation.json is valid JSON",
                f"Rerender validation output: {exc}",
            )
            validation_data = {}

        for finding in review_findings(job, validation_data, output_files):
            fail(job, validation_path, finding.policy, finding.correction)

    for html_name in ("Resume.html", "CoverLetter.html"):
        html_path = output_dir / html_name
        if html_path.is_file():
            _check_html_styles(job, html_path, fail)

    generated_css = output_dir / "application.css"
    shared_css = base_dir / "styles" / "application.css"
    if generated_css.is_file() and shared_css.is_file():
        try:
            if generated_css.read_bytes() != shared_css.read_bytes():
                fail(
                    job,
                    generated_css,
                    "generated stylesheet matches the shared stylesheet byte-for-byte",
                    "Rerender to refresh output/application.css",
                )
        except OSError as exc:
            fail(
                job,
                generated_css,
                "stylesheets are readable",
                f"Fix stylesheet access: {exc}",
            )


def check_repository(
    base_dir: Path | str = Path("application_materials"),
    repo_root: Path | str = Path("."),
) -> bool:
    base_dir = Path(base_dir)
    repo_root = Path(repo_root)
    all_passed = True

    def fail(job: str, path: Path, policy: str, correction: str) -> None:
        nonlocal all_passed
        all_passed = False
        report_error(job, path, policy, correction)

    required_dirs = [
        "schemas",
        "templates",
        "styles",
        "tools",
        "tests",
    ]
    for directory in required_dirs:
        path = base_dir / directory
        if not path.is_dir():
            fail(
                "GLOBAL",
                path,
                f"{directory}/ directory exists",
                f"Create {path}",
            )

    candidate_file = base_dir / "candidate.yaml"
    candidate_schema_file = base_dir / "schemas" / "candidate.schema.json"
    candidate_data: dict[str, Any] = {}

    if not candidate_file.is_file():
        fail(
            "GLOBAL",
            candidate_file,
            "candidate.yaml exists",
            "Copy application_materials/candidate.example.yaml to "
            "application_materials/candidate.yaml and edit it",
        )
    elif not candidate_schema_file.is_file():
        fail(
            "GLOBAL",
            candidate_schema_file,
            "candidate.schema.json exists",
            "Restore the candidate schema",
        )
    else:
        try:
            candidate_data = _load_yaml(candidate_file) or {}
            jsonschema.validate(
                instance=candidate_data,
                schema=_load_json(candidate_schema_file),
            )
        except Exception as exc:
            fail(
                "GLOBAL",
                candidate_file,
                "candidate.yaml validates against candidate.schema.json",
                f"Fix candidate data or schema errors: {exc}",
            )

    catalog = candidate_data.get("evidence_catalog", {})
    if not isinstance(catalog, dict):
        catalog = {}

    jobs_dir = base_dir / "jobs"
    if not jobs_dir.is_dir():
        return all_passed

    job_dirs = sorted(path for path in jobs_dir.iterdir() if path.is_dir())

    for job_dir in job_dirs:
        _check_job(job_dir, base_dir, repo_root, catalog, fail)

    return all_passed


def check_package(
    job_dir: Path | str,
    base_dir: Path | str = Path("application_materials"),
    repo_root: Path | str = Path("."),
) -> bool:
    """Apply the per-package policies to one directory under ``jobs/``.

    Repository-wide policies, such as the required directories, are not checked.
    """
    base_dir = Path(base_dir)
    all_passed = True

    def fail(job: str, path: Path, policy: str, correction: str) -> None:
        nonlocal all_passed
        all_passed = False
        report_error(job, path, policy, correction)

    try:
        catalog = _load_yaml(base_dir / "candidate.yaml").get("evidence_catalog", {})
    except Exception:
        catalog = {}
    if not isinstance(catalog, dict):
        catalog = {}

    _check_job(Path(job_dir), base_dir, Path(repo_root), catalog, fail)
    return all_passed


if __name__ == "__main__":
    if check_repository():
        print("Repository structure policy checks passed.")
        sys.exit(0)

    print("Repository structure policy checks failed.")
    sys.exit(1)
