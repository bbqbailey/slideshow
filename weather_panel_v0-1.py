#!/usr/bin/env python3
# weather_panel_v0-1.py
#
# Generate a weather dashboard PNG using OpenWeather and Pillow.
# Designed for 1920x1080 display, readable from ~30 feet.

import sys
import time
from datetime import datetime, timezone, timedelta

import requests
from PIL import Image, ImageDraw, ImageFont

# --------------------------------------------------------------------
# CONFIG
# --------------------------------------------------------------------

# Exact URL that you confirmed works via curl.
OPENWEATHER_URL = (
    "http://api.openweathermap.org/data/2.5/weather"
    "?lat=34.055667&lon=-84.231000&units=imperial"
    "&appid=96a0cc9aa818fd23c80c4ba5321c2194"
)

# Output image file
OUTPUT_PNG = "weather_panel.png"

# Canvas size
WIDTH = 1920
HEIGHT = 1080

# Colors
BG_COLOR = (10, 25, 60)       # dark blue
TEXT_COLOR = (240, 240, 240)  # off-white
ACCENT_COLOR = (120, 190, 255)

# Fonts – adjust paths if needed. DejaVu is usually present on Ubuntu.
def load_font(name: str, size: int) -> ImageFont.FreeTypeFont:
    candidates = [
        f"/usr/share/fonts/truetype/dejavu/{name}.ttf",
        f"/usr/share/fonts/truetype/{name}.ttf",
    ]
    for path in candidates:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    # Fallback
    return ImageFont.load_default()

FONT_TEMP   = load_font("DejaVuSans-Bold", 220)
FONT_LABEL  = load_font("DejaVuSans-Bold", 64)
FONT_VALUE  = load_font("DejaVuSans", 80)
FONT_SMALL  = load_font("DejaVuSans", 52)
FONT_TINY   = load_font("DejaVuSans", 36)

# --------------------------------------------------------------------
# FETCH & PARSE WEATHER
# --------------------------------------------------------------------

def fetch_current_weather():
    """Fetch current weather JSON from OpenWeather."""
    print(f"[INFO] Requesting: {OPENWEATHER_URL}")
    resp = requests.get(OPENWEATHER_URL, timeout=10)
    try:
        resp.raise_for_status()
    except requests.HTTPError as e:
        print(f"[ERR] HTTP error from OpenWeather: {e}", file=sys.stderr)
        raise

    data = resp.json()
    name = data.get("name", "Unknown")
    temp = data.get("main", {}).get("temp")
    print(f"[INFO] OpenWeather OK for {name}, temp={temp}")
    return data

def fmt_temp(t):
    if t is None:
        return "N/A"
    return f"{round(float(t))}°F"

def fmt_wind(speed, deg):
    if speed is None:
        return "N/A"
    s = round(float(speed))
    if deg is None:
        return f"{s} mph"
    d = round(float(deg))
    return f"{s} mph @ {d}°"

def fmt_sky(desc):
    if not desc:
        return "N/A"
    return desc.capitalize()

def fmt_time_from_unix(ts, tz_offset_sec):
    if ts is None:
        return "N/A"
    tz = timezone(timedelta(seconds=tz_offset_sec))
    dt = datetime.fromtimestamp(ts, tz=tz)
    return dt.strftime("%I:%M %p").lstrip("0")

def build_weather_summary(raw):
    """Convert OpenWeather JSON into simple dict of strings for display."""
    main = raw.get("main", {})
    wind = raw.get("wind", {})
    weather_list = raw.get("weather", [])
    sys_block = raw.get("sys", {})
    tz_offset = raw.get("timezone", 0)

    current_temp = main.get("temp")
    temp_min = main.get("temp_min")
    temp_max = main.get("temp_max")
    wind_speed = wind.get("speed")
    wind_deg = wind.get("deg")
    desc = weather_list[0].get("description") if weather_list else None

    sunrise_unix = sys_block.get("sunrise")
    sunset_unix = sys_block.get("sunset")

    sunrise_str = fmt_time_from_unix(sunrise_unix, tz_offset)
    sunset_str = fmt_time_from_unix(sunset_unix, tz_offset)

    summary = {
        # Top-line temp (now)
        "temp_now": fmt_temp(current_temp),

        # Today (left column)
        "today_hi": fmt_temp(temp_max),
        "today_lo": fmt_temp(temp_min),
        "today_wind": fmt_wind(wind_speed, wind_deg),

        # Tomorrow (right column) – placeholders for now
        "tomorrow_hi": "N/A",
        "tomorrow_lo": "N/A",
        "tomorrow_wind": "N/A",
        "tomorrow_conditions": "N/A",

        # Current conditions text (today)
        "current_conditions": fmt_sky(desc),

        # Sunrise / sunset
        "sunrise": sunrise_str,
        "sunset": sunset_str,

        "location": raw.get("name", "Unknown"),
    }

    return summary

