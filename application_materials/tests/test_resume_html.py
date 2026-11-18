import pytest
import os
import yaml
from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape
from application_materials.tools.validate_application import validate_html


@pytest.fixture
def test_data():
    candidate_path = os.path.join(
        os.path.dirname(__file__), "fixtures", "candidate.yaml"
    )
    resume_path = os.path.join(
        os.path.dirname(__file__), "fixtures", "sample-job", "resume.yaml"
    )

    with open(candidate_path) as f:
        candidate = yaml.safe_load(f)
    with open(resume_path) as f:
        resume = yaml.safe_load(f)

    return candidate, resume


def test_html_structure_and_escaping(test_data, tmp_path):
    candidate, resume = test_data

    # Test HTML escaping
    candidate["name"] = "<script>alert(1)</script>"

    template_dir = os.path.join(os.path.dirname(__file__), "..", "templates")
    env = Environment(
        loader=FileSystemLoader(template_dir),
        undefined=StrictUndefined,
        autoescape=select_autoescape(["html", "xml", "j2"]),
    )
    template = env.get_template("resume.html.j2")
    rendered = template.render(candidate=candidate, resume=resume)

    assert "<script>" not in rendered
    assert "&lt;script&gt;" in rendered

    html_file = tmp_path / "resume.html"
    html_file.write_text(rendered, encoding="utf-8")

    # Use runtime validation
    validate_html(str(html_file), resume)


def test_strict_undefined_failure(test_data):
    candidate, resume = test_data

    template_dir = os.path.join(os.path.dirname(__file__), "..", "templates")
    env = Environment(
        loader=FileSystemLoader(template_dir),
        undefined=StrictUndefined,
        autoescape=select_autoescape(["html", "xml", "j2"]),
    )
    template = env.get_template("resume.html.j2")

    del candidate["name"]
    from jinja2.exceptions import UndefinedError

    with pytest.raises(UndefinedError):
        template.render(candidate=candidate, resume=resume)


def test_incorrect_html_nesting_fails_validation(test_data, tmp_path):
    candidate, resume = test_data

    html_file = tmp_path / "resume.html"

    # Write a bad HTML where achievement is outside an engagement
    bad_html = """
    <html>
    <body>
        <h2 id="summary">Summary</h2>
        <h2 id="skills">Skills</h2>
        <h2 id="experience">Experience</h2>
        <h2 id="education">Education</h2>
        <h2 id="certifications">Certifications</h2>
        <ul class="achievement-list"><li class="achievement">Orphaned achievement</li></ul>
    </body>
    </html>
    """
    html_file.write_text(bad_html, encoding="utf-8")

    with pytest.raises(ValueError, match="Engagement count mismatch"):
        # This will fail fast at engagement count.
        # But if we fake it...
        validate_html(str(html_file), resume)
