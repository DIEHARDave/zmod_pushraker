#!/usr/bin/env python3
"""Refill python/ with the pushraker package.

Zmod's Moonraker environment already has pushraker's requirements
(Apprise, requests, Pillow, Jinja2), so only pushraker itself is shipped;
moonraker/pushraker.py puts python/ on sys.path.

    python tools/vendor.py              # latest pushraker from PyPI
    python tools/vendor.py 0.3.6        # a given version

Runs on any machine with pip (Windows, Linux, macOS): pushraker is a
py3-none-any wheel.
"""

import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
TARGET = os.path.join(REPO, "python")

# Fixes to pushraker that upstream doesn't have yet: (file, old, new).
# A fix that no longer applies (upstream changed the line) is reported.
PATCHES = [
    # The settings page reads the filament change checkboxes, which it
    # leaves out on printers other than the Snapmaker U1: Send Test and
    # Save & Apply then fail with "Cannot read properties of null".
    # Upstream PR: noon92/pushraker, branch fix/hidden-filament-change-row.
    ("pushraker/web/index.html",
     "filament_change_events: ['loaded', 'unloaded'].filter(e => "
     "el('nt-fc-' + e).checked).join(','),",
     "filament_change_events: el('nt-fc-loaded') ? ['loaded', 'unloaded']"
     ".filter(e => el('nt-fc-' + e).checked).join(',') : "
     "[].concat(state.filament_change_events || []).join(','),"),
]


def pip(*args):
    cmd = [sys.executable, "-m", "pip", "--disable-pip-version-check",
           "-q", *args]
    print("+", " ".join(cmd[3:]))
    subprocess.run(cmd, check=True)


def main() -> int:
    version = sys.argv[1] if len(sys.argv) > 1 else None
    tmp = tempfile.mkdtemp(prefix="pushraker-vendor-")
    out = os.path.join(tmp, "python")
    try:
        pkg = f"pushraker=={version}" if version else "pushraker"
        pip("install", "--target", out, "--no-deps", "--only-binary=:all:",
            "--platform", "any", "--implementation", "py",
            "--python-version", "3.12", pkg)
        # Leftovers that don't belong on the printer: caches, scripts
        for root, dirs, files in os.walk(out, topdown=False):
            for f in files:
                if f.endswith((".so", ".pyd", ".pyc")):
                    os.remove(os.path.join(root, f))
            for d in dirs:
                if d == "__pycache__":
                    shutil.rmtree(os.path.join(root, d))
        shutil.rmtree(os.path.join(out, "bin"), ignore_errors=True)

        failed = []
        for rel, old, new in PATCHES:
            path = os.path.join(out, rel)
            with open(path, encoding="utf-8") as f:
                text = f.read()
            if new in text:
                continue
            if old not in text:
                failed.append(rel)
                continue
            with open(path, "w", encoding="utf-8", newline="") as f:
                f.write(text.replace(old, new, 1))
            print(f"patched {rel}")

        shutil.rmtree(TARGET, ignore_errors=True)
        shutil.copytree(out, TARGET)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    for name in sorted(os.listdir(TARGET)):
        if name.endswith(".dist-info"):
            print("  ", name[:-len(".dist-info")])
    if failed:
        print("WARNING: these fixes no longer apply (check whether upstream "
              "fixed them, then drop them from PATCHES):", *failed)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
