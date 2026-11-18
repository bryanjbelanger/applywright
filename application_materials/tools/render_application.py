import argparse
import os
import yaml
import json
import shutil
import sys
import glob
import uuid
from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape
from application_materials.tools.validate_application import (
    validate_input,
    validate_html,
    validate_cover_letter_html,
    validate_pdf_output,
)
from application_materials.tools.render_pdf_pages import render_pages


class RenderError(Exception):
    """The renderer failed. The message says which stage failed and why."""


class RenderInputError(RenderError):
    """The input files failed to load or failed validation. Nothing was written."""

    def __init__(self, stage: str, detail: object):
        super().__init__(f"{stage}: {detail}")
        self.detail = str(detail)


def render_application(
    candidate_path, resume_path, cover_letter_path, output_dir, schema_dir=None
):
    """Validate the inputs and render the package files into `output_dir`.

    The output directory is replaced only after every file and check has passed.
    Raises `RenderInputError` for a bad input and `RenderError` for any other
    failure.
    """
    # Imported here so that importing this module does not load WeasyPrint.
    from weasyprint import HTML

    # a. Load YAML
    try:
        with open(candidate_path, "r") as f:
            candidate_data = yaml.safe_load(f)
        with open(resume_path, "r") as f:
            resume_data = yaml.safe_load(f)
        with open(cover_letter_path, "r") as f:
            cover_letter_data = yaml.safe_load(f)
    except Exception as e:
        raise RenderInputError("Failed to load YAML", e) from e

    if schema_dir is None:
        schema_dir = os.path.join(os.path.dirname(__file__), "..", "schemas")

    # b. Validate schemas
    # c. Validate chronology
    # d. Validate evidence
    try:
        validate_input(candidate_data, resume_data, cover_letter_data, schema_dir)
    except Exception as e:
        raise RenderInputError("Input validation failed", e) from e

    # e. Create staging directory
    run_id = uuid.uuid4().hex
    base_name = os.path.basename(output_dir)
    staging_dir = os.path.join(
        os.path.dirname(output_dir),
        f".{base_name}.staging-{run_id}",
    )
    os.makedirs(staging_dir, exist_ok=True)

    try:
        # Setup Jinja2
        template_dir = os.path.join(os.path.dirname(__file__), "..", "templates")
        env = Environment(
            loader=FileSystemLoader(template_dir),
            undefined=StrictUndefined,
            autoescape=select_autoescape(["html", "xml", "j2"]),
        )

        # f. Render staged HTML
        resume_html_content = env.get_template("resume.html.j2").render(
            candidate=candidate_data, resume=resume_data
        )
        cover_letter_html_content = env.get_template("cover_letter.html.j2").render(
            candidate=candidate_data, cover_letter=cover_letter_data
        )

        resume_html_path = os.path.join(staging_dir, "Resume.html")
        cover_letter_html_path = os.path.join(staging_dir, "CoverLetter.html")

        with open(resume_html_path, "w", encoding="utf-8") as f:
            f.write(resume_html_content)
        with open(cover_letter_html_path, "w", encoding="utf-8") as f:
            f.write(cover_letter_html_content)

        # Copy CSS
        styles_dir = os.path.join(os.path.dirname(__file__), "..", "styles")
        css_source = os.path.join(styles_dir, "application.css")
        css_dest = os.path.join(staging_dir, "application.css")
        shutil.copy2(css_source, css_dest)

        # g. Validate staged HTML structure and order BEFORE generating PDFs
        validate_html(resume_html_path, resume_data)
        validate_cover_letter_html(
            cover_letter_html_path, candidate_data, cover_letter_data
        )

        # h. Render staged PDFs
        resume_pdf_path = os.path.join(staging_dir, "Resume.pdf")
        cover_letter_pdf_path = os.path.join(staging_dir, "CoverLetter.pdf")

        HTML(filename=resume_html_path, base_url=staging_dir).write_pdf(resume_pdf_path)
        HTML(filename=cover_letter_html_path, base_url=staging_dir).write_pdf(
            cover_letter_pdf_path
        )

        # j. Render staged PNGs
        render_pages(resume_pdf_path, staging_dir, "Resume")
        render_pages(cover_letter_pdf_path, staging_dir, "CoverLetter")

        # i. Validate PDF extraction
        # k. Validate PNG counts and required files
        validate_pdf_output(
            candidate_data,
            resume_data,
            cover_letter_data,
            resume_pdf_path,
            cover_letter_pdf_path,
        )

        def check_pngs(pdf_path, prefix):
            from pypdf import PdfReader

            reader = PdfReader(pdf_path)
            num_pages = len(reader.pages)
            for i in range(1, num_pages + 1):
                png_path = os.path.join(staging_dir, f"{prefix}-page-{i}.png")
                if not os.path.exists(png_path):
                    raise ValueError(f"Missing PNG file: {png_path}")

            pngs = glob.glob(os.path.join(staging_dir, f"{prefix}-page-*.png"))
            if len(pngs) != num_pages:
                raise ValueError(
                    f"PNG count mismatch for {prefix}: expected {num_pages}, found {len(pngs)}"
                )

        check_pngs(resume_pdf_path, "Resume")
        check_pngs(cover_letter_pdf_path, "CoverLetter")

        # l. Write staged validation.json
        validation_result = {
            "automated_validation": {"passed": True, "checks": {"all": "passed"}},
            "visual_review": {
                "status": "required",
                "reviewed_pages": [],
                "findings": [],
            },
        }
        with open(os.path.join(staging_dir, "validation.json"), "w") as f:
            json.dump(validation_result, f, indent=2)

    except Exception as e:
        shutil.rmtree(staging_dir, ignore_errors=True)
        raise RenderError(f"Rendering or output validation failed: {e}") from e

    # m. Promote staged artifacts
    prepared_dir = os.path.join(
        os.path.dirname(output_dir),
        f".{base_name}.prepared-{run_id}",
    )
    backup_dir = os.path.join(
        os.path.dirname(output_dir), f".{base_name}.backup-{run_id}"
    )

    try:
        if os.path.exists(output_dir):
            shutil.copytree(output_dir, prepared_dir, dirs_exist_ok=True)
        else:
            os.makedirs(prepared_dir, exist_ok=True)

        known_files = [
            "Resume.html",
            "Resume.pdf",
            "CoverLetter.html",
            "CoverLetter.pdf",
            "application.css",
            "validation.json",
        ]
        for f in known_files:
            p = os.path.join(prepared_dir, f)
            if os.path.exists(p):
                os.remove(p)

        for p in glob.glob(os.path.join(prepared_dir, "Resume-page-*.png")) + glob.glob(
            os.path.join(prepared_dir, "CoverLetter-page-*.png")
        ):
            os.remove(p)

        shutil.copytree(staging_dir, prepared_dir, dirs_exist_ok=True)

        if os.path.exists(output_dir):
            os.rename(output_dir, backup_dir)
        os.rename(prepared_dir, output_dir)

        if os.path.exists(backup_dir):
            shutil.rmtree(backup_dir)
        shutil.rmtree(staging_dir)

    except Exception as e:
        if os.path.exists(backup_dir):
            if os.path.exists(output_dir):
                shutil.rmtree(output_dir)
            os.rename(backup_dir, output_dir)
        if os.path.exists(prepared_dir):
            shutil.rmtree(prepared_dir)
        if os.path.exists(staging_dir):
            shutil.rmtree(staging_dir)
        raise RenderError(f"Promotion failed: {e}") from e


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidate", required=True)
    parser.add_argument("--resume", required=True)
    parser.add_argument("--cover-letter", required=True)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()

    try:
        render_application(
            args.candidate, args.resume, args.cover_letter, args.output_dir
        )
    except RenderError as e:
        print(e, file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
