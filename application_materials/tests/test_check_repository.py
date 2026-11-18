import json
import shutil
from pathlib import Path

import pytest
import yaml

from application_materials.tools.check_repository import check_package, check_repository


@pytest.fixture
def test_repo(tmp_path: Path) -> tuple[Path, Path]:
    repo_root = tmp_path / "repo"
    base_dir = repo_root / "application_materials"

    for directory in [
        "schemas",
        "templates",
        "styles",
        "tools",
        "tests",
        "sources",
        "jobs/sample-job/output",
        "legacy",
    ]:
        (base_dir / directory).mkdir(parents=True, exist_ok=True)

    real_application_dir = Path(__file__).resolve().parents[1]
    for schema_name in [
        "candidate.schema.json",
        "resume.schema.json",
        "cover_letter.schema.json",
    ]:
        shutil.copy2(
            real_application_dir / "schemas" / schema_name,
            base_dir / "schemas" / schema_name,
        )

    shared_css = "body { font-family: sans-serif; }\n"
    (base_dir / "styles" / "application.css").write_text(shared_css, encoding="utf-8")
    (base_dir / "sources" / "facts.md").write_text(
        "# Verified facts\n\n- Supported claim.\n", encoding="utf-8"
    )
    (base_dir / "legacy" / "README.md").write_text("# Legacy\n", encoding="utf-8")

    candidate = {
        "name": "Sample Candidate",
        "email": "sample@example.com",
        "phone": "555-0100",
        "location": "Sample City",
        "education": [
            {
                "degree": "Bachelor of Science",
                "institution": "Sample University",
            }
        ],
        "certifications": [],
        "evidence_catalog": {"evidence_1": "Supported claim."},
    }
    resume = {
        "summary": {
            "text": "Supported summary.",
            "evidence_ids": ["evidence_1"],
        },
        "core_skills": [
            {
                "text": "Supported skill.",
                "evidence_ids": ["evidence_1"],
            }
        ],
        "experience": [
            {
                "employer": "Sample Employer",
                "title": "Engineer",
                "start_year": "2020",
                "end_year": "2024",
                "overview": {
                    "text": "Supported overview.",
                    "evidence_ids": ["evidence_1"],
                },
                "engagements": [
                    {
                        "client": "Sample Client",
                        "overview": {
                            "text": "Supported engagement.",
                            "evidence_ids": ["evidence_1"],
                        },
                        "achievements": [
                            {
                                "text": "Supported achievement.",
                                "evidence_ids": ["evidence_1"],
                            }
                        ],
                    }
                ],
            }
        ],
    }
    cover_letter = {
        "company_name": "Sample Company",
        "position": "Engineer",
        "paragraphs": ["Sample paragraph."],
    }

    (base_dir / "candidate.yaml").write_text(
        yaml.safe_dump(candidate, sort_keys=False), encoding="utf-8"
    )
    job_dir = base_dir / "jobs" / "sample-job"
    (job_dir / "resume.yaml").write_text(
        yaml.safe_dump(resume, sort_keys=False), encoding="utf-8"
    )
    (job_dir / "cover_letter.yaml").write_text(
        yaml.safe_dump(cover_letter, sort_keys=False), encoding="utf-8"
    )
    (job_dir / "evidence_matrix.md").write_text(
        "\n".join(
            [
                "# Evidence Matrix",
                "",
                "The private original may be named `application_materials/missing-private.docx`, but it is not a table source.",
                "",
                "| Evidence ID | Verified claim | Source file | Source location | Used in | Notes |",
                "|---|---|---|---|---|---|",
                "| `evidence_1` | Supported claim | `application_materials/sources/facts.md` | Facts | Resume | Verified |",
                "",
            ]
        ),
        encoding="utf-8",
    )

    output_dir = job_dir / "output"
    valid_html = (
        '<!doctype html><html><head><link rel="stylesheet" '
        'href="application.css"></head><body>Content</body></html>'
    )
    for html_name in ["Resume.html", "CoverLetter.html"]:
        (output_dir / html_name).write_text(valid_html, encoding="utf-8")
    for pdf_name in ["Resume.pdf", "CoverLetter.pdf"]:
        (output_dir / pdf_name).write_bytes(b"%PDF-1.4\n")
    for png_name in ["Resume-page-1.png", "CoverLetter-page-1.png"]:
        (output_dir / png_name).write_bytes(b"PNG")
    (output_dir / "application.css").write_text(shared_css, encoding="utf-8")
    validation = {
        "automated_validation": {
            "passed": True,
            "checks": {"all": "passed"},
        },
        "visual_review": {
            "status": "passed",
            "reviewed_pages": [
                "application_materials/jobs/sample-job/output/Resume-page-1.png",
                "application_materials/jobs/sample-job/output/CoverLetter-page-1.png",
            ],
            "findings": ["Reviewed."],
        },
    }
    (output_dir / "validation.json").write_text(
        json.dumps(validation, indent=2), encoding="utf-8"
    )

    return base_dir, repo_root


