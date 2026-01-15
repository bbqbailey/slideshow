#!/usr/bin/env python3
import os
import time
import sys
from datetime import datetime

CONFIG_FILE = "slideshowDirectories.txt"

def get_ts():
    return datetime.now().strftime("%H:%M:%S")

# 1. SETUP
try:
    with open(CONFIG_FILE, 'r') as f:
        ROOT_PATH = f.readline().strip().replace('"', '').replace("'", "")
except:
    print("Error: Could not read config.")
    sys.exit(1)

print(f"[{get_ts()}] --- HDD PERFORMANCE TEST ---")
print(f"[{get_ts()}] TARGET: {ROOT_PATH}")

# Get image list
items = os.listdir(ROOT_PATH)
images = [f for f in items if f.lower().endswith(('.jpg', '.jpeg', '.png'))]
if not images:
    print("No images found to test.")
    sys.exit(1)

print(f"[{get_ts()}] Testing with {len(images)} images.\n")

# --- TEST 1: NATIVE OS READ (SIMULATING super().do_GET()) ---
print(f"[{get_ts()}] STARTING TEST 1: Native System Read")
start_native = time.perf_counter()
total_bytes = 0

for img in images:
    try:
        full_p = os.path.join(ROOT_PATH, img)
        # Using the most efficient OS-level read
        with open(full_p, 'rb') as f:
            data = f.read()
            total_bytes += len(data)
    except: continue

end_native = time.perf_counter()
native_duration = end_native - start_native
native_mbps = (total_bytes / 1024 / 1024) / native_duration

print(f"[{get_ts()}] TEST 1 COMPLETE.")
print(f" >> Total Data: {total_bytes / 1024 / 1024:.2f} MB")
print(f" >> Total Time: {native_duration:.4f} seconds")
print(f" >> Native Speed: {native_mbps:.2f} MB/s\n")


# --- TEST 2: MANUAL BUFFERED READ (THE "SLOW" PYTHON METHOD) ---
print(f"[{get_ts()}] STARTING TEST 2: Manual Python Buffered Read")
start_manual = time.perf_counter()
total_bytes_manual = 0

for img in images:
    try:
        full_p = os.path.join(ROOT_PATH, img)
        with open(full_p, 'rb') as f:
            # This simulates a manual loop with a small buffer
            while True:
                chunk = f.read(64 * 1024) # 64KB chunks
                if not chunk: break
                total_bytes_manual += len(chunk)
    except: continue

end_manual = time.perf_counter()
manual_duration = end_manual - start_manual
manual_mbps = (total_bytes_manual / 1024 / 1024) / manual_duration

print(f"[{get_ts()}] TEST 2 COMPLETE.")
print(f" >> Total Data: {total_bytes_manual / 1024 / 1024:.2f} MB")
print(f" >> Total Time: {manual_duration:.4f} seconds")
print(f" >> Manual Speed: {manual_mbps:.2f} MB/s\n")

# --- SUMMARY ---
print("-" * 30)
print(f"RESULT: Native is {manual_duration / native_duration:.2f}x faster than Manual.")
if native_mbps < 10:
    print("WARNING: Hardware/Disk speed is under 10MB/s. This is likely the bottleneck.")
else:
    print("HARDWARE CHECK: Disk speed is sufficient. Bottleneck was code efficiency.")
print("-" * 30)

