#!/usr/bin/env python3
"""
Model Home runner: daily US heat stress from thermofeel thermal-comfort indices.

Reads one JSON input file (positional arg, default ``sample_input.json``) with
two optional fields:

- ``date``   -- ISO date, the last day of the 30-day output window. Defaults to
                the current UTC date, so a scheduled run needs no input.
- ``cities`` -- ``[{name, state, lat, lon}]``. Defaults to cities.json.

For each city it fetches 62 days of hourly weather from Open-Meteo (ERA5 for the
days the reanalysis already covers, the forecast endpoint for the rest),
computes thermofeel's indices hourly, reduces them to one value per local day,
adds the Excess Heat / Cold Factors against the committed 1991-2020 climatology,
and writes:

- stdout: the long-format table as JSON (the ``heat_indices`` output; the
  Modelfile redirects stdout to run/heat_indices.output.json);
- the second positional arg (default run/heat_summary.output.json): the same
  values shaped per city for a map-and-trend page (``heat_summary``);
- heat_indices.csv beside the summary, the table as CSV. Model Home keeps only
  JSON outputs, so this file exists only when the model is run off-platform.

Units: thermofeel takes and returns Kelvin; Open-Meteo and every output use
Celsius. Conversion happens once, in ``hourly_indices``, so names carry their
unit (``t2_c``, ``t2_k``). Logs go to stderr; stdout carries only the result.
"""
import csv
import importlib.metadata
import json
import math
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import thermofeel as tmf
from thermofeel import excess_heat

HERE = Path(__file__).resolve().parent
CITIES_PATH = HERE / "cities.json"
CLIMATOLOGY_PATH = HERE / "climatology.csv"
DEFAULT_INPUT_PATH = HERE / "sample_input.json"
DEFAULT_SUMMARY_PATH = Path("run") / "heat_summary.output.json"

# --- window ------------------------------------------------------------------
OUTPUT_DAYS = 30
EHF_SHORT_DAYS = 3  # the "current" 3-day mean
EHF_ACCLIMATISATION_DAYS = 30  # the 30 days before that 3-day window
EHF_LOOKBACK_DAYS = EHF_SHORT_DAYS + EHF_ACCLIMATISATION_DAYS  # 33
# The earliest output day needs its own 33-day lookback, which includes itself.
FETCH_DAYS = OUTPUT_DAYS + EHF_LOOKBACK_DAYS - 1  # 62

# --- weather source ----------------------------------------------------------
ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
# Eight variables keep each request at the weight of one Open-Meteo call per
# two weeks of data (requests with more than ten variables count extra).
# Radiation uses the *_instant variables: thermofeel's MRT and Liljegren WBGT
# expect instantaneous fluxes matched to the solar angle at the same moment,
# not preceding-hour averages.
CORE_VARIABLES = [
    "temperature_2m",
    "relative_humidity_2m",
    "wind_speed_10m",
    "surface_pressure",
]
# Only UTCI and Liljegren WBGT (and what derives from them) need these. A day
# missing them is still reported, with those indices null.
RADIATION_VARIABLES = [
    "cloud_cover",
    "shortwave_radiation_instant",
    "direct_radiation_instant",
    "direct_normal_irradiance_instant",
]
HOURLY_VARIABLES = CORE_VARIABLES + RADIATION_VARIABLES
DATA_SOURCE = (
    "Open-Meteo: ERA5 reanalysis (archive-api.open-meteo.com/v1/archive, models=era5) "
    "for every day it fully covers; forecast endpoint (api.open-meteo.com/v1/forecast, "
    "best_match) for the most recent days. Weather data by Open-Meteo.com, CC BY 4.0."
)
USER_AGENT = "modelhome-thermofeel-bundles/thermal-indices"
REQUEST_ATTEMPTS = 4
REQUEST_PAUSE_SECONDS = 0.2

# --- radiation assumptions (see README "Radiation and mean radiant temperature")
STEFAN_BOLTZMANN = 5.670374419e-8  # W m-2 K-4
SURFACE_ALBEDO = 0.20
SURFACE_EMISSIVITY = 0.97

