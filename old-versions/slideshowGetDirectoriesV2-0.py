#!/usr/bin/env python3
"""
slideshowGetDirectories.py

Scans the SPECIFIED ROOT DIRECTORY and all subdirectories.
Only adds folders that contain image files.
Skips any folder named: slideshow_exclude

USAGE:
  ./slideshowGetDirectories.py /path/to/root
  or
  python3 slideshowGetDirectories.py /path/to/root

NOTE:
  ROOT DIRECTORY is REQUIRED.
  If missing: Shows error and usage.

Output: ~/bin/slideshowDirectories.txt
Log:    ~/bin/slideshowGetDirectories.log
"""

import os
import logging
import argparse
from logging.handlers import RotatingFileHandler

# --- LOGGING: UNIVERSAL, ALWAYS WORKS ---
LOG_FILE = os.path.expanduser('~/bin/slideshowGetDirectories.log')

logger = logging.getLogger('slideshowGetDirectories')
logger.setLevel(logging.INFO)
logger.propagate = False
for h in logger.handlers[:]:
    logger.removeHandler(h)

handler = RotatingFileHandler(
    LOG_FILE,
    maxBytes=10*1024*1024,
    backupCount=1,
    encoding='utf-8'
)
handler.setFormatter(
    logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
)
logger.addHandler(handler)

logger.info("=== LOG INITIALIZED (slideshowGetDirectories) ===")
logger.info(f"Log file: {LOG_FILE}")

# --- CONFIG ---
IMAGE_EXTS = {'.jpg', '.jpeg', '.png', '.gif',
              '.bmp', '.tiff', '.webp'}
SKIP_NAME = "slideshow_exclude"
OUTPUT_FILE = os.path.expanduser('~/bin/slideshowDirectories.txt')


def has_image(path):
    """Return True if folder has one image file."""
    try:
        for entry in os.scandir(path):
            if entry.is_file():
                if entry.name.lower().endswith(tuple(IMAGE_EXTS)):
                    return True
    except Exception as e:
        logger.error(f"Error scanning {path}: {e}")
    return False


def main():
    # --- REQUIRED COMMAND-LINE ARGUMENT ---
    parser = argparse.ArgumentParser(
        description='Scan root directory for image folders'
    )
    parser.add_argument(
        'root_dir',
        help='Root directory to scan (REQUIRED)'
    )
    args = parser.parse_args()

    root_dir = os.path.abspath(args.root_dir)
    
    # Verify root directory exists
    if not os.path.isdir(root_dir):
        error_msg = f"ERROR: {root_dir} is not a valid directory"
        print(error_msg)
        logger.error(error_msg)
        return 1

    dirs_to_save = []

    print(f"Scanning: {root_dir}")
    print(f"Output:   {OUTPUT_FILE}")
    print(f"Log:      {LOG_FILE}")
    print(f"Skip:     {SKIP_NAME}\n")

    logger.info(f"Scanning root: {root_dir}")

    try:
        for root, subdirs, files in os.walk(root_dir):
            # --- Skip slideshow_exclude ---
            if SKIP_NAME in subdirs:
                skip_path = os.path.join(root, SKIP_NAME)
                subdirs.remove(SKIP_NAME)
                logger.info(f"SKIPPED: {skip_path}")
                print(f"Skipped:  {skip_path}")

            # --- Add if has images ---
            if has_image(root):
                dirs_to_save.append(root)
                logger.info(f"ADDED: {root}")
                print(f"Added:    {root}")

        # --- Write output file ---
        with open(OUTPUT_FILE, 'w') as f:
            for d in sorted(dirs_to_save):
                f.write(f'"{d}"\n')

        logger.info(f"SUCCESS: {len(dirs_to_save)} directories written")
        print(f"\nDone: {len(dirs_to_save)} folders → {OUTPUT_FILE}")

    except Exception as e:
        error_msg = f"FATAL ERROR: {e}"
        logger.error(error_msg)
        print(f"\n{error_msg}")
        return 1

    finally:
        logger.info("=== SCRIPT ENDED ===\n")

    return 0


if __name__ == "__main__":
    exit(main())
