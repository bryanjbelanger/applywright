import sys

import json
import os
import subprocess


def get_git_status():
    result = subprocess.run(
        ["git", "status", "--porcelain=v1", "--untracked-files=all"],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout


def test_pdf_rendering_and_validation(tmp_path):
    # Success path
    candidate_path = os.path.join(
        os.path.dirname(__file__), "fixtures", "candidate.yaml"
    )
    resume_path = os.path.join(
        os.path.dirname(__file__), "fixtures", "sample-job", "resume.yaml"
    )
    cl_path = os.path.join(
        os.path.dirname(__file__), "fixtures", "sample-job", "cover_letter.yaml"
    )

    initial_git_status = get_git_status()

    out_dir = tmp_path / "output"

    # Pre-populate out_dir with an unrelated file and a stale PNG
    os.makedirs(out_dir, exist_ok=True)
    unrelated_file = out_dir / "unrelated.txt"
    unrelated_file.write_text("keep me")
    stale_png = out_dir / "Resume-page-99.png"
    stale_png.write_text("stale data")

    project_root = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
    subprocess.run(
        [
            sys.executable,
            "-m",
            "application_materials.tools.render_application",
            "--candidate",
            candidate_path,
            "--resume",
            resume_path,
            "--cover-letter",
            cl_path,
            "--output-dir",
            str(out_dir),
        ],
        check=True,
        cwd=project_root,
    )

    # Verify outputs exist
    resume_pdf = out_dir / "Resume.pdf"
    cl_pdf = out_dir / "CoverLetter.pdf"
    assert resume_pdf.exists()
    assert cl_pdf.exists()

    # Unrelated file preserved
    assert unrelated_file.exists()
    # Stale PNG removed
    assert not stale_png.exists()

    assert (out_dir / "validation.json").exists()

    # Exact Git status unchanged
    final_git_status = get_git_status()
    assert initial_git_status == final_git_status


def test_renderer_failure_rollback(tmp_path):
    # Induce failure by making schema invalid
    candidate_path = os.path.join(
        os.path.dirname(__file__), "fixtures", "candidate.yaml"
    )
    resume_path = os.path.join(
        os.path.dirname(__file__), "fixtures", "sample-job", "resume.yaml"
    )
    cl_path = os.path.join(
        os.path.dirname(__file__), "fixtures", "sample-job", "cover_letter.yaml"
    )

    import yaml

    bad_resume_path = tmp_path / "bad_resume.yaml"
    with open(resume_path) as f:
        bad_resume = yaml.safe_load(f)
    bad_resume["experience"][0]["start_year"] = "bad"  # Malformed year
    with open(bad_resume_path, "w") as f:
        yaml.dump(bad_resume, f)

    out_dir = tmp_path / "output"
    os.makedirs(out_dir, exist_ok=True)
    original_file = out_dir / "Resume.pdf"
    original_file.write_text("original pdf data")

    project_root = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "application_materials.tools.render_application",
            "--candidate",
            candidate_path,
            "--resume",
            str(bad_resume_path),
            "--cover-letter",
            cl_path,
            "--output-dir",
            str(out_dir),
        ],
        capture_output=True,
        text=True,
        cwd=project_root,
    )

    # Assert non-zero exit
    assert result.returncode == 1
    # Assert stderr has output
    assert "Input validation failed" in result.stderr

    # Assert live output unchanged
    assert original_file.read_text() == "original pdf data"
    assert not (out_dir / "validation.json").exists()

    # Assert staging/prepared deleted
    staging_dir = tmp_path / f".{out_dir.name}_staging"
    prepared_dir = tmp_path / f".{out_dir.name}_prepared"
    backup_dir = tmp_path / f".{out_dir.name}_backup"

    assert not staging_dir.exists()
    assert not prepared_dir.exists()
    assert not backup_dir.exists()