def check(test_repo: tuple[Path, Path]) -> bool:
    base_dir, repo_root = test_repo
    return check_repository(base_dir=base_dir, repo_root=repo_root)


def job_dir(test_repo: tuple[Path, Path]) -> Path:
    return test_repo[0] / "jobs" / "sample-job"


def output_dir(test_repo: tuple[Path, Path]) -> Path:
    return job_dir(test_repo) / "output"


def test_valid_structured_job_passes(test_repo):
    assert check(test_repo) is True


def test_missing_resume_yaml_fails(test_repo):
    (job_dir(test_repo) / "resume.yaml").unlink()
    assert check(test_repo) is False


def test_generate_and_test_py_fails(test_repo):
    (job_dir(test_repo) / "generate_and_test.py").touch()
    assert check(test_repo) is False


def test_nested_python_renderer_fails(test_repo):
    nested = job_dir(test_repo) / "helpers"
    nested.mkdir()
    (nested / "render.py").touch()
    assert check(test_repo) is False


def test_source_css_fails(test_repo):
    (job_dir(test_repo) / "custom.css").touch()
    assert check(test_repo) is False


def test_nested_jinja_template_fails(test_repo):
    nested = job_dir(test_repo) / "templates"
    nested.mkdir()
    (nested / "resume.html.j2").touch()
    assert check(test_repo) is False


def test_canonical_resume_md_fails(test_repo):
    (job_dir(test_repo) / "resume.md").touch()
    assert check(test_repo) is False


def test_missing_evidence_id_fails(test_repo):
    path = job_dir(test_repo) / "resume.yaml"
    path.write_text(
        path.read_text(encoding="utf-8").replace("evidence_1", "missing_evidence"),
        encoding="utf-8",
    )
    assert check(test_repo) is False


def test_missing_evidence_matrix_row_fails(test_repo):
    path = job_dir(test_repo) / "evidence_matrix.md"
    path.write_text(
        "\n".join(
            line
            for line in path.read_text(encoding="utf-8").splitlines()
            if "`evidence_1`" not in line
        ),
        encoding="utf-8",
    )
    assert check(test_repo) is False


def test_missing_evidence_source_path_fails(test_repo):
    path = job_dir(test_repo) / "evidence_matrix.md"
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            "application_materials/sources/facts.md",
            "application_materials/sources/missing.md",
        ),
        encoding="utf-8",
    )
    assert check(test_repo) is False


def test_non_table_private_source_reference_is_ignored(test_repo):
    assert check(test_repo) is True


def test_visual_review_required_fails(test_repo):
    path = output_dir(test_repo) / "validation.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["visual_review"]["status"] = "required"
    path.write_text(json.dumps(data), encoding="utf-8")
    assert check(test_repo) is False


def test_incomplete_reviewed_pages_fails(test_repo):
    path = output_dir(test_repo) / "validation.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["visual_review"]["reviewed_pages"].pop()
    path.write_text(json.dumps(data), encoding="utf-8")
    assert check(test_repo) is False


def test_missing_resume_png_fails(test_repo):
    (output_dir(test_repo) / "Resume-page-1.png").unlink()
    assert check(test_repo) is False


