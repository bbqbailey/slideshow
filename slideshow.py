#!/usr/bin/env python3
# Slideshow.py - Version V3-5
#
# V3-5 change:
# - Client JS now PRELOADS and DECODEs each new latest.jpg off-screen before swapping the visible <img>.
#   This fixes the "network is fast but paint is painfully slow" behavior seen on Chromebook/Chrome.
#
# Additional change (no version bump requested):
# - All source images are now RESIZED to fit within 1920x1080 before being saved as latest.jpg,
#   and saved at a lower JPEG quality to reduce bandwidth and improve remote performance.

import ssl
import os
import time
import json
import logging
import logging.handlers
import argparse
import threading
from http.server import SimpleHTTPRequestHandler, HTTPServer
from socketserver import ThreadingMixIn
from io import BytesIO
from urllib.parse import urlparse, parse_qs

import requests
from PIL import Image, ImageDraw, ImageFont, ExifTags

# --- SLIDESHOW CONFIGURATION ---
IMAGES_PER_DIRECTORY = 75  # deprecated since V3-0

SLIDE_DURATION_SECONDS = 10
IMAGE_COUNT_DISPLAY = 30

IMAGE_EXTENSIONS = ('.jpg', '.jpeg', '.png', '.gif')

RADAR_IMAGE_URLS = [
    "https://radar.weather.gov/ridge/standard/CONUS-LARGE_0.gif",
    "https://radar.weather.gov/ridge/standard/KFFC_0.gif",
]

PROJECT_DIR = os.path.expanduser('~/myProjects/python/slideshow')

WEATHER_PANEL_FILENAME = "weather_panel.png"
WEATHER_PANEL_PATH = os.path.join(PROJECT_DIR, WEATHER_PANEL_FILENAME)

SECURITY_BASE_DIR = "/media/CameraSnapshots/SecurityCameraSnapshots/latest"
SECURITY_CAMERA_SUBDIRS_IN_ORDER = [
    "backwindows",
    "basementWoodRm",
    "driveway",
    "frontDoorInside",
    "garagedoors",
    "livingRoom",
]
SECURITY_LATEST_FILENAME = "latest.jpg"

# --- DISPLAY OUTPUT TUNING (bandwidth/paint) ---
# Fit within a 1920x1080 "box" (preserves aspect ratio).
DISPLAY_MAX_SIZE = (1920, 1080)

# Lower than 95 to reduce size dramatically; tune if you want.
JPEG_QUALITY_DEFAULT = 85

# --- LATEST IMAGE OUTPUT ---
LATEST_IMAGE_DIR = os.path.join(PROJECT_DIR, "latestImage")
LATEST_IMAGE_FILENAME = "latest.jpg"
LATEST_IMAGE_PATH = os.path.join(LATEST_IMAGE_DIR, LATEST_IMAGE_FILENAME)

# /frame long-poll timeout (seconds)
FRAME_LONGPOLL_TIMEOUT_SECONDS = 30

# --- LOGGING ---
GENERAL_LOG = os.path.join(PROJECT_DIR, 'slideshow.log')
general_handler = logging.handlers.TimedRotatingFileHandler(
    GENERAL_LOG, when='midnight', interval=1, backupCount=1, encoding='utf-8'
)
general_handler.setLevel(logging.WARNING)
general_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))

DISPLAY_LOG = os.path.join(PROJECT_DIR, 'slideshow-display.log')
display_handler = logging.handlers.TimedRotatingFileHandler(
    DISPLAY_LOG, when='midnight', interval=1, backupCount=1, encoding='utf-8'
)
display_handler.setLevel(logging.INFO)
display_handler.setFormatter(logging.Formatter('%(asctime)s - %(message)s'))

display_logger = logging.getLogger('display')
display_logger.setLevel(logging.INFO)
display_logger.propagate = False
display_logger.addHandler(display_handler)
display_logger.info("=== DISPLAY LOG STARTED (V3-5 LATEST-IMAGE + LONG-POLL + PRELOAD+DECODE, deterministic DFS) ===")

stream_handler = logging.StreamHandler()
stream_handler.setLevel(logging.DEBUG)
stream_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))

