#!/usr/bin/env python3
"""
listDuplicatesFromList-v0-1.py - List duplicate filenames from duplicates.txt (v0-1)

DESCRIPTION
    Version: v0-1

    This script is a READ-ONLY duplicate reporter. It does NOT move or modify
    any files.

    It expects a file named 'duplicates.txt' in the SAME directory as this
    script. Each non-empty line in duplicates.txt must be a FULL ABSOLUTE
    PATH to an image file (as produced by makeDuplicatesTXT-v0-1.py).

    You pass a BASE SEARCH ROOT as arg1 (e.g.
        /media/Entertainment/Photos/PictureAlbums
    ) and the script will walk that tree ONCE, looking for files whose
    BASENAME matches any of the basenames from duplicates.txt.

    It then groups by BASENAME and reports ONLY those basenames that were
    found in 2 or more locations under the search root.

    Example output:

        [GROUP] IMG_1234.jpg (count: 3)
            /path/A/IMG_1234.jpg
            /path/B/IMG_1234.jpg
            /path/C/IMG_1234.jpg

    RULES / BEHAVIOR
        * Any directory named exactly 'slideshow_exclude' is skipped entirely
          while walking the search root.
        * No files are moved, deleted, or changed in any way.
        * A timestamped log file is created in the script directory:
              listDuplicatesFromList-v0-1_YYYYMMDD_HHMMSS.log
          All screen output is also written to this log.

USAGE
    listDuplicatesFromList-v0-1.py <search_root>

EXAMPLE
    # duplicates.txt already created by makeDuplicatesTXT-v0-1.py
    listDuplicatesFromList-v0-1.py /media/Entertainment/Photos/PictureAlbums

OPTIONS
    <search_root>   REQUIRED. Root directory tree to search for duplicates.
    --version       Show version and exit.

EXIT CODES
    0  Success
    1  Missing search_root / usage error
    2  search_root not found or not a directory
    3  duplicates.txt missing or unreadable
"""

import argparse
import os
import sys
from collections import defaultdict
from datetime import datetime
from typing import Dict, List, TextIO, Tuple

VERSION = "v0-1"


def script_dir() -> str:
    """Return absolute directory where this script resides."""
    return os.path.dirname(os.path.abspath(__file__))


# ---------- Logging helpers ----------

_log_file: TextIO | None = None


def init_log() -> None:
    """Open a timestamped log file in the script directory."""
    global _log_file
    if _log_file is not None:
        return

    base_dir = script_dir()
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_name = f"listDuplicatesFromList-v0-1_{ts}.log"
    log_path = os.path.join(base_dir, log_name)

    try:
        _log_file = open(log_path, "w", encoding="utf-8")
        _log_file.write(f"# listDuplicatesFromList-v0-1 log\n# Started: {datetime.now()}\n\n")
        _log_file.flush()
        print(f"Logging to: {log_path}")
    except OSError as e:
        print(f"WARNING: Could not open log file '{log_path}': {e}", file=sys.stderr)
        _log_file = None


def log_out(msg: str = "") -> None:
    """Log a message to stdout and to the log file."""
    print(msg)
    if _log_file is not None:
        _log_file.write(msg + "\n")
        _log_file.flush()


def log_err(msg: str) -> None:
    """Log a message to stderr and to the log file."""
    print(msg, file=sys.stderr)
    if _log_file is not None:
        _log_file.write(msg + "\n")
        _log_file.flush()


def close_log() -> None:
    """Close the log file if open."""
    global _log_file
    if _log_file is not None:
        try:
            _log_file.close()
        except OSError:
            pass
        _log_file = None


# ---------- Core logic ----------


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="List duplicate basenames (2+ locations) based on duplicates.txt (read-only).",
        formatter_class=argparse.RawTextHelpFormatter,
    )
    parser.add_argument(
        "search_root",
        nargs="?",
        help="Base directory tree to search (e.g. /media/Entertainment/Photos/PictureAlbums).",
    )
    parser.add_argument(
        "--version",
        action="store_true",
        help="Show version and exit.",
    )
    return parser.parse_args()


