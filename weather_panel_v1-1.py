#!/usr/bin/env python3
# weather_panel_v1-1.py
#
# v1-1:
# - Reduce font size for "Conditions Today" and "Conditions Tomorrow" values only
# - No other layout or logic changes
#
# v1-0:
# - Keep v0-3 behavior: generate weather_panel.png every 10 minutes
#   using One Call 3.0 (current + today + tomorrow).
# - Add embedded HTTP server (ThreadingHTTPServer) that serves:
#     * /          -> single-page HTML with labeled sections
#     * /weather   -> same as "/"
#     * /weather_panel.png -> the current PNG image
# - HTML page shows:
#     * Current conditions (temp, feels-like, humidity, wind, etc.)
#     * Next 60 minutes (minutely precip, if available)
#     * Next 24 hours (hourly snapshot)
#     * Next 8 days (daily forecast)
#     * Active alerts (if any)
#
# NOTE:
# - PNG generation layout and logic are preserved from v0-3.
# - We now request the full One Call 3.0 payload (no "exclude="),
#   so minutely/hourly/alerts are available for the HTML view.
# - The One Call API is called in a background thread every 10 minutes.
#   The HTTP server serves the most recent data.

import ssl
import os
import time
import logging
import threading
from datetime import datetime
from io import BytesIO
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import html

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

# Base key (the one you confirmed with curl)
OPENWEATHER_API_KEY = "96a0cc9aa818fd23c80c4ba5321c2194"

# Optional override from environment
env_key = os.getenv("OPENWEATHER_API_KEY")
if env_key:
    OPENWEATHER_API_KEY = env_key

# Request FULL One Call 3.0 payload (no exclude=...)
ONECALL_URL = (
    "https://api.openweathermap.org/data/3.0/onecall"
    f"?lat={LAT}&lon={LON}&units={UNITS}"
    f"&appid={OPENWEATHER_API_KEY}"
)

IMG_WIDTH = 1920
IMG_HEIGHT = 1080

# HTTP server config
HTTP_HOST = "0.0.0.0"
HTTP_PORT = 8050