root_logger = logging.getLogger()
root_logger.setLevel(logging.DEBUG)
root_logger.handlers.clear()
root_logger.addHandler(general_handler)
root_logger.addHandler(stream_handler)


def log_image_display(label: str):
    display_logger.info(label)


# ======================================================================
#  GLOBAL FRAME STATE
# ======================================================================
current_frame_id = 0
frame_lock = threading.Lock()
frame_condition = threading.Condition(frame_lock)


def _ensure_latest_image_dir():
    os.makedirs(LATEST_IMAGE_DIR, exist_ok=True)


def _atomic_write_latest_jpg(frame_bytes: bytes):
    tmp_path = LATEST_IMAGE_PATH + ".tmp"
    try:
        with open(tmp_path, "wb") as f:
            f.write(frame_bytes)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, LATEST_IMAGE_PATH)
    except Exception as e:
        logging.error(f"Failed writing latest image: {LATEST_IMAGE_PATH} | {e}")
        try:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
        except Exception:
            pass


def update_current_frame(frame_bytes: bytes, label: str):
    global current_frame_id

    _atomic_write_latest_jpg(frame_bytes)

    with frame_condition:
        current_frame_id += 1
        fid = current_frame_id
        frame_condition.notify_all()

    log_image_display(label)
    logging.info(f"Updated frame_id={fid} label={label}")


def get_current_frame_id() -> int:
    with frame_lock:
        return current_frame_id


def wait_for_frame_change(since_id: int, timeout_seconds: int) -> int:
    deadline = time.monotonic() + max(0, timeout_seconds)
    with frame_condition:
        while current_frame_id == since_id:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            frame_condition.wait(timeout=remaining)
        return current_frame_id


# ======================================================================
#  IMAGE GENERATION HELPERS
# ======================================================================
def _resample_filter():
    # Pillow version compatibility
    try:
        return Image.Resampling.LANCZOS
    except Exception:
        return Image.LANCZOS


def _fit_to_display_box(img: Image.Image) -> Image.Image:
    """
    Resize in-place (thumbnail) to fit within DISPLAY_MAX_SIZE while preserving aspect ratio.
    If already smaller than the box, it is unchanged.
    """
    try:
        img.thumbnail(DISPLAY_MAX_SIZE, resample=_resample_filter())
    except Exception as e:
        logging.warning(f"Resize thumbnail failed; using original size. Error: {e}")
    return img


def _jpeg_bytes_from_pil(img: Image.Image, quality: int = JPEG_QUALITY_DEFAULT) -> bytes:
    buf = BytesIO()
    # optimize=True reduces size; progressive=True may help perceived load in some clients.
    img.save(buf, format='JPEG', quality=quality, optimize=True, progressive=True)
    return buf.getvalue()


def make_placeholder_image(text: str) -> bytes:
    img = Image.new('RGB', (1920, 1080), (50, 0, 0))
    draw = ImageDraw.Draw(img)
    font = ImageFont.load_default()
    draw.text((50, 50), text, fill=(255, 255, 255), font=font)
    return _jpeg_bytes_from_pil(img, quality=JPEG_QUALITY_DEFAULT)


