#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$repo_root"

echo "Installing dependencies..."
poetry install --with document-rendering,dev

echo "Running application-material and Applywright tests..."
poetry run pytest

echo "Checking repository policies..."
poetry run python -m application_materials.tools.check_repository

echo "Checking that local application drafts are not tracked..."
tracked_work="$(git ls-files -- application_materials/work)"
if [[ -n "$tracked_work" ]]; then
  echo "Local application drafts must not be tracked:"
  printf '%s\n' "$tracked_work"
  exit 1
fi

echo "Checking whitespace errors..."
git diff --check

status="$(git status --short)"
if [[ -n "$status" ]]; then
  echo "Local validation passed, but the working tree is not clean:"
  printf '%s\n' "$status"
  exit 1
fi

echo "Local application-package validation passed and the working tree is clean."