logging.basicConfig(
    filename=os.path.join(PROJECT_DIR, 'weather_panel.log'),
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

# -------------------------------------------------------------------
# SHARED STATE (for HTTP + updater)
# -------------------------------------------------------------------
WEATHER_LOCK = threading.Lock()
LATEST_SUMMARY = None   # dict with temp_f, hi_today, lo_today, etc.
LATEST_RAW = None       # full One Call JSON
LAST_UPDATED = None     # datetime of last successful fetch


# -------------------------------------------------------------------
# HELPERS
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
    """Convert unix timestamp to 'h:MM AM/PM' local time."""
    dt = datetime.fromtimestamp(ts)
    return dt.strftime("%-I:%M %p")


def format_date(ts):
    """Convert unix timestamp to 'Weekday MM/DD' local date."""
    dt = datetime.fromtimestamp(ts)
    return dt.strftime("%a %m/%d")


def safe_get(d, key, default=None):
    return d.get(key, default) if isinstance(d, dict) else default


# -------------------------------------------------------------------
# SUMMARY EXTRACTOR (from raw One Call JSON)
# -------------------------------------------------------------------
def extract_weather_summary_from_onecall(data):
    """
    Build the same summary dict that v0-3 used for the PNG.
    This does NOT fetch anything; it only parses the provided data.
    """
    out = {
        "temp_f": "NA",
        "wind_now_mph": None,
        "wind_now_deg": None,
        "sunrise": None,
        "sunset": None,
        "hi_today": "NA",
        "lo_today": "NA",
        "hi_tomorrow": "NA",
        "lo_tomorrow": "NA",
        "conditions_today": "NA",
        "conditions_tomorrow": "NA",
        "wind_tomorrow_mph": None,
    }

    if not isinstance(data, dict):
        logging.warning("extract_weather_summary_from_onecall: data is not a dict")
        return out

    daily = data.get("daily", [])
    logging.info(f"DAILY LENGTH = {len(daily)}")

    # ---------------- current ----------------
    current = data.get("current", {})
    if "temp" in current:
        try:
            out["temp_f"] = round(current["temp"])
        except Exception as e:
            logging.warning(f"Error rounding current temp: {e}")

    if "wind_speed" in current:
        out["wind_now_mph"] = current.get("wind_speed")
    if "wind_deg" in current:
        out["wind_now_deg"] = current.get("wind_deg")

    # sunrise / sunset: prefer current, fall back to daily[0]
    sunrise = current.get("sunrise")
    sunset = current.get("sunset")

    if sunrise is None and len(daily) >= 1 and "sunrise" in daily[0]:
        sunrise = daily[0]["sunrise"]
    if sunset is None and len(daily) >= 1 and "sunset" in daily[0]:
        sunset = daily[0]["sunset"]

    out["sunrise"] = sunrise
    out["sunset"] = sunset

    # ---------------- daily[0] (today) + daily[1] (tomorrow) ----------------
    if len(daily) >= 1:
        today = daily[0]
        try:
            hi_today = round(today["temp"]["max"])
            lo_today = round(today["temp"]["min"])
            out["hi_today"] = hi_today
            out["lo_today"] = lo_today
            logging.info(f"DAILY[0] TODAY hi={hi_today}, lo={lo_today}")
        except Exception as e:
            logging.warning(f"Error extracting today hi/lo: {e}")

        try:
            cond_today = today["weather"][0]["description"].title()
            out["conditions_today"] = cond_today
        except Exception as e:
            logging.warning(f"Error extracting today conditions: {e}")

    if len(daily) >= 2:
        tomorrow = daily[1]
        try:
            hi_tomorrow = round(tomorrow["temp"]["max"])
            lo_tomorrow = round(tomorrow["temp"]["min"])
            out["hi_tomorrow"] = hi_tomorrow
            out["lo_tomorrow"] = lo_tomorrow
            logging.info(f"DAILY[1] TOMORROW hi={hi_tomorrow}, lo={lo_tomorrow}")
        except Exception as e:
            logging.warning(f"Error extracting tomorrow hi/lo: {e}")

        try:
            cond_tomorrow = tomorrow["weather"][0]["description"].title()
            out["conditions_tomorrow"] = cond_tomorrow
        except Exception as e:
            logging.warning(f"Error extracting tomorrow conditions: {e}")

        if "wind_speed" in tomorrow:
            out["wind_tomorrow_mph"] = tomorrow.get("wind_speed")

    logging.info(f"SUMMARY OUT = {out}")
    return out


# -------------------------------------------------------------------
# PNG DRAWING (unchanged layout from v0-3)
# -------------------------------------------------------------------
def create_panel_image(weather):
    """
    weather: dict from extract_weather_summary_from_onecall()
    Layout matches your v0-2 / v0-3 (fonts, positions, spacings).
    """
    img = Image.new("RGB", (IMG_WIDTH, IMG_HEIGHT), (15, 20, 30))
    draw = ImageDraw.Draw(img)

    # Fonts kept as in v0-3
    font_temp = load_font(200, bold=True)
    font_label = load_font(30, bold=True)
    font_value = load_font(100, bold=True)
    font_conditions = load_font(60, bold=True)   # NEW: smaller font
    font_small = load_font(30, bold=False)

    # ------------------ TOP: TEMPERATURE ------------------
    temp_text = f"{weather.get('temp_f', 'NA')}°"
    bbox = draw.textbbox((0, 0), temp_text, font=font_temp)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]
    temp_x = (IMG_WIDTH - tw) // 2 - 100
    temp_y = 50
    draw.text((temp_x, temp_y), temp_text, font=font_temp, fill=(255, 255, 255))

    # ------------------ COLUMNS ------------------
    left_x = 180
    right_x = IMG_WIDTH // 2 + 200

    # vertical start just under the temp
    col_start_y = temp_y + th + 100

    label_spacing = 5    # space between label and its value
    block_spacing = 20   # space between value and next label

    # Helper
    def draw_label_and_value(label, value, x, y):
        draw.text((x, y), label, font=font_label, fill=(200, 200, 240))
        y += font_label.size + label_spacing
        draw.text((x, y), value, font=font_value, fill=(255, 255, 255))
        y += font_value.size + block_spacing
        return y

    def draw_label_and_conditions(label, value, x, y):
        draw.text((x, y), label, font=font_label, fill=(200, 200, 240))
        y += font_label.size + label_spacing
        draw.text((x, y), value, font=font_conditions, fill=(255, 255, 255))
        y += font_conditions.size + block_spacing
        return y


    # LEFT COLUMN: Today
    y_left = col_start_y
    hi_today = weather.get("hi_today", "NA")
    lo_today = weather.get("lo_today", "NA")
    cond_today = weather.get("conditions_today", "NA")
    wind_now = weather.get("wind_now_mph", None)
    wind_now_deg = weather.get("wind_now_deg", None)

    # Today's High / Low
    y_left = draw_label_and_value("High Today", f"{hi_today}°", left_x, y_left)
    y_left = draw_label_and_value("Low Today", f"{lo_today}°", left_x, y_left)

    # Conditions Today
    y_left = draw_label_and_conditions("Conditions Today", cond_today, left_x, y_left)

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
    hi_tomorrow = weather.get("hi_tomorrow", "NA")
    lo_tomorrow = weather.get("lo_tomorrow", "NA")
    cond_tomorrow = weather.get("conditions_tomorrow", "NA")
    wind_tomorrow = weather.get("wind_tomorrow_mph", None)

    y_right = draw_label_and_value("High Tomorrow", f"{hi_tomorrow}°", right_x, y_right)
    y_right = draw_label_and_value("Low Tomorrow", f"{lo_tomorrow}°", right_x, y_right)

    # Conditions Tomorrow
    y_right = draw_label_and_conditions("Conditions Tomorrow", cond_tomorrow, right_x, y_right)

    # Wind Tomorrow
    if wind_tomorrow is not None:
        wind_tomorrow_text = f"{wind_tomorrow:.0f} mph"
    else:
        wind_tomorrow_text = "NA"
    y_right = draw_label_and_value("Wind Tomorrow", wind_tomorrow_text, right_x, y_right)

    # ------------------ BOTTOM: SUNRISE / SUNSET ------------------
    sunrise_ts = weather.get("sunrise")
    sunset_ts = weather.get("sunset")

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
# WEATHER UPDATE LOOP
# -------------------------------------------------------------------
def update_weather_once():
    """Fetch One Call data, update summary, PNG, and shared state."""
    global LATEST_SUMMARY, LATEST_RAW, LAST_UPDATED

    try:
        logging.info(f"Fetching One Call 3.0 data: {ONECALL_URL}")
        resp = requests.get(ONECALL_URL, timeout=10)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        logging.error(f"Error fetching One Call 3.0 data: {e}")
        return

    summary = extract_weather_summary_from_onecall(data)
    logging.info(f"SUMMARY USED FOR PNG = {summary}")

    # Update PNG (same behavior as v0-3)
    try:
        create_panel_image(summary)
    except Exception as e:
        logging.error(f"Error creating weather panel image: {e}")

    # Update shared state for HTTP server
    with WEATHER_LOCK:
        LATEST_SUMMARY = summary
        LATEST_RAW = data
        LAST_UPDATED = datetime.now()

    logging.info("Weather data and shared state updated.")