# --- validity domains ----------------------------------------------------------
# UTCI's polynomial is fitted for 10 m wind of 0.5-17 m/s (Broede et al. 2012).
UTCI_WIND_MIN_MS = 0.5
UTCI_WIND_MAX_MS = 17.0
# thermofeel's wind chill is valid for -50..5 degC and 5-80 km/h.
WIND_CHILL_MIN_T_C = -50.0
WIND_CHILL_MAX_T_C = 5.0
WIND_CHILL_MIN_WIND_KMH = 5.0
WIND_CHILL_MAX_WIND_KMH = 80.0

# --- categories ----------------------------------------------------------------
# UTCI assessment scale, thermofeel docs/guide/utci.md (Broede et al. 2012).
# Lower bound inclusive; below -40 is extreme cold stress.
UTCI_CATEGORIES = [
    (46.0, "Extreme heat stress"),
    (38.0, "Very strong heat stress"),
    (32.0, "Strong heat stress"),
    (26.0, "Moderate heat stress"),
    (9.0, "No thermal stress"),
    (0.0, "Slight cold stress"),
    (-13.0, "Moderate cold stress"),
    (-27.0, "Strong cold stress"),
    (-40.0, "Very strong cold stress"),
]
UTCI_BELOW_ALL = "Extreme cold stress"

# NWS heat index classification (weather.gov/ama/heatindex), degF, lower bound inclusive.
HEAT_INDEX_CATEGORIES_F = [
    (125.0, "Extreme Danger"),
    (103.0, "Danger"),
    (90.0, "Extreme Caution"),
    (80.0, "Caution"),
]
HEAT_INDEX_BELOW_ALL = "None"

# Work/rest bands from the NIOSH Recommended Exposure Limit for acclimatized
# workers, REL [degC-WBGT] = 56.7 - 11.5 log10(M [W]) (NIOSH 2016, Criteria for
# a Recommended Standard: Occupational Exposure to Heat and Hot Environments,
# ch. 8), with M the one-hour time-weighted metabolic rate of work plus rest.
# Default workload: moderate work at 300 W (NIOSH Table 5-1: 234-349 W), rest at
# 117 W (Table 5-1), normal one-layer work clothing, acclimatized worker.
WORK_METABOLIC_RATE_W = 300.0
REST_METABOLIC_RATE_W = 117.0
WORK_REST_SCHEDULES = [
    (1.00, "No restriction"),
    (0.75, "45 min work / 15 min rest"),
    (0.50, "30 min work / 30 min rest"),
    (0.25, "15 min work / 45 min rest"),
]
WORK_REST_ABOVE_ALL = "Work not recommended"

TABLE_COLUMNS = [
    "city", "state", "lat", "lon", "date", "is_forecast", "wbgt_peak_hour_local",
    "t2m_c", "rh_pct", "wind_10m_ms", "shortwave_wm2", "t2m_mean_c",
    "utci_c", "utci_category", "wbgt_c", "wbgt_simple_c", "wbgt_work_category",
    "heat_index_c", "heat_index_category", "humidex_c", "apparent_temp_c", "net_c",
    "heat_force", "wind_chill_c", "ehf", "ecf",
]
CITY_COLUMNS = ["city", "state", "lat", "lon"]


class RunError(Exception):
    """A problem the run cannot recover from; reported on stderr, exit code 1."""


def log(message):
    print(message, file=sys.stderr, flush=True)


# =============================================================================
# Input
# =============================================================================


def parse_request(spec, today_utc):
    """Apply bond-style defaults: a missing, "" or null field falls back."""
    if spec is None:
        spec = {}
    if not isinstance(spec, dict):
        raise RunError("input must be a JSON object")

    raw_date = spec.get("date") or today_utc.isoformat()
    try:
        end_date = date.fromisoformat(raw_date)
    except (TypeError, ValueError):
        raise RunError(f"date must be an ISO date (YYYY-MM-DD), got {raw_date!r}") from None

    raw_cities = spec.get("cities") or json.loads(CITIES_PATH.read_text())
    if not isinstance(raw_cities, list):
        raise RunError("cities must be an array of {name, state, lat, lon}")
    cities = [validate_city(entry, index) for index, entry in enumerate(raw_cities)]
    seen = set()
    for city in cities:
        key = (city["name"], city["state"])
        if key in seen:
            raise RunError(f"cities lists {city['name']}, {city['state']} more than once")
        seen.add(key)
    return end_date, cities


