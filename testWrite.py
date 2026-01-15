#!/usr/bin/env python3
import http.server
import os
import sys
import time
from datetime import datetime

PORT = 8001
CONFIG_FILE = "slideshowDirectories.txt"

def get_ts():
    return datetime.now().strftime("%H:%M:%S")

# 1. SETUP & RAM LOAD
with open(CONFIG_FILE, 'r') as f:
    ROOT_PATH = f.readline().strip().replace('"', '').replace("'", "")

items = os.listdir(ROOT_PATH)
IMAGES = [f for f in items if f.lower().endswith(('.jpg', '.jpeg', '.png'))]
RAM_CACHE = [open(os.path.join(ROOT_PATH, i), 'rb').read() for i in IMAGES]

print(f"[{get_ts()}] RAM LOADED: {len(RAM_CACHE)} images ready.")

class SequentialServer(http.server.BaseHTTPRequestHandler):
    counter = 0  # Global counter to track "one by one"

    def do_GET(self):
        # Every time ANY request hits this server, give the next image
        data = RAM_CACHE[SequentialServer.counter % len(RAM_CACHE)]
        
        self.send_response(200)
        self.send_header("Content-type", "image/jpeg")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        
        print(f"[{get_ts()}] START: Sending Image #{SequentialServer.counter + 1}...")
        
        start = time.perf_counter()
        self.wfile.write(data)
        elapsed = (time.perf_counter() - start) * 1000
        
        mbps = (len(data) / 1024 / 1024) / (elapsed / 1000)
        print(f"[{get_ts()}] FINISHED: {mbps:.2f} MB/s")
        
        SequentialServer.counter += 1

httpd = http.server.HTTPServer(('0.0.0.0', PORT), SequentialServer)
print(f"[{get_ts()}] SERVER READY. Run the curl command from Florida now.")
httpd.serve_forever()
