#!/bin/bash
# ~/bin/slideshow
# Launcher for slideshow-v4-0.py with optional guest list

PROJECT_DIR="$HOME/myProjects/python/slideshow"

cd "$PROJECT_DIR" || {
    echo "Error: Cannot access $PROJECT_DIR" >&2
    exit 1
}

# Kill any old slideshow.py instances (useful when run manually)
/usr/bin/pkill -f "python3.*slideshow.py" 2>/dev/null || true
sleep 1

# Pass any arg through as the guest name (0 or 1 arg typical)
exec /usr/bin/python3 slideshow.py "$@"