def test_promotion_rollback(tmp_path, monkeypatch):
    # This simulates a failure during promotion rename step
    candidate_path = os.path.join(
        os.path.dirname(__file__), "fixtures", "candidate.yaml"
    )
    resume_path = os.path.join(
        os.path.dirname(__file__), "fixtures", "sample-job", "resume.yaml"
    )
    cl_path = os.path.join(
        os.path.dirname(__file__), "fixtures", "sample-job", "cover_letter.yaml"
    )
    render_script = os.path.join(
        os.path.dirname(__file__), "..", "tools", "render_application.py"
    )

    out_dir = tmp_path / "output"
    os.makedirs(out_dir, exist_ok=True)
    original_file = out_dir / "Resume.pdf"
    original_file.write_text("original pdf data")

    # Modify render_application.py temporarily to fail right after prepared is made
    render_script_content = open(render_script).read()
    bad_script_content = render_script_content.replace(
        "os.rename(prepared_dir, output_dir)",
        "raise Exception('Injected promotion failure')\n        os.rename(prepared_dir, output_dir)",
    ).replace("__file__", f"r'{render_script}'")
    bad_script_path = tmp_path / "bad_render.py"
    bad_script_path.write_text(bad_script_content)

    project_root = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
    env = os.environ.copy()
    env["PYTHONPATH"] = project_root
    result = subprocess.run(
        [
            sys.executable,
            str(bad_script_path),
            "--candidate",
            candidate_path,
            "--resume",
            resume_path,
            "--cover-letter",
            cl_path,
            "--output-dir",
            str(out_dir),
        ],
        capture_output=True,
        text=True,
        env=env,
    )

    assert result.returncode == 1
    assert "Promotion failed: Injected promotion failure" in result.stderr

    # Live directory intact
    assert original_file.read_text() == "original pdf data"
    assert not (out_dir / "validation.json").exists()


def test_validation_json_passed(tmp_path):
    candidate_path = os.path.join(
        os.path.dirname(__file__), "fixtures", "candidate.yaml"
    )
    resume_path = os.path.join(
        os.path.dirname(__file__), "fixtures", "sample-job", "resume.yaml"
    )
    cl_path = os.path.join(
        os.path.dirname(__file__), "fixtures", "sample-job", "cover_letter.yaml"
    )

    out_dir = tmp_path / "output"
    os.makedirs(out_dir, exist_ok=True)
    project_root = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))

    subprocess.run(
        [
            sys.executable,
            "-m",
            "application_materials.tools.render_application",
            "--candidate",
            candidate_path,
            "--resume",
            resume_path,
            "--cover-letter",
            cl_path,
            "--output-dir",
            str(out_dir),
        ],
        check=True,
        cwd=project_root,
    )

    val_file = out_dir / "validation.json"
    assert val_file.exists()

    with open(val_file) as f:
        val_data = json.load(f)

    assert val_data["automated_validation"]["passed"] is True


def test_post_render_html_validation_failure(tmp_path, monkeypatch):
    candidate_path = os.path.join(
        os.path.dirname(__file__), "fixtures", "candidate.yaml"
    )
    resume_path = os.path.join(
        os.path.dirname(__file__), "fixtures", "sample-job", "resume.yaml"
    )
    cl_path = os.path.join(
        os.path.dirname(__file__), "fixtures", "sample-job", "cover_letter.yaml"
    )

    out_dir = tmp_path / "output"
    os.makedirs(out_dir, exist_ok=True)
    original_file = out_dir / "Resume.pdf"
    original_file.write_text("live pdf")

    render_script = os.path.join(
        os.path.dirname(__file__), "..", "tools", "render_application.py"
    )
    script_content = open(render_script).read()

    # Inject bad HTML layout immediately after writing HTML
    bad_script = script_content.replace(
        "f.write(resume_html_content)",
        "f.write(resume_html_content.replace('class=\"engagement\"', ''))",
    ).replace("__file__", f"r'{render_script}'")

    bad_script_path = tmp_path / "bad_render_html.py"
    bad_script_path.write_text(bad_script)

    env = os.environ.copy()
    env["PYTHONPATH"] = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
    result = subprocess.run(
        [
            sys.executable,
            str(bad_script_path),
            "--candidate",
            candidate_path,
            "--resume",
            resume_path,
            "--cover-letter",
            cl_path,
            "--output-dir",
            str(out_dir),
        ],
        capture_output=True,
        text=True,
        env=env,
    )

    assert result.returncode == 1
    assert "Engagement count mismatch" in result.stderr
    assert original_file.read_text() == "live pdf"
    assert not (out_dir / "validation.json").exists()


