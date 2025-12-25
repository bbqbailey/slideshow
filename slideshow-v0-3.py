#!/usr/bin/env python3
# Slideshow.py - Version 3.0
# Features:
# - Full images (no cropping), object-fit:contain
# - Handles RGBA PNGs (converts to RGB)
# - Guest mode: --preferred GuestName.txt
# - All files in ~/myProjects/python/slideshow/
# - Wrapper: ~/bin/slideshow
# - Based on your working V2.2

import os
import time
import random
import logging
import logging.handlers
import argparse
from datetime import datetime
from http.server import SimpleHTTPRequestHandler, HTTPServer
from PIL import Image, ImageDraw, ImageFont, ExifTags
import threading

# --- SLIDESHOW CONFIGURATION ---
IMAGES_PER_DIRECTORY = 40
TIME_IMAGE_EVERY_N = 10
SLIDE_DURATION_SECONDS = 5
IMAGE_EXTENSIONS = ('.jpg', '.jpeg', '.png', '.gif')

# --- PROJECT DIRECTORY ---
PROJECT_DIR = os.path.expanduser('~/myProjects/python/slideshow')

# --- LOGGING SETUP ---
GENERAL_LOG = os.path.join(PROJECT_DIR, 'slideshow.log')
general_handler = logging.handlers.TimedRotatingFileHandler(
    GENERAL_LOG, when='midnight', interval=1, backupCount=1, encoding='utf-8')
general_handler.setLevel(logging.WARNING)
general_handler.setFormatter(
    logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))

DISPLAY_LOG = os.path.join(PROJECT_DIR, 'slideshow_display.log')
display_handler = logging.handlers.TimedRotatingFileHandler(
    DISPLAY_LOG, when='midnight', interval=1, backupCount=1, encoding='utf-8')
display_handler.setLevel(logging.INFO)
display_handler.setFormatter(
    logging.Formatter('%(asctime)s - %(message)s'))

display_logger = logging.getLogger('display')
display_logger.setLevel(logging.INFO)
display_logger.propagate = False
display_logger.addHandler(display_handler)
display_logger.info("=== DISPLAY LOG STARTED ===")

stream_handler = logging.StreamHandler()
stream_handler.setLevel(logging.DEBUG)
stream_handler.setFormatter(
    logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))

root_logger = logging.getLogger()
root_logger.setLevel(logging.DEBUG)
root_logger.handlers.clear()
root_logger.addHandler(general_handler)
root_logger.addHandler(stream_handler)

def log_image_display(image_path: str):
    display_logger.info(image_path)


