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
log_filename = os.path.expanduser(f'~/bin/slideshowLogging_{datetime.now().strftime("%Y%m%d_%H%M%S")}.txt')
logger = logging.getLogger()
logger.setLevel(logging.DEBUG)

# File handler - logs WARNING and above
file_handler = logging.FileHandler(log_filename)
file_handler.setLevel(logging.WARNING)
file_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))

# Stream handler - logs DEBUG and above (everything)
stream_handler = logging.StreamHandler()
stream_handler.setLevel(logging.DEBUG)
stream_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))

# Add handlers to the logger
logger.addHandler(file_handler)
logger.addHandler(stream_handler)

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
                body {
                    display: flex;
                    justify-content: center;
                    align-items: center;
                    height: 100vh;
                    margin: 0;
                    background-color: #000;
                    color: #fff;
                    overflow: hidden;
                }
                img {
                    max-width: 100%;
                    max-height: 100%;
                    object-fit: cover;  /* Ensures full fill in browser too */
                }
            </style>
        </head>
        <body>
            <div>
                <img src="/current_image" alt="Slideshow Image">
            </div>
            <script>
                setTimeout(function() {
                    window.location.reload(1);
                }, 5000);
            </script>
        </body>
        </html>
        '''
        return html_content

def generate_slideshow_images(directories, exclude_dirs_set, exclude_images_set, time_interval):
    total_images_displayed = 0
    while True:
        directory = random.choice(directories)
        logging.info(f"Selected directory: {directory}")
        image_files = []
        if os.path.isdir(directory):
            for file in os.listdir(directory):
                if file.lower().endswith(('.jpg', '.jpeg', '.png', '.gif')):
                    image_path = os.path.join(directory, file)
                    if image_path not in exclude_images_set:
                        image_files.append(image_path)
        
        if not image_files:
            logging.warning(f"No valid image files found in directory: {directory}")
            continue

        random.shuffle(image_files)
        image_files = image_files[:20]

        for image_path in image_files:
            total_images_displayed += 1
            logging.info(f"Total images displayed: {total_images_displayed}")
            if total_images_displayed % 10 == 0:
                generate_time_image()
            else:
                serve_image(image_path)
            time.sleep(time_interval)

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

        # Handle EXIF orientation
        try:
            for orientation in ExifTags.TAGS.keys():
                if ExifTags.TAGS[orientation] == 'Orientation':
                    break
            exif = img._getexif()
            if exif is not None:
                exif = dict(exif.items())
                orientation_value = exif.get(orientation, 1)
                orientation_str = "landscape" if img.width >= img.height else "portrait"
                logging.info(f"Image orientation: {orientation_str}")
                if orientation_value == 3:
                    img = img.rotate(180, expand=True)
                    logging.info("Rotated image 180 degrees")
                elif orientation_value == 6:
                    img = img.rotate(270, expand=True)
                    logging.info("Rotated image 270 degrees")
                elif orientation_value == 8:
                    img = img.rotate(90, expand=True)
                    logging.info("Rotated image 90 degrees")
        except Exception as e:
            logging.warning(f"Error handling EXIF orientation for {image_path}: {e}")

        # Validate image dimensions
        width, height = img.size
        if width == 0 or height == 0:
            raise ValueError(f"Invalid image dimensions for {image_path}: width={width}, height={height}")

        # Crop to fill 1920x1080 exactly (no borders, preserves aspect by trimming edges)
        aspect_ratio = width / height
        canvas_width, canvas_height = 1920, 1080
        canvas_aspect = canvas_width / canvas_height

        if aspect_ratio > canvas_aspect:  # Image wider than canvas: crop sides
            new_height = canvas_height
            new_width = int(new_height * aspect_ratio)
            left = (new_width - canvas_width) // 2
            img = img.resize((new_width, new_height), Image.ANTIALIAS)
            img = img.crop((left, 0, left + canvas_width, new_height))
        else:  # Image taller: crop top/bottom
            new_width = canvas_width
            new_height = int(new_width / aspect_ratio)
            top = (new_height - canvas_height) // 2
            img = img.resize((new_width, new_height), Image.ANTIALIAS)
            img = img.crop((0, top, new_width, top + canvas_height))

        # Save as final 1920x1080 JPG (no padding canvas needed)
        img.save('/tmp/resized_image.jpg', 'JPEG', quality=95)  # High quality
        logging.info(f"Cropped/filled image saved to /tmp/resized_image.jpg (final: 1920x1080)")
    except Exception as e:
        logging.error(f"Error processing image {image_path}: {e}")
        return

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