def validate_city(entry, index):
    if not isinstance(entry, dict):
        raise RunError(f"cities[{index}] must be an object with name, state, lat, lon")
    name, state = entry.get("name"), entry.get("state")
    if not isinstance(name, str) or not name.strip():
        raise RunError(f"cities[{index}].name must be a non-empty string")
    if not isinstance(state, str) or not state.strip():
        raise RunError(f"cities[{index}].state must be a non-empty string")
    try:
        lat, lon = float(entry.get("lat")), float(entry.get("lon"))
    except (TypeError, ValueError):
        raise RunError(f"cities[{index}] ({name}) needs numeric lat and lon") from None
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        raise RunError(f"cities[{index}] ({name}) lat/lon out of range: {lat}, {lon}")
    return {"name": name.strip(), "state": state.strip(), "lat": lat, "lon": lon}


def load_climatology():
    if not CLIMATOLOGY_PATH.exists():
        raise RunError(f"{CLIMATOLOGY_PATH.name} is missing; build it with build_climatology.py")
    with open(CLIMATOLOGY_PATH, newline="") as fh:
        return {
            (row["city"], row["state"]): (float(row["t95_c"]), float(row["t05_c"]))
            for row in csv.DictReader(fh)
        }


# =============================================================================
# Weather fetch
# =============================================================================


def get_json(base_url, params):
    url = f"{base_url}?{urllib.parse.urlencode(params)}"
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    for attempt in range(1, REQUEST_ATTEMPTS + 1):
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                return json.load(response)
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", "replace")
            retryable = exc.code == 429 or exc.code >= 500
            if not retryable or attempt == REQUEST_ATTEMPTS:
                reason = body
                try:
                    reason = json.loads(body).get("reason", body)
                except ValueError:
                    pass
                raise RunError(f"Open-Meteo HTTP {exc.code}: {reason}") from None
            wait = float(exc.headers.get("Retry-After") or 5 * 3 ** (attempt - 1))
        except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
            if attempt == REQUEST_ATTEMPTS:
                raise RunError(f"could not reach Open-Meteo: {exc}") from None
            wait = 5 * 3 ** (attempt - 1)
        log(f"  retrying in {wait:.0f}s (attempt {attempt} of {REQUEST_ATTEMPTS})")
        time.sleep(wait)
    raise AssertionError("unreachable")


def request_hours(base_url, city, start, end, extra=None):
    """Hourly values for local days start..end, grouped by local date."""
    params = {
        "latitude": city["lat"],
        "longitude": city["lon"],
        "hourly": ",".join(HOURLY_VARIABLES),
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "timezone": "auto",
        "timeformat": "unixtime",
        "wind_speed_unit": "ms",
        **(extra or {}),
    }
    payload = get_json(base_url, params)
    time.sleep(REQUEST_PAUSE_SECONDS)
    tz = ZoneInfo(payload["timezone"])
    hourly = payload["hourly"]
    days = defaultdict(list)
    for index, stamp in enumerate(hourly["time"]):
        local = datetime.fromtimestamp(stamp, tz)
        values = {name: hourly[name][index] for name in HOURLY_VARIABLES}
        days[local.date()].append((stamp, local.hour, values))
    return payload["timezone"], tz, days


def local_day_length_hours(day, tz):
    """24, or 23/25 on daylight-saving transition days."""
    start = datetime(day.year, day.month, day.day, tzinfo=tz).astimezone(timezone.utc)
    nxt = day + timedelta(days=1)
    end = datetime(nxt.year, nxt.month, nxt.day, tzinfo=tz).astimezone(timezone.utc)
    return round((end - start).total_seconds() / 3600)


def is_complete(hours, day, tz):
    """Every hour of the local day present, with the variables every index needs."""
    return len(hours) == local_day_length_hours(day, tz) and all(
        values[name] is not None for _, _, values in hours for name in CORE_VARIABLES
    )