def weather_updater_loop():
    """Background thread: refresh weather every 10 minutes."""
    while True:
        update_weather_once()
        time.sleep(600)  # 10 minutes


# -------------------------------------------------------------------
# HTML PAGE BUILDER
# -------------------------------------------------------------------
def build_html_page(summary, raw_data, last_updated):
    """Build a single-page HTML view of current, minutely, hourly, daily, alerts."""
    title = "Local Weather Panel"

    # Pre-extract some blocks
    current = safe_get(raw_data, "current", {}) if raw_data else {}
    minutely = raw_data.get("minutely", []) if isinstance(raw_data, dict) else []
    hourly = raw_data.get("hourly", []) if isinstance(raw_data, dict) else []
    daily = raw_data.get("daily", []) if isinstance(raw_data, dict) else []
    alerts = raw_data.get("alerts", []) if isinstance(raw_data, dict) else []

    # Basic current fields
    temp_now = summary.get("temp_f", "NA") if summary else "NA"
    hi_today = summary.get("hi_today", "NA") if summary else "NA"
    lo_today = summary.get("lo_today", "NA") if summary else "NA"
    cond_today = summary.get("conditions_today", "NA") if summary else "NA"

    feels_like = safe_get(current, "feels_like", "NA")
    humidity = safe_get(current, "humidity", "NA")
    pressure = safe_get(current, "pressure", "NA")
    dew_point = safe_get(current, "dew_point", "NA")
    uvi = safe_get(current, "uvi", "NA")
    visibility = safe_get(current, "visibility", "NA")
    clouds = safe_get(current, "clouds", "NA")

    wind_speed = safe_get(current, "wind_speed", None)
    wind_deg = safe_get(current, "wind_deg", None)
    wind_gust = safe_get(current, "wind_gust", None)

    if isinstance(last_updated, datetime):
        updated_str = last_updated.strftime("%Y-%m-%d %H:%M:%S")
    else:
        updated_str = "N/A"

    # Helper to escape text
    def esc(x):
        return html.escape(str(x)) if x is not None else ""

    # Build HTML
    lines = []
    lines.append("<!DOCTYPE html>")
    lines.append("<html lang='en'>")
    lines.append("<head>")
    lines.append("<meta charset='utf-8'>")
    lines.append(f"<title>{esc(title)}</title>")
    lines.append("""
<style>
body {
    background-color: #10141f;
    color: #e5e7eb;
    font-family: Arial, sans-serif;
    margin: 0;
    padding: 20px;
}
h1, h2, h3 {
    color: #f9fafb;
}
a {
    color: #93c5fd;
    text-decoration: none;
}
a:hover {
    text-decoration: underline;
}
.navbar {
    margin-bottom: 20px;
}
.navbar a {
    margin-right: 15px;
}
.section {
    margin-bottom: 40px;
    padding: 15px;
    border-radius: 8px;
    background-color: #111827;
    border: 1px solid #1f2937;
}
table {
    border-collapse: collapse;
    width: 100%;
    font-size: 0.9rem;
}
th, td {
    border-bottom: 1px solid #1f2937;
    padding: 4px 6px;
    text-align: left;
}
th {
    background-color: #1f2937;
}
.small {
    font-size: 0.85rem;
    color: #9ca3af;
}
img {
    max-width: 100%;
    height: auto;
    border-radius: 8px;
    border: 1px solid #1f2937;
}
.button-bar {
    margin-top: 10px;
}
.button-bar a {
    display: inline-block;
    padding: 4px 8px;
    margin-right: 8px;
    border-radius: 4px;
    background-color: #1f2937;
    color: #e5e7eb;
    font-size: 0.85rem;
}
.button-bar a:hover {
    background-color: #374151;
}
</style>
""")
    lines.append("</head>")
    lines.append("<body>")

    # NAVBAR
    lines.append("<div class='navbar'>")
    lines.append("<strong>Sections:</strong> ")
    lines.append("<a href='#overview'>Overview</a>")
    lines.append("<a href='#current'>Current</</a>")
    lines.append("<a href='#minutely'>Next Hour</a>")
    lines.append("<a href='#hourly'>Hourly</a>")
    lines.append("<a href='#daily'>Daily</a>")
    lines.append("<a href='#alerts'>Alerts</a>")
    lines.append("</div>")

    # OVERVIEW SECTION
    lines.append("<div class='section' id='overview'>")
    lines.append("<h1>Local Weather Panel</h1>")
    lines.append(f"<p class='small'>Location: lat {LAT}, lon {LON}, units={esc(UNITS)}</p>")
    lines.append(f"<p class='small'>Last updated: {esc(updated_str)}</p>")
    # Show PNG if it exists
    if os.path.exists(OUTPUT_PNG):
        lines.append("<h3>Overview Panel (PNG)</h3>")
        ts = int(last_updated.timestamp()) if isinstance(last_updated, datetime) else int(time.time())
        lines.append(f"<p><img src='/weather_panel.png?ts={ts}' alt='Weather panel image'></p>")
    else:
        lines.append("<p class='small'>weather_panel.png not generated yet.</p>")
    lines.append("<div class='button-bar'>")
    lines.append("<a href='#current'>Go to Current</a>")
    lines.append("<a href='#hourly'>Go to Hourly</a>")
    lines.append("</div>")
    lines.append("</div>")

    # CURRENT SECTION
    lines.append("<div class='section' id='current'>")
    lines.append("<h2>Current Conditions</h2>")
    if summary is None or raw_data is None:
        lines.append("<p>Weather data not yet available.</p>")
    else:
        lines.append("<table>")
        lines.append("<tr><th>Label</th><th>Value</th></tr>")
        lines.append(f"<tr><td>Temperature</td><td>{esc(temp_now)} °F</td></tr>")
        lines.append(f"<tr><td>Feels Like</td><td>{esc(feels_like)} °F</td></tr>")
        lines.append(f"<tr><td>Today&apos;s High</td><td>{esc(hi_today)} °F</td></tr>")
        lines.append(f"<tr><td>Today&apos;s Low</td><td>{esc(lo_today)} °F</td></tr>")
        lines.append(f"<tr><td>Conditions Today</td><td>{esc(cond_today)}</td></tr>")
        lines.append(f"<tr><td>Humidity</td><td>{esc(humidity)} %</td></tr>")
        lines.append(f"<tr><td>Pressure</td><td>{esc(pressure)} hPa</td></tr>")
        lines.append(f"<tr><td>Dew Point</td><td>{esc(dew_point)} °F</td></tr>")
        lines.append(f"<tr><td>UV Index</td><td>{esc(uvi)}</td></tr>")
        lines.append(f"<tr><td>Cloud Cover</td><td>{esc(clouds)} %</td></tr>")
        lines.append(f"<tr><td>Visibility</td><td>{esc(visibility)} m</td></tr>")

        # Wind details
        wind_pieces = []
        if wind_speed is not None:
            wind_pieces.append(f"{wind_speed:.0f} mph")
        if wind_deg is not None:
            wind_pieces.append(f"{int(wind_deg)}°")
        if wind_gust is not None:
            wind_pieces.append(f"gust {wind_gust:.0f} mph")
        wind_text = " / ".join(wind_pieces) if wind_pieces else "NA"
        lines.append(f"<tr><td>Wind</td><td>{esc(wind_text)}</td></tr>")

        # Sunrise / Sunset
        sunrise_ts = summary.get("sunrise")
        sunset_ts = summary.get("sunset")
        if sunrise_ts and sunset_ts:
            sunrise_str = format_time(sunrise_ts)
            sunset_str = format_time(sunset_ts)
        else:
            sunrise_str = "NA"
            sunset_str = "NA"
        lines.append(f"<tr><td>Sunrise</td><td>{esc(sunrise_str)}</td></tr>")
        lines.append(f"<tr><td>Sunset</td><td>{esc(sunset_str)}</td></tr>")

        lines.append("</table>")
    lines.append("<div class='button-bar'>")
    lines.append("<a href='#overview'>Back to Top</a>")
    lines.append("<a href='#minutely'>Next: Next Hour</a>")
    lines.append("</div>")
    lines.append("</div>")

    # MINUTELY SECTION
    lines.append("<div class='section' id='minutely'>")
    lines.append("<h2>Next 60 Minutes (Minutely Precipitation)</h2>")
    if not minutely:
        lines.append("<p>No minutely data available.</p>")
    else:
        lines.append("<table>")
        lines.append("<tr><th>Time</th><th>Precipitation (mm)</th></tr>")
        for entry in minutely[:20]:
            dt_ts = entry.get("dt")
            precip = entry.get("precipitation", 0)
            t_str = format_time(dt_ts) if dt_ts else "N/A"
            lines.append(f"<tr><td>{esc(t_str)}</td><td>{esc(precip)}</td></tr>")
        lines.append("</table>")
        if len(minutely) > 20:
            lines.append(f"<p class='small'>...and {len(minutely) - 20} more minutes not shown.</p>")
    lines.append("<div class='button-bar'>")
    lines.append("<a href='#current'>Previous: Current</a>")
    lines.append("<a href='#hourly'>Next: Hourly</a>")
    lines.append("</div>")
    lines.append("</div>")

    # HOURLY SECTION
    lines.append("<div class='section' id='hourly'>")
    lines.append("<h2>Next 24 Hours (Hourly)</h2>")
    if not hourly:
        lines.append("<p>No hourly data available.</p>")
    else:
        lines.append("<table>")
        lines.append(
            "<tr>"
            "<th>Time</th>"
            "<th>Temp (°F)</th>"
            "<th>Feels (°F)</th>"
            "<th>Conditions</th>"
            "<th>POP (%)</th>"
            "<th>Rain (mm)</th>"
            "<th>Wind (mph)</th>"
            "</tr>"
        )
        for entry in hourly[:24]:
            dt_ts = entry.get("dt")
            t_str = format_time(dt_ts) if dt_ts else "N/A"
            temp = entry.get("temp", "NA")
            feels = entry.get("feels_like", "NA")
            pop = entry.get("pop", 0)
            pop_pct = int(pop * 100)
            rain_mm = 0
            rain = entry.get("rain")
            if isinstance(rain, dict):
                rain_mm = rain.get("1h", 0)
            wind_s = entry.get("wind_speed", None)
            wind_d = entry.get("wind_deg", None)
            wind_parts = []
            if wind_s is not None:
                wind_parts.append(f"{wind_s:.0f} mph")
            if wind_d is not None:
                wind_parts.append(f"{int(wind_d)}°")
            wind_txt = " / ".join(wind_parts) if wind_parts else "NA"
            weather_arr = entry.get("weather") or []
            if weather_arr:
                cond = weather_arr[0].get("description", "NA").title()
            else:
                cond = "NA"
            lines.append(
                "<tr>"
                f"<td>{esc(t_str)}</td>"
                f"<td>{esc(temp)}</td>"
                f"<td>{esc(feels)}</td>"
                f"<td>{esc(cond)}</td>"
                f"<td>{esc(pop_pct)}</td>"
                f"<td>{esc(rain_mm)}</td>"
                f"<td>{esc(wind_txt)}</td>"
                "</tr>"
            )
        lines.append("</table>")
        if len(hourly) > 24:
            lines.append(f"<p class='small'>...and {len(hourly) - 24} more hours not shown.</p>")
    lines.append("<div class='button-bar'>")
    lines.append("<a href='#minutely'>Previous: Next Hour</a>")
    lines.append("<a href='#daily'>Next: Daily</a>")
    lines.append("</div>")
    lines.append("</div>")

    # DAILY SECTION
    lines.append("<div class='section' id='daily'>")
    lines.append("<h2>Next 8 Days (Daily)</h2>")
    if not daily:
        lines.append("<p>No daily data available.</p>")
    else:
        lines.append("<table>")
        lines.append(
            "<tr>"
            "<th>Day</th>"
            "<th>High / Low (°F)</th>"
            "<th>Summary</th>"
            "<th>POP (%)</th>"
            "<th>Rain (mm)</th>"
            "<th>Snow (mm)</th>"
            "<th>Wind (mph)</th>"
            "<th>UV</th>"
            "</tr>"
        )
        for entry in daily[:8]:
            dt_ts = entry.get("dt")
            day_str = format_date(dt_ts) if dt_ts else "N/A"
            temp_block = entry.get("temp", {})
            hi = temp_block.get("max", "NA")
            lo = temp_block.get("min", "NA")

            summary_text = entry.get("summary")
            if not summary_text:
                weather_arr = entry.get("weather") or []
                if weather_arr:
                    summary_text = weather_arr[0].get("description", "NA").title()
                else:
                    summary_text = "NA"

            pop = entry.get("pop", 0)
            pop_pct = int(pop * 100)
            rain_mm = entry.get("rain", 0)
            snow_mm = entry.get("snow", 0)
            wind_s = entry.get("wind_speed", None)
            wind_d = entry.get("wind_deg", None)
            wind_parts = []
            if wind_s is not None:
                wind_parts.append(f"{wind_s:.0f} mph")
            if wind_d is not None:
                wind_parts.append(f"{int(wind_d)}°")
            wind_txt = " / ".join(wind_parts) if wind_parts else "NA"
            uvi_day = entry.get("uvi", "NA")

            lines.append(
                "<tr>"
                f"<td>{esc(day_str)}</td>"
                f"<td>{esc(hi)} / {esc(lo)}</td>"
                f"<td>{esc(summary_text)}</td>"
                f"<td>{esc(pop_pct)}</td>"
                f"<td>{esc(rain_mm)}</td>"
                f"<td>{esc(snow_mm)}</td>"
                f"<td>{esc(wind_txt)}</td>"
                f"<td>{esc(uvi_day)}</td>"
                "</tr>"
            )
        lines.append("</table>")
    lines.append("<div class='button-bar'>")
    lines.append("<a href='#hourly'>Previous: Hourly</a>")
    lines.append("<a href='#alerts'>Next: Alerts</a>")
    lines.append("</div>")
    lines.append("</div>")

    # ALERTS SECTION
    lines.append("<div class='section' id='alerts'>")
    lines.append("<h2>Active Alerts</h2>")
    if not alerts:
        lines.append("<p>No active weather alerts.</p>")
    else:
        for alert in alerts:
            sender = alert.get("sender_name", "Unknown source")
            event = alert.get("event", "Unknown event")
            start_ts = alert.get("start")
            end_ts = alert.get("end")
            desc = alert.get("description", "").strip()
            tags = alert.get("tags", [])

            if start_ts:
                start_str = datetime.fromtimestamp(start_ts).strftime(
                    "%Y-%m-%d %H:%M"
                )
            else:
                start_str = "N/A"
            if end_ts:
                end_str = datetime.fromtimestamp(end_ts).strftime(
                    "%Y-%m-%d %H:%M"
                )
            else:
                end_str = "N/A"

            lines.append("<div style='margin-bottom: 20px;'>")
            lines.append(f"<h3>{esc(event)}</h3>")
            lines.append(f"<p class='small'>From: {esc(sender)}</p>")
            lines.append(
                f"<p class='small'>Start: {esc(start_str)} &nbsp;&nbsp; End: {esc(end_str)}</p>"
            )
            if tags:
                tag_str = ", ".join(tags)
                lines.append(f"<p class='small'>Tags: {esc(tag_str)}</p>")
            if desc:
                lines.append("<pre style='white-space: pre-wrap;"
                             "background-color:#030712;"
                             "padding:8px;border-radius:4px;'>")
                lines.append(esc(desc))
                lines.append("</pre>")
            lines.append("</div>")
    lines.append("<div class='button-bar'>")
    lines.append("<a href='#daily'>Previous: Daily</a>")
    lines.append("<a href='#overview'>Back to Top</a>")
    lines.append("</div>")
    lines.append("</div>")

    lines.append("</body>")
    lines.append("</html>")

    return "\n".join(lines)