def test_missing_cover_letter_png_fails(test_repo):
    (output_dir(test_repo) / "CoverLetter-page-1.png").unlink()
    assert check(test_repo) is False


def test_page_numbering_must_start_at_one(test_repo):
    output = output_dir(test_repo)
    (output / "Resume-page-1.png").rename(output / "Resume-page-2.png")
    validation_path = output / "validation.json"
    data = json.loads(validation_path.read_text(encoding="utf-8"))
    data["visual_review"]["reviewed_pages"][
        0
    ] = "application_materials/jobs/sample-job/output/Resume-page-2.png"
    validation_path.write_text(json.dumps(data), encoding="utf-8")
    assert check(test_repo) is False


def test_extra_stale_png_fails(test_repo):
    output = output_dir(test_repo)
    (output / "Resume-page-3.png").touch()
    validation_path = output / "validation.json"
    data = json.loads(validation_path.read_text(encoding="utf-8"))
    data["visual_review"]["reviewed_pages"].append(
        "application_materials/jobs/sample-job/output/Resume-page-3.png"
    )
    validation_path.write_text(json.dumps(data), encoding="utf-8")
    assert check(test_repo) is False


def test_unknown_output_artifact_fails(test_repo):
    (output_dir(test_repo) / "notes.txt").touch()
    assert check(test_repo) is False


def test_generated_stylesheet_differs_fails(test_repo):
    with (output_dir(test_repo) / "application.css").open(
        "a", encoding="utf-8"
    ) as handle:
        handle.write("/* changed */\n")
    assert check(test_repo) is False


def test_inline_style_block_fails(test_repo):
    path = output_dir(test_repo) / "Resume.html"
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            "</head>", "<style>body{}</style></head>"
        ),
        encoding="utf-8",
    )
    assert check(test_repo) is False


def test_inline_style_attribute_fails(test_repo):
    path = output_dir(test_repo) / "Resume.html"
    path.write_text(
        path.read_text(encoding="utf-8").replace("<body>", '<body style="margin:0">'),
        encoding="utf-8",
    )
    assert check(test_repo) is False


def test_additional_stylesheet_fails(test_repo):
    path = output_dir(test_repo) / "Resume.html"
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            "</head>", '<link rel="stylesheet" href="extra.css"></head>'
        ),
        encoding="utf-8",
    )
    assert check(test_repo) is False


def test_empty_jobs_directory_passes(test_repo):
    shutil.rmtree(job_dir(test_repo))
    assert check(test_repo) is True


def test_missing_jobs_directory_passes(test_repo):
    shutil.rmtree(test_repo[0] / "jobs")
    assert check(test_repo) is True


def test_missing_candidate_file_fails(test_repo):
    (test_repo[0] / "candidate.yaml").unlink()
    assert check(test_repo) is False


def check_one_package(test_repo: tuple[Path, Path], name: str = "sample-job") -> bool:
    base_dir, repo_root = test_repo
    return check_package(base_dir / "jobs" / name, base_dir, repo_root)


def test_check_package_passes_a_valid_package(test_repo):
    assert check_one_package(test_repo) is True


def test_check_package_fails_an_invalid_package(test_repo):
    path = output_dir(test_repo) / "validation.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["visual_review"]["status"] = "required"
    path.write_text(json.dumps(data), encoding="utf-8")
    assert check_one_package(test_repo) is False


def test_check_package_ignores_a_broken_sibling_package(test_repo):
    base_dir, _ = test_repo
    shutil.copytree(job_dir(test_repo), base_dir / "jobs" / "broken-job")
    (base_dir / "jobs" / "broken-job" / "resume.yaml").unlink()

    assert check(test_repo) is False
    assert check_one_package(test_repo) is True
    assert check_one_package(test_repo, "broken-job") is False


def test_check_package_ignores_repository_wide_policies(test_repo):
    base_dir, _ = test_repo
    shutil.rmtree(base_dir / "tools")

    assert check(test_repo) is False
    assert check_one_package(test_repo) is True