def generate_time_frame() -> bytes:
    current_time = time.strftime("%I:%M").lstrip("0")
    logging.info(f"Generating time frame: {current_time}")

    img = Image.new('RGB', (1920, 1080), (0, 0, 0))
    draw = ImageDraw.Draw(img)

    font_path = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
    try:
        font = ImageFont.truetype(font_path, 300)
    except IOError:
        font = ImageFont.load_default()

    try:
        bbox = draw.textbbox((0, 0), current_time, font=font)
        w, h = bbox[2] - bbox[0], bbox[3] - bbox[1]
    except AttributeError:
        w, h = draw.textsize(current_time, font=font)

    draw.text(((1920 - w) // 2, (1080 - h) // 2),
              current_time, font=font, fill=(255, 255, 255))

    return _jpeg_bytes_from_pil(img, quality=JPEG_QUALITY_DEFAULT)


def image_path_to_jpeg_bytes(image_path: str) -> bytes:
    try:
        logging.info(f"Serving image: {image_path}")
        img = Image.open(image_path)
        img.verify()
        img = Image.open(image_path)

        try:
            orientation_tag = None
            for o in ExifTags.TAGS:
                if ExifTags.TAGS[o] == 'Orientation':
                    orientation_tag = o
                    break
            exif = img._getexif()
            if exif and orientation_tag is not None:
                orient = dict(exif.items()).get(orientation_tag, 1)
                if orient == 3:
                    img = img.rotate(180, expand=True)
                elif orient == 6:
                    img = img.rotate(270, expand=True)
                elif orient == 8:
                    img = img.rotate(90, expand=True)
        except Exception as e:
            logging.warning(f"EXIF error: {e}")

        img = img.convert("RGB")

        # NEW: cap to display size to reduce bandwidth/paint time
        img = _fit_to_display_box(img)

        return _jpeg_bytes_from_pil(img, quality=JPEG_QUALITY_DEFAULT)

    except Exception as e:
        logging.error(f"SKIP: {image_path} | {e}")
        return make_placeholder_image(f"SKIPPED: {os.path.basename(image_path)}")


def fetch_radar_frame(url: str) -> bytes:
    try:
        logging.info(f"Fetching radar image: {url}")
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        img = Image.open(BytesIO(resp.content)).convert("RGB")

        # Cap radar frames too (some sources can be large)
        img = _fit_to_display_box(img)

        return _jpeg_bytes_from_pil(img, quality=JPEG_QUALITY_DEFAULT)
    except Exception as e:
        logging.error(f"RADAR ERROR: {url} | {e}")
        return make_placeholder_image("RADAR ERROR")


def generate_weather_frame() -> bytes:
    if not os.path.exists(WEATHER_PANEL_PATH):
        logging.warning(f"Weather panel not found at {WEATHER_PANEL_PATH}")
        return make_placeholder_image("WEATHER PANEL MISSING")

    try:
        logging.info(f"Serving weather panel: {WEATHER_PANEL_PATH}")
        return image_path_to_jpeg_bytes(WEATHER_PANEL_PATH)
    except Exception as e:
        logging.error(f"WEATHER PANEL ERROR: {WEATHER_PANEL_PATH} | {e}")
        return make_placeholder_image("WEATHER ERROR")


def generate_security_frames_in_order():
    frames = []
    for subdir in SECURITY_CAMERA_SUBDIRS_IN_ORDER:
        img_path = os.path.join(SECURITY_BASE_DIR, subdir, SECURITY_LATEST_FILENAME)

        if not os.path.exists(img_path):
            logging.warning(f"Security image missing: {img_path}")
            continue

        jpeg_bytes = image_path_to_jpeg_bytes(img_path)
        frames.append((jpeg_bytes, f"[SECURITY] {subdir}"))
    return frames


# ======================================================================
#  DETERMINISTIC DEPTH-FIRST TRAVERSAL
# ======================================================================
def _walk_roots_depth_first_no_sort(starting_roots):
    def onerror(err):
        logging.warning(f"os.walk error: {err}")

    for root0 in starting_roots:
        if not os.path.isdir(root0):
            logging.warning(f"Invalid root directory (skipping): {root0}")
            continue

        for root, dirs, files in os.walk(root0, topdown=True, onerror=onerror, followlinks=False):
            dirs[:] = [d for d in dirs if d != 'slideshow_exclude']
            if os.path.basename(root) == 'slideshow_exclude':
                continue

            for fname in files:
                try:
                    if fname.lower().endswith(IMAGE_EXTENSIONS):
                        yield os.path.join(root, fname)
                except Exception as e:
                    logging.warning(f"Filename handling error in {root}: {fname} | {e}")


# ======================================================================
#  SLIDESHOW PRODUCER
# ======================================================================
def generate_slideshow_images(starting_roots, time_interval):
    duration = time_interval
    photo_counter = 0

    if not starting_roots:
        logging.warning("No starting roots available at startup.")
        update_current_frame(make_placeholder_image("NO DIRECTORIES"), "[NO DIRECTORIES]")
    else:
        update_current_frame(make_placeholder_image("Starting slideshow..."), "[STARTUP]")

    while True:
        any_photo_shown = False

        for image_path in _walk_roots_depth_first_no_sort(starting_roots):
            any_photo_shown = True

            update_current_frame(image_path_to_jpeg_bytes(image_path), image_path)
            time.sleep(duration)

            photo_counter += 1

            if photo_counter >= IMAGE_COUNT_DISPLAY:
                update_current_frame(generate_time_frame(), "[TIME]")
                time.sleep(duration)

                update_current_frame(generate_weather_frame(), "[WEATHER]")
                time.sleep(duration)

                for radar_url in RADAR_IMAGE_URLS:
                    update_current_frame(fetch_radar_frame(radar_url), f"[RADAR] {radar_url}")
                    time.sleep(duration)

                for frame_bytes, label in generate_security_frames_in_order():
                    update_current_frame(frame_bytes, label)
                    time.sleep(duration)

                photo_counter = 0

        if not any_photo_shown:
            logging.warning("Traversal found no images. Sleeping 5 seconds before retry.")
            update_current_frame(make_placeholder_image("NO IMAGES FOUND"), "[NO IMAGES FOUND]")
            time.sleep(5)
        else:
            logging.info("Completed full traversal. Wrapping to start (V3-5).")


# ======================================================================
#  HTTP HANDLER
# ======================================================================
class SlideshowHTTPRequestHandler(SimpleHTTPRequestHandler):

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        qs = parse_qs(parsed.query)

        if path == '/slideshow':
            self.handle_slideshow_page()
            return

        if path == '/frame':
            self.handle_frame_id_longpoll(qs)
            return

        if path == '/latestImage/latest.jpg':
            self.handle_latest_image()
            return

        if path == '/favicon.ico':
            self.send_response(204)
            self.end_headers()
            return

        self.send_error(404, "Not Found")


    def handle_slideshow_page(self):
        html = f'''
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="UTF-8">
            <title>Slideshow V3-5 Latest Image (Long-Poll + Preload+Decode)</title>
            <style>
                html, body {{
                    margin:0; padding:0; width:100%; height:100%;
                    background:#000; overflow:hidden;
                }}
                body {{ display:flex; justify-content:center; align-items:center; }}
                img {{ width:100vw; height:100vh; object-fit:contain; }}
            </style>
        </head>
        <body>
            <img id="slide" src="/latestImage/latest.jpg?f=0&t=0" alt="Slideshow Image">

            <script>
                const img = document.getElementById('slide');

                // Hint to Chrome: decode asynchronously, don't lazy-load.
                img.decoding = 'async';
                img.loading = 'eager';

                let lastFrameId = -1;
                let inFlight = false;

                function sleep(ms) {{
                    return new Promise(res => setTimeout(res, ms));
                }}

                async function preloadAndDecode(url) {{
                    const pre = new Image();
                    pre.decoding = 'async';
                    pre.loading = 'eager';
                    pre.src = url;

                    // Wait for bytes + decode. decode() is supported on Chrome.
                    // If decode() fails, fall back to onload.
                    try {{
                        await pre.decode();
                    }} catch (e) {{
                        await new Promise((resolve, reject) => {{
                            pre.onload = resolve;
                            pre.onerror = reject;
                        }});
                    }}
                }}

                async function loop() {{
                    while (true) {{
                        if (document.visibilityState !== 'visible') {{
                            await sleep(500);
                            continue;
                        }}

                        try {{
                            // Long-poll until frame_id changes (or server timeout returns same id)
                            const r = await fetch('/frame?since=' + encodeURIComponent(lastFrameId) + '&t=' + Date.now(), {{
                                cache: 'no-store'
                            }});
                            if (!r.ok) {{
                                await sleep(300);
                                continue;
                            }}

                            const data = await r.json();
                            const fid = data.frame_id;

                            if (typeof fid !== 'number' || fid === lastFrameId) {{
                                continue;
                            }}

                            // Prevent piling up swaps if decode is slow
                            if (inFlight) {{
                                continue;
                            }}
                            inFlight = true;

                            const url = '/latestImage/latest.jpg?f=' + fid + '&t=' + Date.now();

                            // CRITICAL: decode off-screen BEFORE swapping visible <img>
                            await preloadAndDecode(url);

                            img.src = url;
                            lastFrameId = fid;
                            inFlight = false;

                        }} catch (e) {{
                            inFlight = false;
                            await sleep(300);
                        }}
                    }}
                }}

                loop();
            </script>
        </body>
        </html>
        '''.strip()

        body = html.encode('utf-8')
        self.send_response(200)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.send_header('Cache-Control', 'no-cache, no-store, must-revalidate')
        self.send_header('Pragma', 'no-cache')
        self.send_header('Expires', '0')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)
        self.wfile.flush()


    def _send_json(self, obj: dict):
        body = json.dumps(obj).encode("utf-8")
        self.send_response(200)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Cache-Control', 'no-cache, no-store, must-revalidate')
        self.send_header('Pragma', 'no-cache')
        self.send_header('Expires', '0')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)
        self.wfile.flush()


    def handle_frame_id_longpoll(self, qs):
        since_val = -1
        try:
            if 'since' in qs and qs['since']:
                since_val = int(qs['since'][0])
        except Exception:
            since_val = -1

        current = get_current_frame_id()
        if current != since_val:
            self._send_json({"frame_id": current})
            return

        new_id = wait_for_frame_change(since_val, FRAME_LONGPOLL_TIMEOUT_SECONDS)
        self._send_json({"frame_id": new_id})


    def handle_latest_image(self):
        if not os.path.exists(LATEST_IMAGE_PATH):
            body = make_placeholder_image("WAITING FOR FIRST FRAME")
            self.send_response(200)
            self.send_header('Content-Type', 'image/jpeg')
            self.send_header('Cache-Control', 'no-cache, no-store, must-revalidate')
            self.send_header('Pragma', 'no-cache')
            self.send_header('Expires', '0')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            self.wfile.flush()
            return

        try:
            with open(LATEST_IMAGE_PATH, "rb") as f:
                body = f.read()

            self.send_response(200)
            self.send_header('Content-Type', 'image/jpeg')
            self.send_header('Cache-Control', 'no-cache, no-store, must-revalidate')
            self.send_header('Pragma', 'no-cache')
            self.send_header('Expires', '0')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            self.wfile.flush()
        except Exception as e:
            logging.warning(f"Latest image read/send error: {e}")
            self.send_error(500, "Internal Server Error")