def fetch_window(city, end_date):
    """Hourly arrays for FETCH_DAYS local days ending on end_date.

    ERA5 first: the archive returns nulls for days the reanalysis doesn't cover
    yet, so the leading run of complete days comes from ERA5 and every day
    after the first incomplete one comes from the forecast endpoint.
    """
    start_date = end_date - timedelta(days=FETCH_DAYS - 1)
    days = [start_date + timedelta(days=i) for i in range(FETCH_DAYS)]

    tz_name, tz, archive = request_hours(ARCHIVE_URL, city, start_date, end_date, {"models": "era5"})
    chosen, sources = {}, {}
    for day in days:
        if not is_complete(archive.get(day, []), day, tz):
            break
        chosen[day], sources[day] = archive[day], "era5"

    remaining = [day for day in days if day not in chosen]
    if remaining:
        _, _, forecast = request_hours(FORECAST_URL, city, remaining[0], end_date)
        for day in remaining:
            if not is_complete(forecast.get(day, []), day, tz):
                raise RunError(
                    f"{city['name']}, {city['state']}: no complete weather for {day} "
                    "from either the ERA5 archive or the forecast endpoint"
                )
            chosen[day], sources[day] = forecast[day], "forecast"

    hours = [(day, hour) for day in days for hour in chosen[day]]
    # Missing radiation values (None) become NaN, which makes the indices that
    # need them NaN, reported as null.
    arrays = {
        name: np.array([values[name] for _, (_, _, values) in hours], dtype=float)
        for name in HOURLY_VARIABLES
    }
    arrays["unix_time"] = np.array([stamp for _, (stamp, _, _) in hours], dtype=float)
    arrays["local_hour"] = np.array([hour for _, (_, hour, _) in hours], dtype=int)
    arrays["day_index"] = np.array([days.index(day) for day, _ in hours], dtype=int)
    return {
        "timezone": tz_name,
        "days": days,
        "sources": [sources[day] for day in days],
        "hourly": arrays,
    }


# =============================================================================
# Physics
# =============================================================================


def cos_solar_zenith(unix_time, lat, lon):
    """Cosine of the solar zenith angle, clipped at 0 below the horizon.

    NOAA Solar Calculator equations (after Meeus, Astronomical Algorithms),
    accurate to well under a degree for 1800-2100.
    """
    rad = np.radians
    julian_day = unix_time / 86400.0 + 2440587.5
    jc = (julian_day - 2451545.0) / 36525.0  # Julian centuries since J2000

    mean_long = (280.46646 + jc * (36000.76983 + jc * 0.0003032)) % 360.0
    mean_anom = 357.52911 + jc * (35999.05029 - 0.0001537 * jc)
    eccentricity = 0.016708634 - jc * (0.000042037 + 0.0000001267 * jc)
    centre = (
        np.sin(rad(mean_anom)) * (1.914602 - jc * (0.004817 + 0.000014 * jc))
        + np.sin(rad(2 * mean_anom)) * (0.019993 - 0.000101 * jc)
        + np.sin(rad(3 * mean_anom)) * 0.000289
    )
    omega = 125.04 - 1934.136 * jc
    apparent_long = mean_long + centre - 0.00569 - 0.00478 * np.sin(rad(omega))
    mean_obliquity = 23.0 + (26.0 + (21.448 - jc * (46.815 + jc * (0.00059 - jc * 0.001813))) / 60.0) / 60.0
    obliquity = mean_obliquity + 0.00256 * np.cos(rad(omega))
    declination = np.arcsin(np.sin(rad(obliquity)) * np.sin(rad(apparent_long)))

    y = np.tan(rad(obliquity / 2.0)) ** 2
    equation_of_time_min = 4.0 * np.degrees(
        y * np.sin(2 * rad(mean_long))
        - 2 * eccentricity * np.sin(rad(mean_anom))
        + 4 * eccentricity * y * np.sin(rad(mean_anom)) * np.cos(2 * rad(mean_long))
        - 0.5 * y * y * np.sin(4 * rad(mean_long))
        - 1.25 * eccentricity * eccentricity * np.sin(2 * rad(mean_anom))
    )
    utc_minutes = np.mod(unix_time, 86400.0) / 60.0
    true_solar_minutes = np.mod(utc_minutes + equation_of_time_min + 4.0 * lon, 1440.0)
    hour_angle = rad(true_solar_minutes / 4.0 - 180.0)

    cos_zenith = (
        np.sin(rad(lat)) * np.sin(declination)
        + np.cos(rad(lat)) * np.cos(declination) * np.cos(hour_angle)
    )
    return np.clip(cos_zenith, 0.0, 1.0)


def downward_longwave(t2_k, vapour_pressure_hpa, cloud_fraction):
    """Estimated surface thermal radiation downwards [W m-2].

    Open-Meteo has no downward longwave variable. Clear-sky emissivity after
    Prata (1996), from air temperature and vapour pressure, raised for cloud
    cover with the Unsworth & Monteith (1975) correction.
    """
    precipitable_water_cm = 46.5 * vapour_pressure_hpa / t2_k
    clear_sky = 1.0 - (1.0 + precipitable_water_cm) * np.exp(-np.sqrt(1.2 + 3.0 * precipitable_water_cm))
    emissivity = (1.0 - 0.84 * cloud_fraction) * clear_sky + 0.84 * cloud_fraction
    return emissivity * STEFAN_BOLTZMANN * t2_k**4


