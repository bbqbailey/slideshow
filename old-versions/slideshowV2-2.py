#!/usr/bin/env python3
# Slideshow.py - Version 2.0
# Features:
# - Randomized slideshow from directories in ~/bin/slideshowDirectories.txt
# - Excludes directories via substrings in ~/bin/exclude_dirs.txt
# - Excludes individual images via full paths in ~/bin/exclude_images.txt
# - Crops to fill 1920x1080 landscape canvas exactly (no borders, aspect preserved)
# - Handles EXIF orientation, time overlay every 10 images
# - Serves on port 8000, auto-reload every 5s in browser
# - Logging to console and dated file
# - Fixed PIL compatibility: Uses Image.ANTIALIAS for older Pillow versions

import os
import time
import random
import logging
from datetime import datetime
from http.server import SimpleHTTPRequestHandler, HTTPServer
from PIL import Image, ImageDraw, ImageFont, ExifTags
import threading




# Configure logging
import logging.handlers
import os
from datetime import datetime

# --- SLIDESHOW CONFIGURATION ---
IMAGES_PER_DIRECTORY = 40        # ← Change this to any number
TIME_IMAGE_EVERY_N = 10          # Show time image every N images
SLIDE_DURATION_SECONDS = 5       # Time between images
IMAGE_EXTENSIONS = ('.jpg', '.jpeg', '.png', '.gif')


# ---- 1. General log: WARNING+ only ----
GENERAL_LOG = os.path.expanduser('~/bin/slideshow.log')
general_handler = logging.handlers.TimedRotatingFileHandler(
    GENERAL_LOG, when='midnight', interval=1, backupCount=1, encoding='utf-8')
general_handler.setLevel(logging.WARNING)
general_handler.setFormatter(
    logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))

# ---- 2. Display log: ONLY image paths ----
DISPLAY_LOG = os.path.expanduser('~/bin/slideshow_display.log')
display_handler = logging.handlers.TimedRotatingFileHandler(
    DISPLAY_LOG, when='midnight', interval=1, backupCount=1, encoding='utf-8')
display_handler.setLevel(logging.INFO)
display_handler.setFormatter(
    logging.Formatter('%(asctime)s - %(message)s'))

# Dedicated logger for display events
display_logger = logging.getLogger('display')
display_logger.setLevel(logging.INFO)          # THIS WAS MISSING
display_logger.propagate = False
display_logger.addHandler(display_handler)

# TEST: Force a log entry
display_logger.info("=== DISPLAY LOG STARTED ===")


# ---- 3. Console + root logger (DEBUG+, no display) ----
stream_handler = logging.StreamHandler()
stream_handler.setLevel(logging.DEBUG)
stream_handler.setFormatter(
    logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))

root_logger = logging.getLogger()
root_logger.setLevel(logging.DEBUG)
root_logger.handlers.clear()
root_logger.addHandler(general_handler)
root_logger.addHandler(stream_handler)

# ---- 4. Helper: logs ONLY to slideshow_display.log ----
def log_image_display(image_path: str):
    display_logger.info(image_path)   # This now works



from http.server import SimpleHTTPRequestHandler

class SlideshowHTTPRequestHandler(SimpleHTTPRequestHandler):

    def do_GET(self):
        if self.path == '/slideshow':
            self.send_response(200)
            self.send_header('Content-type', 'text/html')
            self.end_headers()
            html_content = self.get_html_content()
            self.wfile.write(html_content.encode('utf-8'))
        elif self.path == '/current_image':
            self.send_response(200)
            self.send_header('Content-type', 'image/jpeg')
            self.end_headers()
            with open('/tmp/resized_image.jpg', 'rb') as file:
                self.wfile.write(file.read())
        elif self.path == '/favicon.ico':
            self.send_response(204)  # No Content
            self.end_headers()
        else:
            self.send_error(404, "File not found")

    def get_html_content(self):
        html_content = '''
        <!DOCTYPE html>
        <html lang="en">
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>Slideshow</title>
            <style>
                html, body {
                    margin: 0;
                    padding: 0;
                    width: 100%;
                    height: 100%;
                    background-color: #000;
                    overflow: hidden;
                }
                body {
                    display: flex;
                    justify-content: center;
                    align-items: center;
                }
                img {
                    width: 100vw;
                    height: 100vh;
                    object-fit: contain;
                    display: block;
                }
            </style>
        </head>
        <body>
            <img src="/current_image" alt="Slideshow Image"> 
            <script>
                setTimeout(() => location.reload(), 5000);
            </script>
        </body>
        </html>
        '''
        return html_content.strip()


def generate_slideshow_images(directories, exclude_dirs_set, exclude_images_set, time_interval=None):
    """
    Displays images from random directories with configurable limits.
    """
    # Use config value or passed argument
    duration = SLIDE_DURATION_SECONDS if time_interval is None else time_interval

    total_images_displayed = 0
    while True:
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
            