# --------------------------------------------------------------------
# RENDERING
# --------------------------------------------------------------------

def draw_centered_text(draw, text, y, font, fill):
    w, h = draw.textsize(text, font=font)
    x = (WIDTH - w) // 2
    draw.text((x, y), text, font=font, fill=fill)

def render_weather_panel(summary):
    """Return a PIL.Image with the weather dashboard."""
    img = Image.new("RGB", (WIDTH, HEIGHT), BG_COLOR)
    draw = ImageDraw.Draw(img)

    margin = 80

    # Top: big temperature (moved up slightly)
    temp_text = summary["temp_now"]
    temp_y = 20
    draw_centered_text(draw, temp_text, temp_y, FONT_TEMP, TEXT_COLOR)

    # Start columns well below the temp
    col_y_start = temp_y + 260

    # Increase row height and keep label/value spacing uniform for both columns
    row_height = 190
    label_to_value_offset = 80

    left_x_label = margin
    right_x_label = WIDTH // 2 + margin // 2

    def draw_row(row_index, left_label=None, left_value=None,
                 right_label=None, right_value=None):
        base_y = col_y_start + row_index * row_height
        label_y = base_y
        value_y = base_y + label_to_value_offset

        if left_label:
            draw.text((left_x_label, label_y), left_label,
                      font=FONT_LABEL, fill=ACCENT_COLOR)
        if left_value:
            draw.text((left_x_label, value_y), left_value,
                      font=FONT_VALUE, fill=TEXT_COLOR)

        if right_label:
            draw.text((right_x_label, label_y), right_label,
                      font=FONT_LABEL, fill=ACCENT_COLOR)
        if right_value:
            draw.text((right_x_label, value_y), right_value,
                      font=FONT_VALUE, fill=TEXT_COLOR)

    # Row 0: Today vs Tomorrow (Hi/Lo)
    draw_row(
        0,
        left_label="Today",
        left_value=f'{summary["today_hi"]} / {summary["today_lo"]}',
        right_label="Tomorrow",
        right_value=f'{summary["tomorrow_hi"]} / {summary["tomorrow_lo"]}',
    )

    # Row 1: Wind Today vs Wind Tomorrow
    draw_row(
        1,
        left_label="Wind Today",
        left_value=summary["today_wind"],
        right_label="Wind Tomorrow",
        right_value=summary["tomorrow_wind"],
    )

    # Row 2: Current conditions (today) on left, Conditions Tomorrow on right
    draw_row(
        2,
        left_label="Conditions Today",
        left_value=summary["current_conditions"],
        right_label="Conditions Tomorrow",
        right_value=summary["tomorrow_conditions"],
    )

    # Bottom: Sunrise / Sunset centered
    sunrise = summary["sunrise"]
    sunset = summary["sunset"]
    bottom_text = f"Sunrise {sunrise}   |   Sunset {sunset}"
    w, h = draw.textsize(bottom_text, font=FONT_SMALL)
    bottom_y = HEIGHT - margin - h
    draw.text(((WIDTH - w) // 2, bottom_y), bottom_text,
              font=FONT_SMALL, fill=TEXT_COLOR)

    # Tiny timestamp in bottom-right
    ts = datetime.now().strftime("%Y-%m-%d %H:%M")
    ts_w, ts_h = draw.textsize(ts, font=FONT_TINY)
    draw.text((WIDTH - margin - ts_w, HEIGHT - margin - ts_h),
              ts, font=FONT_TINY, fill=(180, 180, 200))

    return img

# --------------------------------------------------------------------
# MAIN LOOP
# --------------------------------------------------------------------

def main():
    while True:
        try:
            raw = fetch_current_weather()
            summary = build_weather_summary(raw)
            img = render_weather_panel(summary)
            img.save(OUTPUT_PNG)
            print(f"[INFO] Updated {OUTPUT_PNG}")
        except Exception as e:
            print(f"[ERR] {e}", file=sys.stderr)
        # Sleep 10 minutes
        time.sleep(600)

if __name__ == "__main__":
    main()

