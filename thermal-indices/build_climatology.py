#!/usr/bin/env python3
"""
One-time build of climatology.csv: the per-city 1991-2020 thresholds that the
Excess Heat Factor (EHF) and Excess Cold Factor (ECF) compare against.

For every city in cities.json this script:

1. downloads hourly ERA5 2 m temperature for the nearest 0.25 degree grid point
   from the Copernicus Climate Data Store dataset
   ``reanalysis-era5-single-levels-timeseries`` (CC BY 4.0);
2. groups the UTC hours into the city's local calendar days and takes each
   day's minimum and maximum;
3. computes the daily mean as (Tmin + Tmax) / 2, the definition thermofeel's
   ``excess_heat.daily_mean_temperature`` and Nairn & Fawcett (2014) use, and
   the one runner.py applies to the recent weather;
4. takes the 95th and 5th percentiles of all daily means in 1991-2020 (one
   whole-period threshold per city, not a day-of-year window).

The model never runs this. It reads the committed climatology.csv.

Requirements: a free CDS account with the ERA5 licence accepted and an API key
in ~/.cdsapirc (https://cds.climate.copernicus.eu/how-to-api). Run from the
repo root:

    uv run --no-project --python 3.12 --with cdsapi==0.7.7 --with numpy==2.5.3 \\
        --with tzdata==2026.4 python thermal-indices/build_climatology.py

Downloads are cached in thermal-indices/.climatology-cache/ (git-ignored), so
an interrupted build resumes where it stopped.
"""
import csv
import io
import json
import sys
import zipfile
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import cdsapi
import numpy as np

HERE = Path(__file__).resolve().parent
CITIES_PATH = HERE / "cities.json"
OUTPUT_PATH = HERE / "climatology.csv"
CACHE_DIR = HERE / ".climatology-cache"

DATASET = "reanalysis-era5-single-levels-timeseries"
PERIOD_START = date(1991, 1, 1)
PERIOD_END = date(2020, 12, 31)
SOURCE = "ERA5 hourly 2m_temperature, Copernicus CDS reanalysis-era5-single-levels-timeseries"
PERIOD = "1991-2020"
METHOD = (
    "daily mean = (Tmin + Tmax) / 2 over local calendar days; "
    "whole-period 95th / 5th percentile (numpy linear interpolation)"
)


def log(message):
    print(message, file=sys.stderr, flush=True)


def cache_path(city):
    """Keyed by location too, so moving a city's coordinates fetches a new series.

    The time zone isn't part of the key: the download is in UTC and local days
    are regrouped from it on every run.
    """
    slug = f"{city['name']}-{city['state']}".lower().replace(" ", "-").replace(".", "")
    return CACHE_DIR / f"{slug}_{city['lat']:.4f}_{city['lon']:.4f}.csv"


def download(client, city):
    """Fetch the city's hourly series once; later runs reuse the cached CSV."""
    target = cache_path(city)
    if target.exists():
        return target
    CACHE_DIR.mkdir(exist_ok=True)
    # UTC request window: US local days lag UTC by 4-11 hours, so the last local
    # day of 2020 ends on 2021-01-01 UTC.
    request = {
        "variable": ["2m_temperature"],
        "location": {"longitude": city["lon"], "latitude": city["lat"]},
        "date": [f"{PERIOD_START.isoformat()}/{(PERIOD_END + timedelta(days=1)).isoformat()}"],
        "data_format": "csv",
    }
    partial = target.with_suffix(".download")
    client.retrieve(DATASET, request, str(partial))
    raw = partial.read_bytes()
    if raw[:2] == b"PK":  # the CDS may wrap the CSV in a zip
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            names = [n for n in archive.namelist() if n.endswith(".csv")]
            if len(names) != 1:
                raise RuntimeError(f"{city['name']}: expected one CSV in the download, got {names}")
            raw = archive.read(names[0])
    target.write_bytes(raw)
    partial.unlink()
    return target


def read_hourly_kelvin(path):
    """Return [(utc datetime, temperature K)] from a CDS time-series CSV."""
    with open(path, newline="") as fh:
        reader = csv.DictReader(fh)
        time_col = next((c for c in reader.fieldnames if c in ("valid_time", "time", "date")), None)
        temp_col = next((c for c in reader.fieldnames if c in ("t2m", "2m_temperature")), None)
        if time_col is None or temp_col is None:
            raise RuntimeError(f"{path.name}: unexpected columns {reader.fieldnames}")
        rows = []
        for row in reader:
            stamp = datetime.fromisoformat(row[time_col].replace("Z", "+00:00"))
            if stamp.tzinfo is None:
                stamp = stamp.replace(tzinfo=timezone.utc)
            rows.append((stamp, float(row[temp_col])))
    return rows


def daily_means_celsius(hourly, tz_name):
    """(Tmin + Tmax) / 2 for every complete local day in the period, in Celsius."""
    tz = ZoneInfo(tz_name)
    by_day = defaultdict(list)
    for stamp, t_k in hourly:
        by_day[stamp.astimezone(tz).date()].append(t_k)
    means = []
    day = PERIOD_START
    while day <= PERIOD_END:
        values = by_day.get(day, [])
        expected = local_day_length_hours(day, tz)
        if len(values) != expected:
            raise RuntimeError(f"{day}: {len(values)} hourly values, expected {expected}")
        means.append(0.5 * (min(values) + max(values)) - 273.15)
        day += timedelta(days=1)
    return np.array(means)


def local_day_length_hours(day, tz):
    """24, or 23/25 on daylight-saving transition days."""
    start = datetime(day.year, day.month, day.day, tzinfo=tz).astimezone(timezone.utc)
    nxt = day + timedelta(days=1)
    end = datetime(nxt.year, nxt.month, nxt.day, tzinfo=tz).astimezone(timezone.utc)
    return round((end - start).total_seconds() / 3600)


def main():
    cities = json.loads(CITIES_PATH.read_text())
    client = cdsapi.Client()
    rows = []
    for index, city in enumerate(cities, start=1):
        log(f"[{index}/{len(cities)}] {city['name']}, {city['state']}")
        path = download(client, city)
        try:
            means = daily_means_celsius(read_hourly_kelvin(path), city["timezone"])
        except RuntimeError as exc:
            raise RuntimeError(f"{city['name']}, {city['state']}: {exc}") from exc
        rows.append({
            "city": city["name"],
            "state": city["state"],
            "lat": city["lat"],
            "lon": city["lon"],
            "t95_c": round(float(np.percentile(means, 95)), 2),
            "t05_c": round(float(np.percentile(means, 5)), 2),
            "source": SOURCE,
            "period": PERIOD,
            "method": METHOD,
        })
    with open(OUTPUT_PATH, "w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    log(f"wrote {OUTPUT_PATH} ({len(rows)} cities)")


if __name__ == "__main__":
    main()
