#!/usr/bin/env python3
"""
findDuplicatesFromList-v1-4.py - LIST-ONLY tool using Linux `find`
Version v1-4

HARD RULES (non-negotiable):
    • NO moves, NO renames, NO deletes, NO mkdirs.
    • Absolutely NO changes to the filesystem.
    • ALWAYS use Linux `find` to locate matching filenames under <search_root>.
    • ONLY list duplicates, never modify.

BEHAVIOR:
    • Reads duplicates.txt in the same directory as this script.
    • Groups entries by basename.
    • Only processes basenames that appear >1 time in duplicates.txt.
    • For each such basename, runs Linux `find` to locate ALL matching files.
    • Output format:

          IMG_1234.jpg
              /path/from/duplicates.txt/IMG_1234.jpg
              /path/found/elsewhere/IMG_1234.jpg
              /another/found/path/IMG_1234.jpg

    • Log + terminal output both show the same list-only report.
"""

import argparse
import os
import subprocess
import sys
from collections import defaultdict
from datetime import datetime
from typing import Dict, List, TextIO

VERSION = "v1-4"

# ----------------- Logging -----------------

_log_file: TextIO | None = None

def script_dir() -> str:
    return os.path.dirname(os.path.abspath(__file__))

def init_log() -> None:
    global _log_file
    if _log_file:
        return

    base = script_dir()
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    fname = f"findDuplicatesFromList-v1-4_{ts}.log"
    path = os.path.join(base, fname)

    try:
        _log_file = open(path, "w", encoding="utf-8")
        print(f"Logging to: {path}")
        _log_file.write(f"# LIST-ONLY v1-4 run started {datetime.now()}\n\n")
    except OSError:
        print("WARNING: Could not open log for writing.")
        _log_file = None

def log(msg: str = "") -> None:
    print(msg)
    if _log_file:
        _log_file.write(msg + "\n")

def close_log() -> None:
    global _log_file
    if _log_file:
        try:
            _log_file.close()
        except:
            pass
        _log_file = None

# ----------------- Core Logic -----------------

def parse_args():
    p = argparse.ArgumentParser(
        description="LIST-ONLY duplicate basename scanner using Linux find."
    )
    p.add_argument(
        "search_root",
        help="Root of the Photos tree to search (read-only)."
    )
    p.add_argument("--version", action="store_true")
    return p.parse_args()

def load_originals(dups_path: str) -> Dict[str, List[str]]:
    out = defaultdict(list)

    with open(dups_path, "r", encoding="utf-8") as f:
        for lineno, line in enumerate(f, 1):
            p = line.strip()
            if not p:
                continue
            if not os.path.isabs(p):
                log(f"Skipping non-absolute path on line {lineno}: {p}")
                continue
            out[os.path.basename(p)].append(p)

    return out

def run_find(root: str, basename: str) -> List[str]:
    """ALWAYS uses Linux find."""
    cmd = [
        "find", root,
        "-type", "d", "-name", "slideshow_exclude", "-prune",
        "-o", "-type", "f", "-name", basename, "-print"
    ]

    try:
        r = subprocess.run(cmd, capture_output=True, text=True, check=False)
    except Exception as e:
        log(f"[ERROR running find] {e}")
        return []

    paths = []
    for line in r.stdout.splitlines():
        p = line.strip()
        if p:
            paths.append(p)
    return paths

def main():
    init_log()

    try:
        args = parse_args()

        if args.version:
            log(f"Version: {VERSION}")
            return 0

        search_root = os.path.abspath(args.search_root)
        if not os.path.isdir(search_root):
            log(f"ERROR: search_root is not a directory: {search_root}")
            return 2

        dups_path = os.path.join(script_dir(), "duplicates.txt")
        if not os.path.isfile(dups_path):
            log(f"ERROR: duplicates.txt not found at: {dups_path}")
            return 3

        originals = load_originals(dups_path)

        # Only basenames with >1 entry in duplicates.txt
        dup_basenames = sorted([bn for bn, lst in originals.items() if len(lst) > 1])

        log(f"Unique basenames in duplicates.txt: {len(originals)}")
        log(f"Basenames with >1 occurrence: {len(dup_basenames)}\n")

        # MAIN LOOP — ALWAYS list-only, NEVER move.
        for idx, bn in enumerate(dup_basenames, 1):
            log(f"[{idx}/{len(dup_basenames)}] {bn}")

            found = run_find(search_root, bn)

            # Group output
            log(bn)
            for p in originals[bn]:
                log(f"    {p}")

            for p in found:
                if p not in originals[bn]:
                    log(f"    {p}")

            log("")  # blank line between groups

        log("=== DONE — LIST-ONLY, NO FILES WERE MODIFIED ===")

        return 0

    finally:
        close_log()

if __name__ == "__main__":
    raise SystemExit(main())