class SlideshowHTTPRequestHandler(SimpleHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/slideshow':
            self.send_response(200)
            self.send_header('Content-type', 'text/html')
            self.end_headers()
            self.wfile.write(self.get_html_content().encode('utf-8'))
        elif self.path == '/current_image':
            self.send_response(200)
            self.send_header('Content-type', 'image/jpeg')
            self.end_headers()
            with open('/tmp/resized_image.jpg', 'rb') as f:
                self.wfile.write(f.read())
        elif self.path == '/favicon.ico':
            self.send_response(204)
            self.end_headers()
        else:
            self.send_error(404, "File not found")

    def get_html_content(self):
        return '''
        <!DOCTYPE html>
        <html lang="en">
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>Slideshow</title>
            <style>
                html, body { margin:0; padding:0; width:100%; height:100%; background:#000; overflow:hidden; }
                body { display:flex; justify-content:center; align-items:center; }
                img { width:100vw; height:100vh; object-fit:contain; display:block; }
            </style>
        </head>
        <body>
            <img src="/current_image" alt="Slideshow Image">
            <script>
                setTimeout(() => location.reload(), 5000);
            </script>
        </body>
        </html>
        '''.strip()


def generate_time_image():
    current_time = time.strftime("%I:%M").lstrip("0")
    logging.info(f"Generating time image: {current_time}")
    img = Image.new('RGB', (1920, 1080), (0, 0, 0))
    draw = ImageDraw.Draw(img)
    font_path = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
    try:
        font = ImageFont.truetype(font_path, 300)
    except IOError:
        font = ImageFont.load_default()
    try:
        bbox = draw.textbbox((0, 0), current_time, font=font)
        w = bbox[2] - bbox[0]
        h = bbox[3] - bbox[1]
    except AttributeError:
        w, h = draw.textsize(current_time, font=font)
    draw.text(((1920 - w) // 2, (1080 - h) // 2), current_time, font=font, fill=(255, 255, 255))
    img.save('/tmp/resized_image.jpg')
    logging.info("Time image saved")


def serve_image(image_path):
    try:
        logging.info(f"Serving: {image_path}")
        img = Image.open(image_path)
        img.verify()
        img = Image.open(image_path)

        # EXIF rotation
        try:
            for o in ExifTags.TAGS:
                if ExifTags.TAGS[o] == 'Orientation': break
            exif = img._getexif()
            if exif:
                orient = dict(exif.items()).get(o, 1)
                if orient == 3: img = img.rotate(180, expand=True)
                elif orient == 6: img = img.rotate(270, expand=True)
                elif orient == 8: img = img.rotate(90, expand=True)
        except Exception as e:
            logging.warning(f"EXIF error: {e}")

        # FIX: Convert RGBA → RGB
        img = img.convert("RGB")

        img.save('/tmp/resized_image.jpg', 'JPEG', quality=95)
        log_image_display(image_path)

    except Exception as e:
        logging.error(f"SKIP: {image_path} | {e}")
        placeholder = Image.new('RGB', (1920, 1080), (50, 0, 0))
        draw = ImageDraw.Draw(placeholder)
        draw.text((50, 50), f"SKIPPED: {os.path.basename(image_path)}", fill=(255,255,255))
        placeholder.save('/tmp/resized_image.jpg')
        log_image_display(f"[SKIPPED] {image_path}")


def generate_slideshow_images(directories, exclude_dirs_set, exclude_images_set, time_interval):
    duration = time_interval
    total_images_displayed = 0
    while True:
        if not directories:
            time.sleep(5)
            continue
        directory = random.choice(directories)
        logging.info(f"Selected directory: {directory}")
        image_files = []
        if os.path.isdir(directory):
            for file in os.listdir(directory):
                if file.lower().endswith(IMAGE_EXTENSIONS):
                    image_path = os.path.join(directory, file)
                    if image_path not in exclude_images_set:
                        image_files.append(image_path)
        if not image_files:
            logging.warning(f"No valid image files found in directory: {directory}")
            continue
        random.shuffle(image_files)
        image_files = image_files[:IMAGES_PER_DIRECTORY]
        for image_path in image_files:
            total_images_displayed += 1
            logging.info(f"Total images displayed: {total_images_displayed}")
            if total_images_displayed % TIME_IMAGE_EVERY_N == 0:
                generate_time_image()
            else:
                serve_image(image_path)
            time.sleep(duration)


def run_server(port=8000):
    httpd = HTTPServer(('', port), SlideshowHTTPRequestHandler)
    logging.info(f"Server on port {port}")
    httpd.serve_forever()


def load_directories(filepath):
    if not os.path.exists(filepath):
        logging.warning(f"File not found: {filepath}")
        return []
    with open(filepath) as f:
        dirs = [line.strip().strip('"') for line in f if line.strip()]
    logging.info(f"Loaded {len(dirs)} dirs from {filepath}")
    return dirs


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Slideshow V3.0 — Guest-Ready Photo Viewer",
        epilog="""
Examples:
  slideshow                     # Normal mode
  slideshow Durand              # Guest: Durand.txt
        """,
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument('preferred', nargs='?', help="Guest list: slideshowPreferred<NAME>.txt")
    args = parser.parse_args()

    # Load directories
    if args.preferred:
        path = os.path.join(PROJECT_DIR, f'slideshowPreferred{args.preferred}.txt')
        directories = load_directories(path)
        if not directories:
            print(f"Error: No directories in {path}")
            exit(1)
    else:
        path = os.path.join(PROJECT_DIR, 'slideshowDirectories.txt')
        directories = load_directories(path)

    # Exclusions
    exclude_dirs_set = set()
    exclude_file = os.path.join(PROJECT_DIR, 'exclude_dirs.txt')
    if os.path.exists(exclude_file):
        with open(exclude_file) as f:
            exclude_dirs_set = {line.strip() for line in f if line.strip()}
        logging.info(f"Loaded {len(exclude_dirs_set)} dir exclusions")

    directories = [d for d in directories if not any(ex in d for ex in exclude_dirs_set)]
    logging.info(f"Using {len(directories)} directories")

    exclude_images_set = set()
    img_file = os.path.join(PROJECT_DIR, 'exclude_images.txt')
    if os.path.exists(img_file):
        with open(img_file) as f:
            exclude_images_set = {line.strip() for line in f if line.strip()}
        logging.info(f"Loaded {len(exclude_images_set)} image exclusions")

    # Start
    threading.Thread(
        target=generate_slideshow_images,
        args=(directories, exclude_dirs_set, exclude_images_set, SLIDE_DURATION_SECONDS),
        daemon=True
    ).start()
    run_server()
