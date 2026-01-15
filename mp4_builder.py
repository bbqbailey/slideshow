#!/usr/bin/env python3
"""
mp4_builder.py

Build hourly MP4 timelapse videos from your per-day per-camera JPG snapshots using ffmpeg.

Key behavior:
- Camera selection flags:
    --all
    --camera1  (backwindows)
    --camera2  (basementWoodRm)
    --camera3  (driveway)
    --camera4  (frontDoorInside)
    --camera5  (garagedoors)
    --camera6  (livingRoom)

- Output:
    Writes MP4s into the SAME daily camera directory as the JPGs:
      .../archive/YYYYMMDD/<camera>/<camera>-HH00.mp4

- Hourly windows (mtime-based, tolerates drift):
    For each hour HH00:
      include frames with mtime in [day HH:00:00, day (HH+1):05:00)
    Special case HH00=0000:
      include previous day frames in [prev 23:55:00, day 00:00:00)
      plus current day frames in [day 00:00:00, day 01:05:00)

- Smart rebuild:
    * For past hours: skip if MP4 exists and is newer than newest JPG in that hour window.
    * For the current hour: ALWAYS rebuild so you get the most current MP4 even if the hour isn't complete.
      (Filename stays HH00.mp4.)

- No args:
    Prints help + camera mapping and exits with status 2.
"""

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple


# ---------------------------
# CONFIG (edit if desired)
# ---------------------------
ARCHIVE_ROOT_DEFAULT = "/media/CameraSnapshots/SecurityCameraSnapshots/archive"

# Encoding / playback tuning
OUTPUT_FPS_DEFAULT = 15.0
SCALE_MAX_WIDTH_DEFAULT = 1920
CRF_DEFAULT = 23
PRESET_DEFAULT = "veryfast"

# Minimum frames to bother creating an MP4 (per hour)
MIN_FRAMES_DEFAULT = 30

# Overlap settings
OVERLAP_MINUTES = 5

JPEG_EXTS = (".jpg", ".jpeg", ".JPG", ".JPEG")


CAMERA_MAP: Dict[str, str] = {
    "camera1": "backwindows",
    "camera2": "basementWoodRm",
    "camera3": "driveway",
    "camera4": "frontDoorInside",
    "camera5": "garagedoors",
    "camera6": "livingRoom",
}


@dataclass(frozen=True)
class Config:
    archive_root: Path
    day: Optional[str]          # YYYYMMDD, None => latest
    cameras: List[str]          # list of camera subdir names
    output_fps: float
    scale_max_width: int
    crf: int
    preset: str
    min_frames: int
    verbose: bool


def eprint(*args, **kwargs) -> None:
    print(*args, file=sys.stderr, **kwargs)


def camera_mapping_text() -> str:
    lines = ["Camera mappings:"]
    for k in sorted(CAMERA_MAP.keys()):
        lines.append(f"  --{k}  =>  {CAMERA_MAP[k]}")
    lines.append("  --all   =>  all cameras above")
    return "\n".join(lines)


def require_ffmpeg() -> str:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise SystemExit("ERROR: ffmpeg not found in PATH.")
    return ffmpeg


def list_day_dirs(archive_root: Path) -> List[str]:
    if not archive_root.exists():
        return []
    days: List[str] = []
    for p in archive_root.iterdir():
        if p.is_dir():
            name = p.name
            if len(name) == 8 and name.isdigit():
                days.append(name)
    days.sort()
    return days


def pick_latest_day(archive_root: Path) -> Optional[str]:
    days = list_day_dirs(archive_root)
    return days[-1] if days else None


def parse_args(argv: List[str]) -> Tuple[argparse.ArgumentParser, argparse.Namespace]:
    parser = argparse.ArgumentParser(
        description="Build hourly MP4 timelapses from per-day per-camera JPG snapshots (mtime windows + overlap).",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
        epilog=camera_mapping_text(),
    )

    cam = parser.add_argument_group("camera selection (choose at least one)")
    cam.add_argument("--all", action="store_true", help="Build for all cameras.")
    for i in range(1, 7):
        cam.add_argument(f"--camera{i}", action="store_true", help=f"Build for {CAMERA_MAP[f'camera{i}']}.")

    parser.add_argument(
        "--archive-root",
        default=ARCHIVE_ROOT_DEFAULT,
        help="Root of the archive tree that contains YYYYMMDD directories.",
    )
    parser.add_argument(
        "--day",
        default=None,
        help="Day to build in YYYYMMDD (default: latest day directory under archive-root).",
    )

    enc = parser.add_argument_group("encoding")
    enc.add_argument("--output-fps", type=float, default=OUTPUT_FPS_DEFAULT, help="Output video FPS.")
    enc.add_argument("--scale-max-width", type=int, default=SCALE_MAX_WIDTH_DEFAULT, help="Max width for scaling frames.")
    enc.add_argument("--crf", type=int, default=CRF_DEFAULT, help="x264 CRF quality (lower=better, bigger).")
    enc.add_argument("--preset", default=PRESET_DEFAULT, help="x264 preset.")

    parser.add_argument("--min-frames", type=int, default=MIN_FRAMES_DEFAULT, help="Minimum frames required per hour MP4.")
    parser.add_argument("-v", "--verbose", action="store_true", help="Verbose logging.")

    ns = parser.parse_args(argv)
    return parser, ns