def mean_radiant_temperature_k(t2_k, vapour_pressure_hpa, cloud_fraction, ssrd, fdir, dni, cossza):
    """thermofeel MRT with Open-Meteo radiation mapped onto ERA5's fluxes."""
    strd = downward_longwave(t2_k, vapour_pressure_hpa, cloud_fraction)
    upward_longwave = SURFACE_EMISSIVITY * STEFAN_BOLTZMANN * t2_k**4  # surface at air temperature
    return tmf.calculate_mean_radiant_temperature(
        ssrd=ssrd,
        ssr=ssrd * (1.0 - SURFACE_ALBEDO),
        dsrp=dni,
        strd=strd,
        fdir=fdir,
        strr=strd - upward_longwave,
        cossza=cossza,
    )


def hourly_indices(t2_c, rh_pct, wind_10m_ms, pressure_hpa, ssrd, fdir, cossza, mrt_k):
    """Every index for aligned hourly arrays, in degC (heat force dimensionless).

    Inputs in Celsius; thermofeel is called in Kelvin; outputs back in Celsius.
    """
    t2_k = tmf.celsius_to_kelvin(t2_c)
    td_k = tmf.calculate_dew_point_from_relative_humidity(rh_pct, t2_k)
    vapour_pressure_hpa = tmf.calculate_saturation_vapour_pressure(t2_k) * rh_pct / 100.0

    with np.errstate(divide="ignore", invalid="ignore"):
        direct_fraction = np.where(ssrd > 0, fdir / ssrd, 0.0)
    wbgt_k = tmf.calculate_wbgt_liljegren(t2_k, rh_pct, pressure_hpa, wind_10m_ms, ssrd, direct_fraction, cossza)
    utci_wind = np.clip(wind_10m_ms, UTCI_WIND_MIN_MS, UTCI_WIND_MAX_MS)

    k_to_c = tmf.kelvin_to_celsius
    return {
        "utci_c": k_to_c(tmf.calculate_utci(t2_k, utci_wind, mrt_k, ehPa=vapour_pressure_hpa)),
        "wbgt_c": k_to_c(wbgt_k),
        "wbgt_simple_c": k_to_c(tmf.calculate_wbgt_simple(t2_k, rh_pct)),
        "heat_index_c": k_to_c(tmf.calculate_heat_index_adjusted(t2_k, td_k)),
        "humidex_c": k_to_c(tmf.calculate_humidex(t2_k, td_k)),
        "apparent_temp_c": k_to_c(tmf.calculate_apparent_temperature(t2_k, wind_10m_ms, rh_pct)),
        "net_c": k_to_c(tmf.calculate_normal_effective_temperature(t2_k, wind_10m_ms, rh_pct)),
        "wind_chill_c": k_to_c(tmf.calculate_wind_chill(t2_k, wind_10m_ms)),
        "heat_force": tmf.calculate_heat_force(wbgt_k),
    }


def excess_heat_and_cold(daily_mean_c, day, t95_c, t05_c):
    """EHF and ECF for window day `day`, attributed to the last day of its 3-day mean.

    thermofeel (Nairn & Fawcett 2014) defines the index for day i from days
    i..i+2; labelling it with day i+2 keeps every value free of future days.
    """
    short = float(np.mean(daily_mean_c[day - EHF_SHORT_DAYS + 1 : day + 1]))
    prior = float(np.mean(daily_mean_c[day - EHF_LOOKBACK_DAYS + 1 : day - EHF_SHORT_DAYS + 1]))
    accl = excess_heat.acclimatisation_index(short, prior)
    ehf = excess_heat.excess_heat_factor(excess_heat.significance_index(short, t95_c), accl, clip=True)
    ecf = excess_heat.excess_cold_factor(excess_heat.significance_index(short, t05_c), accl, clip=True)
    return float(ehf) + 0.0, float(ecf) + 0.0  # + 0.0 turns -0.0 into 0.0


# =============================================================================
# Daily reduction
# =============================================================================


def rounded(value, digits=2):
    if value is None or not math.isfinite(value):
        return None
    return round(float(value), digits)


