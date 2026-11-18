from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any, Callable

from applywright.application_packages import Draft, DraftError


def _default_renderer() -> Callable[..., None]:
    # Imported here because the renderer needs WeasyPrint, which tests do not load.
    from application_materials.tools.render_application import render_application

    return render_application


def render_application_draft(
    slug: str,
    *,
    repo_root: Path | str | None = None,
    renderer: Callable[..., None] | None = None,
) -> dict[str, Any]:
    """Render a draft. `renderer` is the seam: it takes the same arguments as
    `render_application` and raises `RenderError` on failure."""
    from application_materials.tools.render_application import (
        RenderError,
        RenderInputError,
    )

    draft = Draft.open(slug, repo_root)
    render = renderer or _default_renderer()

    try:
        render(
            candidate_path=draft.candidate_path,
            resume_path=draft.resume_path,
            cover_letter_path=draft.cover_letter_path,
            output_dir=draft.output_dir,
            schema_dir=draft.application_root / "schemas",
        )
    except RenderInputError as exc:
        raise DraftError(f"Draft input validation failed: {exc.detail}") from exc
    except RenderError as exc:
        raise DraftError(f"Shared application renderer failed: {exc}") from exc

    record = draft.record_render()
    return {
        "job_slug": draft.slug,
        "draft_path": str(draft.path),
        "output_path": str(draft.output_dir),
        "actual_png_paths": [str(path) for path in record.actual_png_paths],
        "reviewed_pages_to_record": record.reviewed_pages_to_record,
        "visual_review_status": "required",
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Render a validated application draft with the shared renderer."
    )
    parser.add_argument("--slug", required=True)
    args = parser.parse_args()

    try:
        result = render_application_draft(args.slug)
    except DraftError as exc:
        print(f"Draft rendering failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc

    print("Application draft rendered successfully.")
    print("Open every PNG listed below before recording visual review:")
    for path in result["actual_png_paths"]:
        print(f"  {path}")
    print("Record these final repository-relative paths in output/validation.json:")
    for path in result["reviewed_pages_to_record"]:
        print(f"  {path}")
    print("Do not promote the package until visual_review.status is passed.")


if __name__ == "__main__":
    main()