def load_basenames(dups_path: str) -> Tuple[List[str], Dict[str, int]]:
    """
    Load full paths from duplicates.txt and return:

        originals_list: list of full paths (in file order)
        basename_counts: {basename: count_in_duplicates_txt}

    NOTE: duplicates.txt may contain multiple entries with the same basename.
    """
    if not os.path.isfile(dups_path):
        raise FileNotFoundError(f"duplicates.txt not found: {dups_path}")

    originals_list: List[str] = []
    basename_counts: Dict[str, int] = defaultdict(int)

    with open(dups_path, "r", encoding="utf-8") as f:
        for lineno, line in enumerate(f, start=1):
            path = line.strip()
            if not path:
                continue

            if not os.path.isabs(path):
                log_err(
                    f"Warning: line {lineno} in {dups_path} is not an absolute path; skipping: {path}"
                )
                continue

            originals_list.append(path)
            base = os.path.basename(path)
            basename_counts[base] += 1

    if not originals_list:
        log_err(f"Warning: no valid entries found in {dups_path}")

    return originals_list, basename_counts


def walk_and_collect(search_root: str, basenames: List[str]) -> Dict[str, List[str]]:
    """
    Walk search_root once, collecting full paths for files whose basename
    is in 'basenames'.

    Returns:
        {basename: [full_path1, full_path2, ...]}

    Directories named 'slideshow_exclude' are skipped entirely.
    """
    targets_set = set(basenames)
    matches: Dict[str, List[str]] = defaultdict(list)

    for dirpath, dirnames, filenames in os.walk(search_root):
        # Skip any directory named exactly 'slideshow_exclude'
        dirnames[:] = [d for d in dirnames if d != "slideshow_exclude"]

        for fname in filenames:
            if fname in targets_set:
                full_path = os.path.join(dirpath, fname)
                matches[fname].append(full_path)
                # Optional progress line
                log_out(f"FOUND: {fname} -> {full_path}")

    return matches


def main() -> int:
    init_log()
    try:
        args = parse_args()

        if args.version:
            log_out(f"listDuplicatesFromList-v0-1.py version {VERSION}")
            return 0

        if not args.search_root:
            log_err("Error: missing <search_root>.\n")
            log_out(__doc__)
            return 1

        search_root = os.path.abspath(args.search_root)
        if not os.path.isdir(search_root):
            log_err(f"Error: search_root not found or not a directory: {search_root}")
            return 2

        dups_path = os.path.join(script_dir(), "duplicates.txt")

        try:
            originals_list, basename_counts = load_basenames(dups_path)
        except FileNotFoundError as e:
            log_err(str(e))
            return 3
        except OSError as e:
            log_err(f"Error reading {dups_path}: {e}")
            return 3

        if not originals_list:
            return 0

        # Walk once, gathering actual locations under search_root
        matches_by_name = walk_and_collect(search_root, list(basename_counts.keys()))

        # Filter to basenames that have 2+ physical locations
        duplicate_groups = {name: paths for name, paths in matches_by_name.items() if len(paths) >= 2}

        log_out()
        log_out(f"Search root: {search_root}")
        log_out(f"Total entries in duplicates.txt: {len(originals_list)}")
        log_out(f"Unique basenames in duplicates.txt: {len(basename_counts)}")
        log_out(f"Basenames with 2+ locations under search_root: {len(duplicate_groups)}")
        log_out()

        total_files_in_groups = sum(len(v) for v in duplicate_groups.values())

        # Print each group
        for name, paths in sorted(duplicate_groups.items()):
            log_out(f"[GROUP] {name} (count: {len(paths)})")
            for p in sorted(paths):
                log_out(f"    {p}")
            log_out()

        # Summary
        log_out("=== SUMMARY ===")
        log_out(f"Basenames with duplicates (2+ locations): {len(duplicate_groups)}")
        log_out(f"Total files participating in duplicate groups: {total_files_in_groups}")

        return 0

    finally:
        close_log()


if __name__ == "__main__":
    raise SystemExit(main())

