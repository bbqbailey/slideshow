#!/usr/bin/env python3
# weather_panel_v0-2.py
#
# v0-2:
# - Fix One Call 3.0 usage (forecast no longer NA)
# - Use SAME key as working curl
# - Parse daily[0] as today, daily[1] as tomorrow

import os
import time
import logging
from datetime import datetime
from io import BytesIO

import requests
from PIL import Image, ImageDraw, ImageFont

# -------------------------------------------------------------------
# CONFIG
# -------------------------------------------------------------------
PROJECT_DIR = os.path.expanduser('~/myProjects/python/slideshow')
OUTPUT_PNG = os.path.join(PROJECT_DIR, 'weather_panel.png')

LAT = 34.055667
LON = -84.231000
UNITS = "imperial"

# Use the key you already confirmed with curl
OPENWEATHER_API_KEY = "96a0cc9aa818fd23c80c4ba5321c2194"

# If you *also* want env override, keep this:
env_key = os.getenv("OPENWEATHER_API_KEY")
if env_key:
    OPENWEATHER_API_KEY = env_key

CURRENT_URL = (
    "https://api.openweathermap.org/data/2.5/weather"
    f"?lat={LAT}&lon={LON}&units={UNITS}&appid={OPENWEATHER_API_KEY}"
)

ONECALL_URL = (
    "https://api.openweathermap.org/data/3.0/onecall"
    f"?lat={LAT}&lon={LON}&units={UNITS}"
    f"&exclude=minutely,hourly,alerts&appid={OPENWEATHER_API_KEY}"
)

IMG_WIDTH = 1920
IMG_HEIGHT = 1080