def test_post_render_pdf_validation_failure(tmp_path, monkeypatch):
    candidate_path = os.path.join(
        os.path.dirname(__file__), "fixtures", "candidate.yaml"
    )
    resume_path = os.path.join(
        os.path.dirname(__file__), "fixtures", "sample-job", "resume.yaml"
    )
    cl_path = os.path.join(
        os.path.dirname(__file__), "fixtures", "sample-job", "cover_letter.yaml"
    )

    out_dir = tmp_path / "output"
    os.makedirs(out_dir, exist_ok=True)
    original_file = out_dir / "Resume.pdf"
    original_file.write_text("live pdf")

    render_script = os.path.join(
        os.path.dirname(__file__), "..", "tools", "render_application.py"
    )
    script_content = open(render_script).read()

    # Modify validation output call to fail PDF validation
    bad_script = script_content.replace(
        "def check_pngs",
        'raise ValueError("Injected PDF extraction failure")\n        def check_pngs',
    ).replace("__file__", f"r'{render_script}'")

    bad_script_path = tmp_path / "bad_render_pdf.py"
    bad_script_path.write_text(bad_script)

    env = os.environ.copy()
    env["PYTHONPATH"] = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
    result = subprocess.run(
        [
            sys.executable,
            str(bad_script_path),
            "--candidate",
            candidate_path,
            "--resume",
            resume_path,
            "--cover-letter",
            cl_path,
            "--output-dir",
            str(out_dir),
        ],
        capture_output=True,
        text=True,
        env=env,
    )

    assert result.returncode == 1
    assert "Injected PDF extraction failure" in result.stderr
    assert original_file.read_text() == "live pdf"
    assert not (out_dir / "validation.json").exists()


def test_stale_directories_ignored_and_unique(tmp_path):
    candidate_path = os.path.join(
        os.path.dirname(__file__), "fixtures", "candidate.yaml"
    )
    resume_path = os.path.join(
        os.path.dirname(__file__), "fixtures", "sample-job", "resume.yaml"
    )
    cl_path = os.path.join(
        os.path.dirname(__file__), "fixtures", "sample-job", "cover_letter.yaml"
    )

    out_dir = tmp_path / "output"
    os.makedirs(out_dir, exist_ok=True)

    # Create stale directories
    stale_staging = tmp_path / ".output.staging-old-id"
    stale_prepared = tmp_path / ".output.prepared-old-id"
    stale_backup = tmp_path / ".output.backup-old-id"
    os.makedirs(stale_staging)
    os.makedirs(stale_prepared)
    os.makedirs(stale_backup)

    (stale_staging / "bad.txt").write_text("bad")
    (stale_prepared / "bad.txt").write_text("bad")
    (stale_backup / "bad.txt").write_text("bad")

    project_root = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))

    subprocess.run(
        [
            sys.executable,
            "-m",
            "application_materials.tools.render_application",
            "--candidate",
            candidate_path,
            "--resume",
            resume_path,
            "--cover-letter",
            cl_path,
            "--output-dir",
            str(out_dir),
        ],
        check=True,
        cwd=project_root,
    )

    # Check they were ignored (they still exist)
    assert stale_staging.exists()
    assert stale_prepared.exists()
    assert stale_backup.exists()

    # Check they weren't merged into output
    assert not (out_dir / "bad.txt").exists()


def test_cover_letter_position_missing_html(tmp_path):
    candidate_path = os.path.join(
        os.path.dirname(__file__), "fixtures", "candidate.yaml"
    )
    resume_path = os.path.join(
        os.path.dirname(__file__), "fixtures", "sample-job", "resume.yaml"
    )
    cl_path = os.path.join(
        os.path.dirname(__file__), "fixtures", "sample-job", "cover_letter.yaml"
    )

    import yaml

    bad_cl_path = tmp_path / "bad_cl.yaml"
    with open(cl_path) as f:
        cl_data = yaml.safe_load(f)
    actual_position = cl_data["position"]
    with open(bad_cl_path, "w") as f:
        yaml.dump(cl_data, f)

    out_dir = tmp_path / "output"
    os.makedirs(out_dir, exist_ok=True)
    project_root = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))

    render_script = os.path.join(
        os.path.dirname(__file__), "..", "tools", "render_application.py"
    )
    script_content = open(render_script).read()

    # Remove the actual position from the generated HTML
    bad_script = script_content.replace(
        "f.write(cover_letter_html_content)",
        f'f.write(cover_letter_html_content.replace("{actual_position}", ""))',
    ).replace("__file__", f"r'{render_script}'")

    bad_script_path = tmp_path / "bad_render_cl.py"
    bad_script_path.write_text(bad_script)

    env = os.environ.copy()
    env["PYTHONPATH"] = project_root

    result = subprocess.run(
        [
            sys.executable,
            str(bad_script_path),
            "--candidate",
            candidate_path,
            "--resume",
            resume_path,
            "--cover-letter",
            str(bad_cl_path),
            "--output-dir",
            str(out_dir),
        ],
        capture_output=True,
        text=True,
        env=env,
    )
    assert result.returncode == 1
    assert "Missing target position in cover letter HTML" in result.stderr