def selected_cameras(ns: argparse.Namespace) -> List[str]:
    cams: List[str] = []
    if ns.all:
        return list(CAMERA_MAP.values())

    for i in range(1, 7):
        if getattr(ns, f"camera{i}", False):
            cams.append(CAMERA_MAP[f"camera{i}"])
    return cams


def yyyymmdd_to_date(day: str) -> datetime:
    # local time
    return datetime.strptime(day, "%Y%m%d")


def hour_window(day_dt: datetime, hour: int) -> Tuple[datetime, datetime]:
    """
    For hour HH00 on day_dt (local):
      start = day_dt + HH:00
      end   = day_dt + (HH+1):00 + overlap
    Note: hour=23 end goes into next day.
    """
    start = day_dt.replace(hour=hour, minute=0, second=0, microsecond=0)
    end = start + timedelta(hours=1, minutes=OVERLAP_MINUTES)
    return start, end


def list_jpgs_in_range(dir_path: Path, start_dt: datetime, end_dt: datetime) -> List[Tuple[Path, float]]:
    """
    Return (path, mtime) for jpgs in dir_path with mtime in [start_dt, end_dt).
    Uses local timestamps via mtime epoch comparisons.
    """
    if not dir_path.exists():
        return []

    start_ts = start_dt.timestamp()
    end_ts = end_dt.timestamp()

    out: List[Tuple[Path, float]] = []

    # scandir is faster than glob for large dirs
    try:
        with os.scandir(dir_path) as it:
            for entry in it:
                if not entry.is_file():
                    continue
                name = entry.name
                # quick extension check
                if not name.endswith(JPEG_EXTS):
                    continue
                try:
                    st = entry.stat()
                except OSError:
                    continue
                mt = st.st_mtime
                if mt < start_ts or mt >= end_ts:
                    continue
                out.append((Path(entry.path), mt))
    except FileNotFoundError:
        return []

    out.sort(key=lambda x: x[1])
    return out


def write_concat_list(frames: List[Tuple[Path, float]], list_path: Path) -> None:
    """
    ffmpeg concat demuxer list file.
    """
    with open(list_path, "w", encoding="utf-8") as f:
        for p, _mt in frames:
            s = str(p.resolve())
            s = s.replace("'", r"'\''")
            f.write(f"file '{s}'\n")


def run_ffmpeg_concat(
    ffmpeg: str,
    list_file: Path,
    out_mp4: Path,
    out_fps: float,
    scale_max_width: int,
    crf: int,
    preset: str,
    verbose: bool,
) -> None:
    # scale: cap width, preserve aspect ratio, ensure even height
    vf = f"scale='min({scale_max_width},iw)':-2"

    cmd = [
        ffmpeg,
        "-y",
        "-hide_banner",
        "-loglevel", "info" if verbose else "error",
        "-f", "concat",
        "-safe", "0",
        "-i", str(list_file),
        "-vf", vf,
        "-r", str(out_fps),
        "-c:v", "libx264",
        "-preset", preset,
        "-crf", str(crf),
        "-pix_fmt", "yuv420p",
        "-movflags", "+faststart",
        str(out_mp4),
    ]

    if verbose:
        eprint("FFMPEG:", " ".join(cmd))

    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg failed ({proc.returncode}):\n{proc.stderr.strip()}")


def newest_mtime(frames: List[Tuple[Path, float]]) -> Optional[float]:
    if not frames:
        return None
    return frames[-1][1]  # sorted by mtime


def should_skip_past_hour(out_mp4: Path, frames: List[Tuple[Path, float]], verbose: bool) -> bool:
    """
    Skip if output exists and is newer than newest input frame.
    """
    if not out_mp4.exists():
        return False

    src_newest = newest_mtime(frames)
    if src_newest is None:
        return True  # nothing to build anyway

    out_mt = out_mp4.stat().st_mtime
    if out_mt >= src_newest:
        if verbose:
            eprint(f"SKIP (up-to-date): {out_mp4.name} out_mtime={out_mt:.0f} src_newest={src_newest:.0f}")
        return True

    return False


