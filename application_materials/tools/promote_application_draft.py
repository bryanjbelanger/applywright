from __future__ import annotations

import argparse
import sys
from pathlib import Path

from application_materials.tools.check_repository import check_package
from applywright.application_packages import Draft, DraftError


def promote_application_draft(
    slug: str,
    *,
    human_approved: bool,
    replace_existing: bool = False,
    repo_root: Path | str | None = None,
) -> Path:
    draft = Draft.open(slug, repo_root)
    return draft.promote(
        human_approved=human_approved,
        replace_existing=replace_existing,
        verify_package=lambda package: check_package(
            package, draft.application_root, draft.root
        ),
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Promote a rendered and visually reviewed application draft."
    )
    parser.add_argument("--slug", required=True)
    parser.add_argument("--human-approved", action="store_true")
    parser.add_argument("--replace-existing", action="store_true")
    args = parser.parse_args()

    try:
        destination = promote_application_draft(
            args.slug,
            human_approved=args.human_approved,
            replace_existing=args.replace_existing,
        )
    except DraftError as exc:
        print(f"Draft promotion failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc

    print(f"Application package promoted successfully: {destination}")
    print("No job database or lifecycle state was modified.")


if __name__ == "__main__":
    main()
