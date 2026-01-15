#!/usr/bin/env python3
import http.server
import os
import sys
import urllib.parse
import shutil
import time
from datetime import datetime

PORT = 8000
DIR_FILE = "slideshowDirectories.txt"

def get_ts():
    return datetime.now().strftime("%H:%M:%S")

# 1. LOAD DIRECTORY
try:
    with open(DIR_FILE, 'r') as f:
        START_DIR = f.readline().strip().replace('"', '').replace("'", "")
    if not os.path.isdir(START_DIR):
        print(f"[{get_ts()}] ERROR: {START_DIR} not found.")
        sys.exit(1)
except Exception as e:
    print(f"[{get_ts()}] CONFIG ERROR: {e}")
    sys.exit(1)

# 2. LIST IMAGES
ALL_IMAGES = [os.path.join(START_DIR, f) for f in os.listdir(START_DIR) 
              if f.lower().endswith(('.jpg', '.jpeg', '.png'))]
ALL_IMAGES.sort()
print(f"[{get_ts()}] FAST TEST: Found {len(ALL_IMAGES)} images in {START_DIR}")

class FastTestHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, format, *args): pass

    def do_GET(self):
        # ROOT PAGE
        if self.path == '/' or self.path.startswith('/slideshow'):
            self.send_response(200)
            self.send_header("Content-type", "text/html")
            self.send_header("Connection", "close")
            self.end_headers()
            
            html = f"""
            <html>
            <head>
                <script>
                    let idx = 0;
                    function next() {{
                        idx = (idx + 1) % {len(ALL_IMAGES)};
                        document.getElementById('s').src = '/_img?idx=' + idx + '&t=' + Date.now();
                    }}
                    setInterval(next, 10000);
                </script>
            </head>
            <body style="margin:0;background:#000;display:flex;justify-content:center;align-items:center;height:100vh;">
                <img id="s" src="/_img?idx=0" style="max-width:100%;max-height:100%;object-fit:contain;">
            </body>
            </html>
            """
            self.wfile.write(html.encode())
            self.wfile.flush()

        # IMAGE STREAM
        elif self.path.startswith('/_img'):
            params = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            idx = int(params.get('idx', [0])[0]) % len(ALL_IMAGES)
            file_path = ALL_IMAGES[idx]
            
            start_time = time.perf_counter()
            try:
                with open(file_path, 'rb') as f:
                    fs = os.fstat(f.fileno())
                    content_length = fs.st_size
                    
                    self.send_response(200)
                    self.send_header("Content-Type", "image/jpeg")
                    self.send_header("Content-Length", str(content_length))
                    self.send_header("Connection", "close")
                    self.end_headers()
                    
                    # Push data and force the socket to flush
                    shutil.copyfileobj(f, self.wfile)
                    self.wfile.flush()
                    
                    duration = time.perf_counter() - start_time
                    speed = (content_length / (1024*1024)) / duration if duration > 0 else 0
                    print(f"[{get_ts()}] PUSHED: {os.path.basename(file_path)} | {speed:.2f} MB/s")
            except Exception as e:
                print(f"[{get_ts()}] ERROR: {e}")

# 3. START
httpd = http.server.HTTPServer(('0.0.0.0', PORT), FastTestHandler)
print(f"[{get_ts()}] Aggressive Server on {PORT}...")
try:
    httpd.serve_forever()
except KeyboardInterrupt:
    print(f"\n[{get_ts()}] Shutdown.")
    sys.exit(0)

