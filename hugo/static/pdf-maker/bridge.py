"""
Glue code that runs inside Pyodide (in the browser) and drives the exact
same `generate_pdf()` used by the `create_pdf.py` CLI in this repository.

This file is fetched and executed by app.js. It intentionally does not
import anything from app.js/JS beyond what Pyodide implicitly provides
(the `js` module), so it can be reasoned about like normal Python.
"""

import json
import os
import shutil
import sys
from pathlib import Path

WORKDIR = "/home/pyodide"
GAME_DIR = os.path.join(WORKDIR, "game")
FRONT_DIR = os.path.join(GAME_DIR, "front")
BACK_DIR = os.path.join(GAME_DIR, "back")
DS_DIR = os.path.join(GAME_DIR, "double_sided")
OUTPUT_DIR = os.path.join(GAME_DIR, "output")
DATA_DIR = os.path.join(WORKDIR, "data")

os.chdir(WORKDIR)
if WORKDIR not in sys.path:
    sys.path.insert(0, WORKDIR)

import utilities  # noqa: E402


def ensure_dirs():
    for d in (FRONT_DIR, BACK_DIR, DS_DIR, OUTPUT_DIR, DATA_DIR):
        os.makedirs(d, exist_ok=True)


def _clear_dir(path):
    if os.path.isdir(path):
        shutil.rmtree(path)
    os.makedirs(path, exist_ok=True)


def reset_upload_dirs():
    """Clear any images left over from a previous run in this browser tab."""
    _clear_dir(FRONT_DIR)
    _clear_dir(BACK_DIR)
    _clear_dir(DS_DIR)


def reset_output_dir():
    _clear_dir(OUTPUT_DIR)


# ---------------------------------------------------------------------------
# Progress logging: generate_pdf() reports progress via print(). Forward it
# to a JS callback so the page can show a live log instead of a black hole.
# ---------------------------------------------------------------------------

_log_callback = None


def set_log_callback(callback):
    global _log_callback
    _log_callback = callback


def _bridge_print(*args, **kwargs):
    message = " ".join(str(a) for a in args)
    if _log_callback is not None:
        try:
            _log_callback(message)
        except Exception:
            pass


import builtins  # noqa: E402

builtins.print = _bridge_print


# ---------------------------------------------------------------------------
# Main entry point called from JS with a JSON string of form parameters.
# ---------------------------------------------------------------------------

def generate(params_json):
    params = json.loads(params_json)

    def opt(key):
        value = params.get(key)
        if value is None or value == "":
            return None
        return value

    try:
        reset_output_dir()

        output_images = bool(params.get("output_images", False))
        output_path = OUTPUT_DIR if output_images else os.path.join(OUTPUT_DIR, "game.pdf")

        skip_raw = params.get("skip", [])
        skip_indices = [int(i) for i in skip_raw]

        utilities.generate_pdf(
            front_dir_path=FRONT_DIR,
            back_dir_path=BACK_DIR,
            ds_dir_path=DS_DIR,
            output_path=output_path,
            output_images=output_images,
            card_size=params.get("card_size", "standard"),
            paper_size=params.get("paper_size", "letter"),
            registration=params.get("registration", "3"),
            only_fronts=bool(params.get("only_fronts", False)),
            fit=params.get("fit", "stretch"),
            fit_backs=opt("fit_backs"),
            crop_string=opt("crop"),
            crop_backs_string=opt("crop_backs"),
            extend_edges=opt("extend_edges"),
            extend_edges_backs=opt("extend_edges_backs"),
            extend_corners=opt("extend_corners"),
            extend_corners_backs=opt("extend_corners_backs"),
            extend_bleed=opt("extend_bleed"),
            extend_bleed_backs=opt("extend_bleed_backs"),
            ppi=int(params.get("ppi") or 300),
            quality=int(params.get("quality") or 100),
            skip_indices=skip_indices,
            load_offset=bool(params.get("load_offset", False)),
            label=opt("label"),
            show_outline=bool(params.get("show_outline", False)),
            specialty=opt("specialty"),
            borderless=bool(params.get("borderless", False)),
            registration_orientation_override=opt("registration_orientation"),
        )

        if output_images:
            files = sorted(
                f for f in os.listdir(OUTPUT_DIR)
                if os.path.isfile(os.path.join(OUTPUT_DIR, f))
            )
            if not files:
                return json.dumps({"ok": False, "error": "No pages were generated. Check your uploaded images and options."})
            return json.dumps({"ok": True, "output_kind": "images", "output_dir": OUTPUT_DIR, "files": files})

        if not os.path.isfile(output_path):
            return json.dumps({"ok": False, "error": "No pages were generated. Check your uploaded images and options."})
        return json.dumps({"ok": True, "output_kind": "pdf", "output_path": output_path})

    except Exception as e:  # noqa: BLE001 - surfaced verbatim to the user
        return json.dumps({"ok": False, "error": str(e)})


# ---------------------------------------------------------------------------
# Print-alignment calibration offset (mirrors offset_pdf.py's --save/--load).
# The saved offset is persisted by the JS side (localStorage) since Pyodide's
# in-memory filesystem does not survive a page reload.
# ---------------------------------------------------------------------------

def save_offset_web(x_offset, y_offset, angle_offset):
    os.makedirs(DATA_DIR, exist_ok=True)
    utilities.save_offset(int(x_offset), int(y_offset), float(angle_offset))
    with open(os.path.join(DATA_DIR, "offset_data.json"), "r") as f:
        return f.read()


def hydrate_offset_web(json_str):
    """Write a previously-saved offset (from localStorage) into the FS so
    load_offset=True picks it up, matching offset_pdf.py's saved-offset file."""
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(os.path.join(DATA_DIR, "offset_data.json"), "w") as f:
        f.write(json_str)


ensure_dirs()