# -------------------------------------------------------------------
# HTTP REQUEST HANDLER
# -------------------------------------------------------------------
class WeatherRequestHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        path = self.path.split('?', 1)[0]

        if path in ("/", "/weather"):
            self.handle_weather_page()
        elif path == "/weather_panel.png":
            self.handle_png()
        else:
            self.send_error(404, "Not Found")

    def handle_weather_page(self):
        with WEATHER_LOCK:
            summary = LATEST_SUMMARY
            raw = LATEST_RAW
            updated = LAST_UPDATED

        html_body = build_html_page(summary, raw, updated)
        body_bytes = html_body.encode("utf-8")

        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body_bytes)))
        self.end_headers()
        self.wfile.write(body_bytes)

    def handle_png(self):
        if not os.path.exists(OUTPUT_PNG):
            self.send_error(404, "PNG not found")
            return

        try:
            with open(OUTPUT_PNG, "rb") as f:
                data = f.read()
        except Exception as e:
            logging.error(f"Error reading PNG for HTTP: {e}")
            self.send_error(500, "Error reading PNG")
            return

        self.send_response(200)
        self.send_header("Content-Type", "image/png")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, fmt, *args):
        logging.info("HTTP: " + fmt, *args)


# -------------------------------------------------------------------
# MAIN
# -------------------------------------------------------------------
def main():
    # Initial fetch so we have data and PNG before serving
    update_weather_once()

    # Start background updater thread
    t = threading.Thread(target=weather_updater_loop, daemon=True)
    t.start()

    # Start HTTP server (blocking)
    server_address = (HTTP_HOST, HTTP_PORT)
    httpd = ThreadingHTTPServer(server_address, WeatherRequestHandler)

    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(
        certfile="/etc/ssl/certs/hottub.crt",
        keyfile="/etc/ssl/private/hottub.key"
    )
    httpd.socket = context.wrap_socket(httpd.socket, server_side=True)


    logging.info(f"Starting weather HTTP server on {HTTP_HOST}:{HTTP_PORT}")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        logging.info("Shutting down weather HTTP server.")
        httpd.server_close()


if __name__ == "__main__":
    main()