def generate_time_image():
    current_time = time.strftime("%I:%M").lstrip("0")
    logging.info(f"Generating time image: {current_time}")
    # 1920x1080 landscape canvas
    img = Image.new('RGB', (1920, 1080), color=(0, 0, 0))
    draw = ImageDraw.Draw(img)
    font_path = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
    try:
        font = ImageFont.truetype(font_path, 300)  # Scaled for 1080 height
    except IOError:
        font = ImageFont.load_default()
    # Use textbbox for accurate size (PIL 8.3+; fallback if needed)
    try:
        bbox = draw.textbbox((0, 0), current_time, font=font)
        text_width = bbox[2] - bbox[0]
        text_height = bbox[3] - bbox[1]
    except AttributeError:
        text_width, text_height = draw.textsize(current_time, font=font)
    text_x = (img.width - text_width) // 2
    text_y = (img.height - text_height) // 2
    draw.text((text_x, text_y), current_time, font=font, fill=(255, 255, 255))
    img.save('/tmp/resized_image.jpg')
    logging.info("Time image generated and saved to /tmp/resized_image.jpg")



def serve_image(image_path):
    try:
        logging.info(f"Serving image: {image_path}")
        img = Image.open(image_path)

        # Verify image loaded properly
        img.verify()  # Raises if corrupted
        img = Image.open(image_path)  # Re-open after verify()

        # Handle EXIF orientation
        try:
            for orientation in ExifTags.TAGS.keys():
                if ExifTags.TAGS[orientation] == 'Orientation':
                    break
            exif = img._getexif()
            if exif is not None:
                exif = dict(exif.items())
                orientation_value = exif.get(orientation, 1)
                if orientation_value == 3:
                    img = img.rotate(180, expand=True)
                elif orientation_value == 6:
                    img = img.rotate(270, expand=True)
                elif orientation_value == 8:
                    img = img.rotate(90, expand=True)
        except Exception as e:
            logging.warning(f"EXIF error for {image_path}: {e}")

        # Save full image
        img.save('/tmp/resized_image.jpg', 'JPEG', quality=95)
        logging.info(f"Full image saved: {image_path}")
        log_image_display(image_path)

    except Exception as e:
        logging.error(f"SKIPPING BAD IMAGE: {image_path} | Error: {e}")
        # Optional: Save a placeholder so browser doesn't hang
        placeholder = Image.new('RGB', (1920, 1080), color=(50, 0, 0))
        draw = ImageDraw.Draw(placeholder)
        draw.text((50, 50), f"SKIPPED: {os.path.basename(image_path)}", fill=(255,255,255))
        placeholder.save('/tmp/resized_image.jpg')
        log_image_display(f"[SKIPPED] {image_path}")



def run_server(port=8000):
    server_address = ('', port)
    httpd = HTTPServer(server_address, SlideshowHTTPRequestHandler)
    logging.info(f"Serving on port {port}")
    httpd.serve_forever()

if __name__ == "__main__":
    with open(os.path.expanduser('~/bin/slideshowDirectories.txt')) as f:
        directories = [line.strip().strip('"') for line in f.readlines()]

    # Load excluded directories from ~/bin/exclude_dirs.txt (one substring per line)
    exclude_dirs_set = set()
    exclude_dirs_file = os.path.expanduser('~/bin/exclude_dirs.txt')
    if os.path.exists(exclude_dirs_file):
        with open(exclude_dirs_file) as ef:
            exclude_dirs_set = set(line.strip() for line in ef if line.strip())
        logging.info(f"Loaded {len(exclude_dirs_set)} excluded dir substrings from {exclude_dirs_file}")
    else:
        logging.warning(f"Exclude dirs file not found: {exclude_dirs_file}. No directory exclusions applied.")

    # Filter directories
    directories = [d for d in directories if not any(ex in d for ex in exclude_dirs_set)]
    logging.info(f"Filtered to {len(directories)} directories after exclusions")

    # Load excluded images from ~/bin/exclude_images.txt (one full path per line)
    exclude_images_set = set()
    exclude_images_file = os.path.expanduser('~/bin/exclude_images.txt')
    if os.path.exists(exclude_images_file):
        with open(exclude_images_file) as ef:
            exclude_images_set = set(line.strip() for line in ef if line.strip())
        logging.info(f"Loaded {len(exclude_images_set)} excluded images from {exclude_images_file}")
    else:
        logging.warning(f"Exclude images file not found: {exclude_images_file}. No per-image exclusions applied.")

    threading.Thread(target=generate_slideshow_images, args=(directories, exclude_dirs_set, exclude_images_set, 5), daemon=True).start()
    run_server()

