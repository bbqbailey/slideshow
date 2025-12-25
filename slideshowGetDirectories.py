#!/usr/bin/env python3
# slideshowGetDirectories.py - Version 2.1
# Purpose:
# - Scan current directory and all subdirectories
# - Output list of directories containing images
# - Skip any folder named: slideshow_exclude
# - Output file: ~/MyProjects/python/slideshow/slideshowDirectories.txt
# - Support exclude_dirs.txt and exclude_images.txt in project dir

import os

# --- PROJECT DIRECTORY (hardcoded, no variables) ---
PROJECT_DIR = os.path.expanduser('~/MyProjects/python/slideshow')

# --- OUTPUT AND CONFIG FILES ---
OUTPUT_FILE = os.path.join(PROJECT_DIR, 'slideshowDirectories.txt')
EXCLUDE_DIRS_FILE = os.path.join(PROJECT_DIR, 'exclude_dirs.txt')
EXCLUDE_IMAGES_FILE = os.path.join(PROJECT_DIR, 'exclude_images.txt')

# --- CONFIG ---
IMAGE_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.gif', '.bmp', '.tiff', '.webp'}
SKIP_NAME = "slideshow_exclude"


def has_image(path: str) -> bool:
    """Return True if folder has at least one image file."""
    try:
        for entry in os.scandir(path):
            if entry.is_file():
                if entry.name.lower().endswith(tuple(IMAGE_EXTENSIONS)):
                    return True
    except (PermissionError, OSError):
        pass
    return False


def main():
    cwd = os.getcwd()
    directories = []

    print(f"Scanning: {cwd}")
    print(f"Output:   {OUTPUT_FILE}")
    print(f"Skip:     {SKIP_NAME}\n")

    for root, subdirs, files in os.walk(cwd):
        # Skip slideshow_exclude
        if SKIP_NAME in subdirs:
            skip_path = os.path.join(root, SKIP_NAME)
            subdirs.remove(SKIP_NAME)
            print(f"Skipped:  {skip_path}")

        # Add if has images
        if has_image(root):
            directories.append(root)
            print(f"Added:    {root}")

    # Write output
    with open(OUTPUT_FILE, 'w') as f:
        for d in sorted(directories):
            f.write(f'"{d}"\n')

    print(f"\nDone: {len(directories)} directories → {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
    
