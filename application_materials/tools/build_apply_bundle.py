from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from applywright.application_packages.apply_bundle import (
    ApplyBundleError,
    build_apply_bundle,
)

REPO_ROOT = Path(__file__).resolve().parents[2]


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Write the apply bundle for one promoted application package."
    )
    parser.add_argument("slug")
    args = parser.parse_args()

    try:
        bundle = build_apply_bundle(REPO_ROOT, args.slug)
    except ApplyBundleError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc

    target_dir = REPO_ROOT / "application_materials" / "apply_bundles"
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / f"{bundle['slug']}.json"
    target.write_text(json.dumps(bundle, indent=2) + "\n", encoding="utf-8")
    print(target)


if __name__ == "__main__":
    main()
