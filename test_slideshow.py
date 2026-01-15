#!/usr/bin/env python3
import os
import sys
import ssl
from http.server import HTTPServer, SimpleHTTPRequestHandler
from socketserver import ThreadingMixIn
from pathlib import Path
from urllib.parse import urlparse

DISPLAY_SECONDS = 5
IMAGE_EXTS = (".jpg", ".jpeg")

# Hardcoded directory to serve images from
IMAGE_DIR = Path("/media/Entertainment/Photos/PictureAlbums/Scans2/").expanduser().resolve()

# Check if the directory exists
if not IMAGE_DIR.is_dir():
    print(f"Not a directory: {IMAGE_DIR}")
    sys.exit(1)

# List of images (only JPG and JPEG)
IMAGES = sorted(
    [f for f in os.listdir(IMAGE_DIR) if f.lower().endswith(IMAGE_EXTS)]
)

if not IMAGES:
    print("No JPG images found")
    sys.exit(1)


class Handler(SimpleHTTPRequestHandler):
    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/slideshow":
            self.serve_slideshow()
            return

        # Directly serve the image from the hardcoded directory
        image_name = parsed.path.lstrip("/")
        if image_name in IMAGES:
            self.serve_image(image_name)
            return

        self.send_error(404)

    def serve_slideshow(self):
        images = IMAGES  # Dynamically loaded images
        img_list = ",".join(f"'{name}'" for name in images)

        html = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>Test Slideshow</title>
<style>
html, body {{
    margin: 0;
    width: 100%;
    height: 100%;
    background: black;
}}
img {{
    width: 100%;
    height: 100%;
    object-fit: contain;
}}
</style>
</head>
<body>
<img id="img">

<script>
const images = [{img_list}];
let idx = 0;
const img = document.getElementById("img");

function showNext() {{
    if (idx >= images.length) {{
        return; // EXIT — stop at end
    }}
    // No '/images/' path — use the image file name directly
    img.src = "/" + images[idx] + "?t=" + Date.now();
    idx++;
    setTimeout(showNext, {DISPLAY_SECONDS * 1000});
}}

showNext();
</script>
</body>
</html>
"""

        body = html.encode('utf-8')
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        self.end_headers()
        self.wfile.write(body)

    def serve_image(self, image_name):
        # Directly serve the image from the hardcoded directory
        path = IMAGE_DIR / image_name
        if not path.exists() or not path.is_file():
            self.send_error(404)
            return

        with open(path, "rb") as f:
            data = f.read()

        self.send_response(200)
        self.send_header("Content-Type", "image/jpeg")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        self.end_headers()
        self.wfile.write(data)


class ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True


httpd = ThreadedHTTPServer(("", 8000), Handler)

# Enable SSL with existing certificates
context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
context.load_cert_chain(certfile="/home/superben/myProjects/python/slideshow/certs/hottub.crt", keyfile="/home/superben/myProjects/python/slideshow/certs/hottub.key")

httpd.socket = context.wrap_socket(httpd.socket, server_side=True)

print("Serving test slideshow at https://<funnel-host>/slideshow")
httpd.serve_forever()