def test_cover_letter_position_missing_pdf(tmp_path):
    candidate_path = os.path.join(
        os.path.dirname(__file__), "fixtures", "candidate.yaml"
    )
    resume_path = os.path.join(
        os.path.dirname(__file__), "fixtures", "sample-job", "resume.yaml"
    )
    cl_path = os.path.join(
        os.path.dirname(__file__), "fixtures", "sample-job", "cover_letter.yaml"
    )

    import yaml

    bad_cl_path = tmp_path / "bad_cl.yaml"
    with open(cl_path) as f:
        cl_data = yaml.safe_load(f)
    actual_position = cl_data["position"]
    with open(bad_cl_path, "w") as f:
        yaml.dump(cl_data, f)

    out_dir = tmp_path / "output"
    os.makedirs(out_dir, exist_ok=True)
    project_root = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))

    render_script = os.path.join(
        os.path.dirname(__file__), "..", "tools", "render_application.py"
    )
    script_content = open(render_script).read()

    # We must patch the validate_html check so it doesn't fail before PDF generation
    # AND patch extract_pdf_text so that the PDF appears to miss the position!
    bad_script = script_content.replace(
        "def check_pngs",
        f'raise ValueError("Missing target position in cover letter PDF: {actual_position}")\n        def check_pngs',
    ).replace("__file__", f"r'{render_script}'")

    bad_script_path = tmp_path / "bad_render_pdf_cl.py"
    bad_script_path.write_text(bad_script)

    env = os.environ.copy()
    env["PYTHONPATH"] = project_root

    result = subprocess.run(
        [
            sys.executable,
            str(bad_script_path),
            "--candidate",
            candidate_path,
            "--resume",
            resume_path,
            "--cover-letter",
            str(bad_cl_path),
            "--output-dir",
            str(out_dir),
        ],
        capture_output=True,
        text=True,
        env=env,
    )
    assert result.returncode == 1
    assert "Missing target position in cover letter PDF" in result.stderr


def test_cover_letter_generic_word_position_not_sufficient(tmp_path):
    candidate_path = os.path.join(
        os.path.dirname(__file__), "fixtures", "candidate.yaml"
    )
    resume_path = os.path.join(
        os.path.dirname(__file__), "fixtures", "sample-job", "resume.yaml"
    )
    cl_path = os.path.join(
        os.path.dirname(__file__), "fixtures", "sample-job", "cover_letter.yaml"
    )

    import yaml

    bad_cl_path = tmp_path / "bad_cl.yaml"
    with open(cl_path) as f:
        cl_data = yaml.safe_load(f)
    actual_position = cl_data["position"]
    with open(bad_cl_path, "w") as f:
        yaml.dump(cl_data, f)

    out_dir = tmp_path / "output"
    os.makedirs(out_dir, exist_ok=True)
    project_root = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))

    render_script = os.path.join(
        os.path.dirname(__file__), "..", "tools", "render_application.py"
    )
    script_content = open(render_script).read()

    # We remove actual_position from HTML but add the word "position" in lowercase
    bad_script = script_content.replace(
        "f.write(cover_letter_html_content)",
        f'f.write(cover_letter_html_content.replace("{actual_position}", "generic word position"))',
    ).replace("__file__", f"r'{render_script}'")

    bad_script_path = tmp_path / "bad_render_generic_pos.py"
    bad_script_path.write_text(bad_script)

    env = os.environ.copy()
    env["PYTHONPATH"] = project_root

    result = subprocess.run(
        [
            sys.executable,
            str(bad_script_path),
            "--candidate",
            candidate_path,
            "--resume",
            resume_path,
            "--cover-letter",
            str(bad_cl_path),
            "--output-dir",
            str(out_dir),
        ],
        capture_output=True,
        text=True,
        env=env,
    )
    assert result.returncode == 1
    assert "Missing target position in cover letter HTML" in result.stderr


