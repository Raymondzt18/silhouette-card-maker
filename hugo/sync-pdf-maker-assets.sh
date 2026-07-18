#!/usr/bin/env bash
# Copies the core PDF-generation modules from the repo root into the static
# in-browser tool (hugo/static/pdf-maker/pylib) so the website always ships
# the exact same layout/rendering logic as the create_pdf.py CLI.
#
# Run this after changing utilities.py, page_manager.py, enums.py,
# size_convert.py, or assets/layouts.json, and before building the Hugo
# site. It also runs automatically in the GitHub Pages deploy workflow.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEST_DIR="$ROOT_DIR/hugo/static/pdf-maker/pylib"

mkdir -p "$DEST_DIR/assets"

cp "$ROOT_DIR/utilities.py" "$DEST_DIR/utilities.py"
cp "$ROOT_DIR/page_manager.py" "$DEST_DIR/page_manager.py"
cp "$ROOT_DIR/enums.py" "$DEST_DIR/enums.py"
cp "$ROOT_DIR/size_convert.py" "$DEST_DIR/size_convert.py"
cp "$ROOT_DIR/assets/layouts.json" "$DEST_DIR/assets/layouts.json"
cp "$ROOT_DIR/assets/arial.ttf" "$DEST_DIR/assets/arial.ttf"

echo "Synced core PDF-generation modules into $DEST_DIR"