def nan_max(values):
    """Largest finite value, or None when there is none (e.g. every hour NaN)."""
    return float(np.nanmax(values)) if np.isfinite(values).any() else None


def band(value, thresholds, below_all):
    if value is None:
        return None
    for lower, label in thresholds:
        if value >= lower:
            return label
    return below_all


def niosh_rel_c(metabolic_rate_w):
    return 56.7 - 11.5 * math.log10(metabolic_rate_w)


def work_rest_category(wbgt_c):
    if wbgt_c is None:
        return None
    for work_fraction, label in WORK_REST_SCHEDULES:
        rate = work_fraction * WORK_METABOLIC_RATE_W + (1 - work_fraction) * REST_METABOLIC_RATE_W
        if wbgt_c <= niosh_rel_c(rate):
            return label
    return WORK_REST_ABOVE_ALL


def daily_rows(city, window, climatology, warnings):
    h = window["hourly"]
    t2_c = h["temperature_2m"]
    rh_pct = h["relative_humidity_2m"]
    wind = h["wind_speed_10m"]
    ssrd = h["shortwave_radiation_instant"]
    fdir = h["direct_radiation_instant"]

    cossza = cos_solar_zenith(h["unix_time"], city["lat"], city["lon"])
    t2_k = tmf.celsius_to_kelvin(t2_c)
    vapour_pressure_hpa = tmf.calculate_saturation_vapour_pressure(t2_k) * rh_pct / 100.0
    mrt_k = mean_radiant_temperature_k(
        t2_k, vapour_pressure_hpa, h["cloud_cover"] / 100.0, ssrd, fdir,
        h["direct_normal_irradiance_instant"], cossza,
    )
    idx = hourly_indices(t2_c, rh_pct, wind, h["surface_pressure"], ssrd, fdir, cossza, mrt_k)
    wind_kmh = wind * 3.6
    wind_chill_valid = (
        (t2_c >= WIND_CHILL_MIN_T_C)
        & (t2_c <= WIND_CHILL_MAX_T_C)
        & (wind_kmh >= WIND_CHILL_MIN_WIND_KMH)
        & (wind_kmh <= WIND_CHILL_MAX_WIND_KMH)
    )

    n_days = len(window["days"])
    t_min = np.array([t2_c[h["day_index"] == d].min() for d in range(n_days)])
    t_max = np.array([t2_c[h["day_index"] == d].max() for d in range(n_days)])
    daily_mean_c = excess_heat.daily_mean_temperature(t_min, t_max)

    thresholds = climatology.get((city["name"], city["state"]))
    if thresholds is None:
        warnings.append(
            f"{city['name']}, {city['state']}: not in climatology.csv, so ehf and ecf are null"
        )

    rows = []
    for d in range(n_days - OUTPUT_DAYS, n_days):
        in_day = h["day_index"] == d
        # Daily maxima; wind chill is a daily minimum over valid hours, below.
        daily = {name: nan_max(values[in_day]) for name, values in idx.items() if name != "wind_chill_c"}

        wbgt_c = daily["wbgt_c"]
        peak_series = idx["wbgt_c"] if wbgt_c is not None else idx["wbgt_simple_c"]
        peak = np.flatnonzero(in_day)[np.nanargmax(peak_series[in_day])]

        chill = idx["wind_chill_c"][in_day & wind_chill_valid]
        heat_index_c = daily["heat_index_c"]
        utci_c = daily["utci_c"]
        ehf = ecf = None
        if thresholds is not None:
            ehf, ecf = excess_heat_and_cold(daily_mean_c, d, *thresholds)

        heat_force = daily["heat_force"]
        rows.append({
            "city": city["name"],
            "state": city["state"],
            "lat": city["lat"],
            "lon": city["lon"],
            "date": window["days"][d].isoformat(),
            "is_forecast": window["sources"][d] == "forecast",
            "wbgt_peak_hour_local": int(h["local_hour"][peak]),
            "t2m_c": rounded(t2_c[peak]),
            "rh_pct": rounded(rh_pct[peak], 1),
            "wind_10m_ms": rounded(wind[peak]),
            "shortwave_wm2": rounded(ssrd[peak], 1),
            "t2m_mean_c": rounded(daily_mean_c[d]),
            "utci_c": rounded(utci_c),
            "utci_category": band(utci_c, UTCI_CATEGORIES, UTCI_BELOW_ALL),
            "wbgt_c": rounded(wbgt_c),
            "wbgt_simple_c": rounded(daily["wbgt_simple_c"]),
            "wbgt_work_category": work_rest_category(wbgt_c),
            "heat_index_c": rounded(heat_index_c),
            "heat_index_category": band(
                None if heat_index_c is None else heat_index_c * 9 / 5 + 32,
                HEAT_INDEX_CATEGORIES_F, HEAT_INDEX_BELOW_ALL,
            ),
            "humidex_c": rounded(daily["humidex_c"]),
            "apparent_temp_c": rounded(daily["apparent_temp_c"]),
            "net_c": rounded(daily["net_c"]),
            "heat_force": None if heat_force is None else int(heat_force),
            "wind_chill_c": rounded(float(np.min(chill))) if chill.size else None,
            "ehf": rounded(ehf, 3),
            "ecf": rounded(ecf, 3),
        })
    return rows