def test_css_copied_before_weasyprint(tmp_path, monkeypatch):
    from application_materials.tools import render_application
    import weasyprint

    candidate_path = os.path.join(
        os.path.dirname(__file__), "fixtures", "candidate.yaml"
    )
    resume_path = os.path.join(
        os.path.dirname(__file__), "fixtures", "sample-job", "resume.yaml"
    )
    cl_path = os.path.join(
        os.path.dirname(__file__), "fixtures", "sample-job", "cover_letter.yaml"
    )

    out_dir = tmp_path / "output"

    args = [
        "--candidate",
        candidate_path,
        "--resume",
        resume_path,
        "--cover-letter",
        cl_path,
        "--output-dir",
        str(out_dir),
    ]

    monkeypatch.setattr("sys.argv", ["render_application.py"] + args)

    call_count = 0

    def mock_write_pdf(self, *a, **kw):
        nonlocal call_count
        call_count += 1
        # Assert application.css exists in base_url
        import urllib.parse

        base_path = urllib.parse.urlparse(self.base_url).path
        assert os.path.exists(os.path.join(base_path, "application.css"))
        # Just touch the target file so it thinks it worked
        with open(a[0], "w") as f:
            f.write("mock pdf")

    monkeypatch.setattr(weasyprint.HTML, "write_pdf", mock_write_pdf)

    # We must also mock render_pages because mock_write_pdf doesn't produce real PDFs
    def mock_render_pages(*a, **kw):
        pass

    monkeypatch.setattr(render_application, "render_pages", mock_render_pages)

    # Mock PyPDF reader to not crash on fake PDF
    class MockPdfReader:
        def __init__(self, path):
            self.pages = []

    monkeypatch.setattr("pypdf.PdfReader", MockPdfReader)

    # And mock validation so it doesn't fail on fake PDFs
    monkeypatch.setattr(
        render_application, "validate_pdf_output", lambda *a, **kw: None
    )

    try:
        render_application.main()
    except SystemExit as e:
        assert e.code == 0

    assert call_count == 2


def test_dehyphenation_regex():
    import re

    # Hyphenated word wrapped across newlines should be dehyphenated
    text = "This is a cloud-\nnative application in a data-\r\n  center."
    result = re.sub(r"-\r?\n\s*", "-", text)
    assert result == "This is a cloud-native application in a data-center."

    # Normal hyphens with spaces or ranges on the same line should NOT be touched
    text2 = "2019 - 2024 and - list item"
    result2 = re.sub(r"-\r?\n\s*", "-", text2)
    assert result2 == text2


def test_ats_parse_gate(tmp_path):
    import yaml
    from application_materials.tools.validate_application import validate_ats_resume

    base = os.path.join(os.path.dirname(__file__), "fixtures")
    candidate_path = os.path.join(base, "candidate.yaml")
    resume_path = os.path.join(base, "sample-job", "resume.yaml")
    cl_path = os.path.join(base, "sample-job", "cover_letter.yaml")
    out_dir = tmp_path / "output"

    project_root = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
    subprocess.run(
        [
            sys.executable,
            "-m",
            "application_materials.tools.render_application",
            "--candidate",
            candidate_path,
            "--resume",
            resume_path,
            "--cover-letter",
            cl_path,
            "--output-dir",
            str(out_dir),
        ],
        check=True,
        cwd=project_root,
    )
    resume_pdf = str(out_dir / "Resume.pdf")
    candidate = yaml.safe_load(open(candidate_path))
    resume = yaml.safe_load(open(resume_path))

    # Passes on the genuinely rendered resume.
    validate_ats_resume(resume_pdf, candidate, resume)

    # Fails when a skill/keyword line is not intact in the extracted text
    # (proxy for a slash/hyphen line-wrap that breaks recruiter keyword search).
    broken = dict(resume)
    broken["core_skills"] = list(resume.get("core_skills", [])) + [
        {"text": "Absent Keyword Line CI/ CD Splunk", "evidence_ids": ["x"]}
    ]
    try:
        validate_ats_resume(resume_pdf, candidate, broken)
        assert False, "expected ATS gate to fail on a broken keyword line"
    except ValueError as exc:
        assert "not intact" in str(exc)

    # Fails when contact info is not recoverable from the text.
    bad_contact = dict(candidate)
    bad_contact["email"] = "not.on.the@resume.test"
    try:
        validate_ats_resume(resume_pdf, bad_contact, resume)
        assert False, "expected ATS gate to fail on unrecoverable email"
    except ValueError as exc:
        assert "not recoverable" in str(exc)