# ======================================================================
#  THREADED HTTP SERVER
# ======================================================================
class ThreadingHTTPServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True


def load_directories(filepath):
    if not os.path.exists(filepath):
        logging.warning(f"File not found: {filepath}")
        return []
    with open(filepath) as f:
        return [line.strip().strip('"') for line in f if line.strip()]


def run_server(port=8000):
    httpd = ThreadingHTTPServer(('', port), SlideshowHTTPRequestHandler)

    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(
        certfile="/home/superben/myProjects/python/slideshow/certs/hottub.crt",
        keyfile="/home/superben/myProjects/python/slideshow/certs/hottub.key"
    )
    httpd.socket = context.wrap_socket(httpd.socket, server_side=True)

    logging.info("Server on port %s (V3-5 LATEST-IMAGE + LONG-POLL + PRELOAD+DECODE, deterministic DFS, threaded)", port)
    logging.info("Serving on https://0.0.0.0:8000/slideshow")
    httpd.serve_forever()


# ======================================================================
#  MAIN
# ======================================================================
if __name__ == "__main__":
    _ensure_latest_image_dir()

    parser = argparse.ArgumentParser(
        description="Slideshow V3-5 — Latest-image slideshow with /frame long-poll and client preload+decode swap (no MJPEG, no meta refresh).",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument('preferred', nargs='?', help="Guest list: slideshowPreferred<NAME>.txt")
    args = parser.parse_args()

    if args.preferred:
        txt_path = os.path.join(PROJECT_DIR, f'slideshowPreferred{args.preferred}.txt')
    else:
        txt_path = os.path.join(PROJECT_DIR, 'slideshowDirectories.txt')

    starting_roots = load_directories(txt_path)

    if not starting_roots:
        print("Error: No starting directories found.")
        logging.error("No starting directories found. Exiting.")
        raise SystemExit(1)

    threading.Thread(
        target=generate_slideshow_images,
        args=(starting_roots, SLIDE_DURATION_SECONDS),
        daemon=True
    ).start()

    run_server()