# =============================================================================
# Output
# =============================================================================


def run_metadata(end_date, retrieved_at, warnings):
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "retrieved_at": retrieved_at,
        "date": end_date.isoformat(),
        "window_days": OUTPUT_DAYS,
        "data_source": DATA_SOURCE,
        "thermofeel_version": tmf.__version__,
        "numpy_version": np.__version__,
        "tzdata_version": importlib.metadata.version("tzdata"),
        "climatology": {
            "source": "ERA5 hourly 2m temperature, Copernicus Climate Data Store",
            "period": "1991-2020",
            "method": "whole-period 95th / 5th percentile of daily (Tmin + Tmax) / 2",
        },
        "assumptions": {
            "surface_albedo": SURFACE_ALBEDO,
            "surface_emissivity": SURFACE_EMISSIVITY,
            "downward_longwave": "estimated: Prata (1996) clear sky + Unsworth & Monteith (1975) cloud correction",
            "wbgt_work_category": (
                "NIOSH REL, acclimatized worker, moderate work 300 W, rest 117 W, normal work clothing"
            ),
            "ehf_ecf_date": "attributed to the last day of the 3-day mean",
        },
        "warnings": warnings,
    }


def summary_document(metadata, rows, cities):
    by_city = defaultdict(list)
    for row in rows:
        by_city[(row["city"], row["state"])].append({k: v for k, v in row.items() if k not in CITY_COLUMNS})
    return {
        **metadata,
        "cities": [
            {
                "city": city["name"],
                "state": city["state"],
                "lat": city["lat"],
                "lon": city["lon"],
                "today": by_city[(city["name"], city["state"])][-1],
                "history": by_city[(city["name"], city["state"])],
            }
            for city in cities
        ],
    }


def write_csv(path, rows):
    with open(path, "w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=TABLE_COLUMNS)
        writer.writeheader()
        for row in rows:
            writer.writerow({k: ("" if v is None else v) for k, v in row.items()})


def main():
    input_path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_INPUT_PATH
    summary_path = Path(sys.argv[2]) if len(sys.argv) > 2 else DEFAULT_SUMMARY_PATH
    try:
        with open(input_path) as fh:
            spec = json.load(fh)
        end_date, cities = parse_request(spec, datetime.now(timezone.utc).date())
        climatology = load_climatology()

        retrieved_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        warnings, rows = [], []
        log(f"{len(cities)} cities, {OUTPUT_DAYS} days ending {end_date}")
        for number, city in enumerate(cities, start=1):
            log(f"[{number}/{len(cities)}] {city['name']}, {city['state']}")
            rows.extend(daily_rows(city, fetch_window(city, end_date), climatology, warnings))
    except (RunError, OSError, json.JSONDecodeError) as exc:
        log(f"error: {exc}")
        sys.exit(1)

    for warning in warnings:
        log(f"warning: {warning}")
    metadata = run_metadata(end_date, retrieved_at, warnings)
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    # Compact JSON: 89 cities x 30 days is ~2,700 rows, which indentation would
    # double to ~2 MB per output on the platform.
    compact = {"separators": (",", ":")}
    summary_path.write_text(json.dumps(summary_document(metadata, rows, cities), **compact) + "\n")
    write_csv(summary_path.parent / "heat_indices.csv", rows)
    print(json.dumps({"metadata": metadata, "columns": TABLE_COLUMNS, "rows": rows}, **compact))


if __name__ == "__main__":
    main()