def build_hour_mp4(
    ffmpeg: str,
    out_mp4: Path,
    frames: List[Tuple[Path, float]],
    cfg: Config,
) -> None:
    if len(frames) < cfg.min_frames:
        eprint(f"SKIP: {out_mp4.name} only {len(frames)} frames (min {cfg.min_frames})")
        return

    out_mp4.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="mp4_builder_") as td:
        td_path = Path(td)
        list_file = td_path / "frames.txt"
        tmp_mp4 = td_path / "out.mp4"

        write_concat_list(frames, list_file)
        run_ffmpeg_concat(
            ffmpeg=ffmpeg,
            list_file=list_file,
            out_mp4=tmp_mp4,
            out_fps=cfg.output_fps,
            scale_max_width=cfg.scale_max_width,
            crf=cfg.crf,
            preset=cfg.preset,
            verbose=cfg.verbose,
        )

        # Atomic-ish replace
        #os.replace(tmp_mp4, out_mp4)  #didn't' work with cross accessing filesystems
        shutil.copy2(tmp_mp4, out_mp4)


    eprint(f"OK: {out_mp4} (frames={len(frames)})")


def build_for_camera_day(cfg: Config, ffmpeg: str, day: str, camera: str) -> int:
    """
    Build MP4s for a single camera for the specified day.
    Returns number of MP4s built (not skipped).
    """
    day_dir = cfg.archive_root / day / camera
    if not day_dir.exists():
        eprint(f"ERROR: missing camera dir: {day_dir}")
        return 0

    now = datetime.now()
    day_dt = yyyymmdd_to_date(day)

    # Determine "current hour" relative to now IF the day is today.
    is_today = (day_dt.date() == now.date())
    current_hour = now.hour if is_today else 23

    built = 0

    # Precompute prev day for hour 0000 overlap
    prev_day_dt = day_dt - timedelta(days=1)
    prev_day_str = prev_day_dt.strftime("%Y%m%d")
    prev_day_dir = cfg.archive_root / prev_day_str / camera

    for hour in range(0, current_hour + 1):
        out_name = f"{camera}-{hour:02}00.mp4"
        out_mp4 = day_dir / out_name

        start_dt, end_dt_full = hour_window(day_dt, hour)

        # For the current hour on today: end at "now" so MP4 is always most current.
        if is_today and hour == current_hour:
            end_dt = now
        else:
            end_dt = end_dt_full

        frames: List[Tuple[Path, float]] = []

        if hour == 0:
            # Include prev day 23:55 -> 24:00, if available
            prev_start = prev_day_dt.replace(hour=23, minute=60 - OVERLAP_MINUTES, second=0, microsecond=0)
            prev_end = day_dt.replace(hour=0, minute=0, second=0, microsecond=0)
            if prev_day_dir.exists():
                frames.extend(list_jpgs_in_range(prev_day_dir, prev_start, prev_end))

            # Plus current day 00:00 -> 01:05 (or now if current hour)
            frames.extend(list_jpgs_in_range(day_dir, start_dt, end_dt))
        else:
            frames = list_jpgs_in_range(day_dir, start_dt, end_dt)

        if not frames:
            if cfg.verbose:
                eprint(f"SKIP: {out_name} no frames in window [{start_dt} .. {end_dt})")
            continue

        # Skip logic:
        if not (is_today and hour == current_hour):
            # Past hour: only build if missing or outdated
            if should_skip_past_hour(out_mp4, frames, cfg.verbose):
                continue
        else:
            # Current hour: ALWAYS rebuild (your requirement)
            if cfg.verbose:
                eprint(f"BUILD current hour (forced): {out_name} window_end={end_dt}")

        try:
            build_hour_mp4(ffmpeg, out_mp4, frames, cfg)
            built += 1
        except Exception as e:
            eprint(f"ERROR building {out_name}: {e}")

    return built


def main(argv: List[str]) -> int:
    parser, ns = parse_args(argv)

    cams = selected_cameras(ns)
    if not cams:
        # No selection => print help + mapping, exit with 2
        parser.print_help(sys.stderr)
        eprint()
        eprint("ERROR: No camera selection provided. Use --all or --camera1..--camera6.")
        return 2

    cfg = Config(
        archive_root=Path(ns.archive_root),
        day=ns.day,
        cameras=cams,
        output_fps=float(ns.output_fps),
        scale_max_width=int(ns.scale_max_width),
        crf=int(ns.crf),
        preset=str(ns.preset),
        min_frames=int(ns.min_frames),
        verbose=bool(ns.verbose),
    )

    if not cfg.archive_root.exists():
        eprint(f"ERROR: archive root not found: {cfg.archive_root}")
        return 2

    day = cfg.day or pick_latest_day(cfg.archive_root)
    if not day:
        eprint(f"ERROR: no YYYYMMDD directories found under: {cfg.archive_root}")
        return 1

    ffmpeg = require_ffmpeg()

    total_built = 0
    for cam in cfg.cameras:
        eprint(f"=== CAMERA: {cam}  DAY: {day} ===")
        total_built += build_for_camera_day(cfg, ffmpeg, day, cam)

    eprint(f"\nDONE. Built {total_built} MP4 file(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