logging.basicConfig(
    filename=os.path.join(PROJECT_DIR, 'weather_panel.log'),
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

# -------------------------------------------------------------------
# DATA FETCHERS
# -------------------------------------------------------------------
def fetch_current_weather():
    """Return dict with current temp, wind, sunrise/sunset, and description."""
    try:
        logging.info(f"Fetching current weather: {CURRENT_URL}")
        resp = requests.get(CURRENT_URL, timeout=10)
        resp.raise_for_status()
        data = resp.json()

        temp_f = round(data["main"]["temp"])
        desc = data["weather"][0]["description"].title()
        wind_speed = data["wind"].get("speed", 0.0)
        wind_deg = data["wind"].get("deg", 0)

        sunrise = data["sys"]["sunrise"]
        sunset = data["sys"]["sunset"]

        return {
            "temp_f": temp_f,
            "conditions_now": desc,
            "wind_now_mph": wind_speed,
            "wind_now_deg": wind_deg,
            "sunrise": sunrise,
            "sunset": sunset,
        }
    except Exception as e:
        logging.error(f"Error fetching current weather: {e}")
        return {}


def fetch_forecast():
    """
    Use One Call 3.0:
      - daily[0] = today
      - daily[1] = tomorrow
    Returns dict with:
      hi_today, lo_today, hi_tomorrow, lo_tomorrow,
      conditions_today, conditions_tomorrow, wind_tomorrow_mph
    """
    try:
        logging.info(f"Fetching forecast (One Call 3.0): {ONECALL_URL}")
        resp = requests.get(ONECALL_URL, timeout=10)
        resp.raise_for_status()
        data = resp.json()

        daily = data.get("daily", [])
        if len(daily) < 2:
            logging.warning("One Call returned fewer than 2 daily entries")
            return {}

        today = daily[0]
        tomorrow = daily[1]

        hi_today = round(today["temp"]["max"])
        lo_today = round(today["temp"]["min"])
        hi_tomorrow = round(tomorrow["temp"]["max"])
        lo_tomorrow = round(tomorrow["temp"]["min"])

        cond_today = today["weather"][0]["description"].title()
        cond_tomorrow = tomorrow["weather"][0]["description"].title()

        wind_tomorrow_mph = tomorrow.get("wind_speed", 0.0)

        return {
            "hi_today": hi_today,
            "lo_today": lo_today,
            "hi_tomorrow": hi_tomorrow,
            "lo_tomorrow": lo_tomorrow,
            "conditions_today": cond_today,
            "conditions_tomorrow": cond_tomorrow,
            "wind_tomorrow_mph": wind_tomorrow_mph,
        }
    except Exception as e:
        logging.error(f"Error fetching One Call forecast: {e}")
        return {}

# -------------------------------------------------------------------
# DRAWING
# -------------------------------------------------------------------
def load_font(size, bold=False):
    """Try DejaVu Sans; fall back to default."""
    if bold:
        path = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
    else:
        path = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"

    try:
        return ImageFont.truetype(path, size)
    except Exception:
        return ImageFont.load_default()


def format_time(ts):
    """Convert unix timestamp to 'h:MM am/pm' local time."""
    dt = datetime.fromtimestamp(ts)
    return dt.strftime("%-I:%M %p")


def create_panel_image(current, forecast):
    img = Image.new("RGB", (IMG_WIDTH, IMG_HEIGHT), (15, 20, 30))
    draw = ImageDraw.Draw(img)

    font_temp = load_font(200, bold=True)
    font_label = load_font(30, bold=True)
    font_value = load_font(90, bold=True)
    font_small = load_font(30, bold=False)

    # ------------------ TOP: TEMPERATURE ------------------
    temp_text = f"{current.get('temp_f', 'NA')}°"
    bbox = draw.textbbox((0, 0), temp_text, font=font_temp)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]
    temp_x = (IMG_WIDTH - tw) // 2 - 100
    temp_y = 50
    draw.text((temp_x, temp_y), temp_text, font=font_temp, fill=(255, 255, 255))

    # ------------------ COLUMNS ------------------
    left_x = 50
    right_x = IMG_WIDTH // 2 + 200

    # vertical start just under the temp
    col_start_y = temp_y + th + 100 

    label_spacing = 5   # space between label and its value
    block_spacing = 20   # space between value and next label

    # Helper
    def draw_label_and_value(label, value, x, y):
        draw.text((x, y), label, font=font_label, fill=(200, 200, 240))
        y += font_label.size + label_spacing
        draw.text((x, y), value, font=font_value, fill=(255, 255, 255))
        y += font_value.size + block_spacing
        return y

    # LEFT COLUMN: Today
    y_left = col_start_y
    hi_today = forecast.get("hi_today", "NA")
    lo_today = forecast.get("lo_today", "NA")
    cond_today = forecast.get("conditions_today", "NA")
    wind_now = current.get("wind_now_mph", None)
    wind_now_deg = current.get("wind_now_deg", None)

    # Today's High / Low
    y_left = draw_label_and_value("High Today", f"{hi_today}°", left_x, y_left)
    y_left = draw_label_and_value("Low Today", f"{lo_today}°", left_x, y_left)

    # Conditions Today
    y_left = draw_label_and_value("Conditions Today", cond_today, left_x, y_left)

    # Wind Now
    if wind_now is not None:
        wind_now_text = f"{wind_now:.0f} mph"
        if wind_now_deg is not None:
            wind_now_text += f" @ {int(wind_now_deg)}°"
    else:
        wind_now_text = "NA"
    y_left = draw_label_and_value("Wind Now", wind_now_text, left_x, y_left)

    # RIGHT COLUMN: Tomorrow
    y_right = col_start_y
    hi_tomorrow = forecast.get("hi_tomorrow", "NA")
    lo_tomorrow = forecast.get("lo_tomorrow", "NA")
    cond_tomorrow = forecast.get("conditions_tomorrow", "NA")
    wind_tomorrow = forecast.get("wind_tomorrow_mph", None)

    y_right = draw_label_and_value("High Tomorrow", f"{hi_tomorrow}°", right_x, y_right)
    y_right = draw_label_and_value("Low Tomorrow", f"{lo_tomorrow}°", right_x, y_right)

    # Conditions Tomorrow
    y_right = draw_label_and_value("Conditions Tomorrow", cond_tomorrow, right_x, y_right)

    # Wind Tomorrow
    if wind_tomorrow is not None:
        wind_tomorrow_text = f"{wind_tomorrow:.0f} mph"
    else:
        wind_tomorrow_text = "NA"
    y_right = draw_label_and_value("Wind Tomorrow", wind_tomorrow_text, right_x, y_right)

    # ------------------ BOTTOM: SUNRISE / SUNSET ------------------
    sunrise_ts = current.get("sunrise")
    sunset_ts = current.get("sunset")

    if sunrise_ts and sunset_ts:
        sunrise_str = format_time(sunrise_ts)
        sunset_str = format_time(sunset_ts)
        bottom_text = f"Sunrise: {sunrise_str}    Sunset: {sunset_str}"
    else:
        bottom_text = "Sunrise: NA    Sunset: NA"

    bbox = draw.textbbox((0, 0), bottom_text, font=font_small)
    bw = bbox[2] - bbox[0]
    bh = bbox[3] - bbox[1]
    bottom_x = (IMG_WIDTH - bw) // 2
    bottom_y = IMG_HEIGHT - bh - 40
    draw.text((bottom_x, bottom_y), bottom_text, font=font_small, fill=(220, 220, 220))

    buf = BytesIO()
    img.save(buf, format="PNG")
    with open(OUTPUT_PNG, "wb") as f:
        f.write(buf.getvalue())

    logging.info(f"Weather panel image updated: {OUTPUT_PNG}")


# -------------------------------------------------------------------
# MAIN LOOP
# -------------------------------------------------------------------
def main():
    while True:
        current = fetch_current_weather()
        forecast = fetch_forecast()

        # If forecast fetch failed, we'll still draw with NA fields
        create_panel_image(current, forecast)

        # sleep 10 minutes
        time.sleep(600)


if __name__ == "__main__":
    main()

