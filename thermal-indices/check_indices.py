#!/usr/bin/env python3
"""
Checks for the thermal-indices bundle. Not part of the model image.

    python thermal-indices/check_indices.py              # index and physics checks
    python thermal-indices/check_indices.py --output run # also validate a run's outputs

1. thermofeel's own expected values. Downloads thermofeel's test cases and
   expected-value tables from the GitHub tag matching the installed version (so
   nothing Apache-licensed is copied into this repo), converts the Kelvin test
   inputs to Celsius, runs them through runner.hourly_indices -- the same
   function the model uses -- and compares the Celsius results. This checks the
   unit boundary, not just thermofeel.
2. Independent spot values: NWS heat index chart, Environment Canada wind chill
   table, and solar zenith angles from pvlib's NREL SPA implementation.
3. Radiation plausibility: mean radiant temperature for clear-sky noon and night.
4. EHF / ECF on synthetic series with hand-computed answers, including which
   day a value is attributed to.
5. With --output DIR: the schema and plausibility of heat_indices.output.json
   and heat_summary.output.json in DIR.

Needs network access for part 1. Run with the model's pins plus pvlib:

    uv run --no-project --python 3.12 --with thermofeel==2.3.0 --with numpy==2.5.3 \\
        --with tzdata==2026.4 --with pvlib==0.15.2 python thermal-indices/check_indices.py
"""
import argparse
import io
import json
import sys
import urllib.request
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd  # pvlib dependency, used only to hand it timestamps
import pvlib
import thermofeel as tmf

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import runner

THERMOFEEL_TESTS = "https://raw.githubusercontent.com/ecmwf/thermofeel/{version}/tests/{name}"

failures = []


def check(label, ok, detail=""):
    print(f"{'PASS' if ok else 'FAIL'}  {label}{'  -- ' + detail if detail else ''}")
    if not ok:
        failures.append(label)


def fetch_table(name, **kwargs):
    url = THERMOFEEL_TESTS.format(version=tmf.__version__, name=name)
    with urllib.request.urlopen(url, timeout=60) as response:
        text = response.read().decode("utf-8")
    if kwargs.get("names"):
        return np.genfromtxt(io.StringIO(text), delimiter=",", names=True)
    return np.loadtxt(io.StringIO(text))


def compare(label, expected_c, actual_c, tolerance, mask=None):
    expected_c, actual_c = np.asarray(expected_c, float), np.asarray(actual_c, float)
    if mask is None:
        mask = np.isfinite(expected_c)
    mask = mask & np.isfinite(expected_c)
    worst = float(np.max(np.abs(expected_c[mask] - actual_c[mask]))) if mask.any() else float("nan")
    check(label, mask.any() and worst <= tolerance, f"{int(mask.sum())} cases, max |diff| {worst:.2e} degC (tolerance {tolerance:g})")


# -----------------------------------------------------------------------------
# 1. thermofeel expected values through runner.hourly_indices
# -----------------------------------------------------------------------------


def check_against_thermofeel_tables():
    print(f"\n1. thermofeel {tmf.__version__} expected values, via runner.hourly_indices (Celsius in, Celsius out)")
    cases = fetch_table("thermofeel_testcases.csv", names=True)
    t2_k, td_k, va = cases["t2m"], cases["td"], cases["va"]
    rh_pct = tmf.calculate_relative_humidity_percent(t2_k, td_k)
    # ERA5 test fluxes are hourly accumulations [J m-2]; runner takes W m-2.
    ssrd, fdir = cases["ssrd"] / 3600, cases["fdir"] / 3600

    out = runner.hourly_indices(
        t2_c=t2_k - 273.15,
        rh_pct=rh_pct,
        wind_10m_ms=va,
        pressure_hpa=np.full_like(t2_k, 1013.25),
        ssrd=ssrd,
        fdir=fdir,
        cossza=cases["cossza"],
        mrt_k=cases["mrt"],
    )
    k = 273.15
    # Exact paths (inputs used as given).
    compare("WBGT simple", fetch_table("wbgts.csv") - k, out["wbgt_simple_c"], 1e-6)
    compare("Apparent temperature", fetch_table("at.csv") - k, out["apparent_temp_c"], 1e-6)
    compare("Normal effective temperature", fetch_table("net.csv") - k, out["net_c"], 1e-6)
    compare("Wind chill", fetch_table("windchill.csv") - k, out["wind_chill_c"], 1e-6)
    # The runner derives dew point from relative humidity (Open-Meteo gives RH);
    # thermofeel's own dew-point round trip is tested to 0.01 K.
    compare("Heat index (adjusted)", fetch_table("hia.csv") - k, out["heat_index_c"], 0.05)
    compare("Humidex", fetch_table("humidex.csv") - k, out["humidex_c"], 0.05)
    # Liljegren WBGT and heat force: thermofeel's test divides fdir by ssrd, which
    # is undefined at night; the runner uses a direct fraction of 0 there.
    daylight = ssrd > 0
    compare("WBGT Liljegren (daylight cases)", fetch_table("wbgt_liljegren.csv") - k, out["wbgt_c"], 1e-6, daylight)
    compare("Heat force (daylight cases)", fetch_table("heat_force.csv"), out["heat_force"], 0, daylight)
    # UTCI: the runner clamps wind to the polynomial's 0.5-17 m/s fitting range.
    in_range = (va >= runner.UTCI_WIND_MIN_MS) & (va <= runner.UTCI_WIND_MAX_MS)
    compare("UTCI (wind 0.5-17 m/s cases)", fetch_table("utci.csv") - k, out["utci_c"], 1e-6, in_range)
    # Not emitted (heat_index_c is the adjusted form) but part of the brief's index set.
    compare(
        "Heat index (simplified), thermofeel direct",
        fetch_table("heatindex.csv") - k,
        tmf.calculate_heat_index_simplified(t2_k, rh_pct) - k,
        1e-6,
    )


# -----------------------------------------------------------------------------
# 2. Independent spot values
# -----------------------------------------------------------------------------


def one(value):
    """A single value as the one-element array the runner's functions expect."""
    return np.array([float(value)])


def one_hour(t2_c, rh_pct, wind_ms):
    return runner.hourly_indices(
        one(t2_c), one(rh_pct), one(wind_ms), one(1013.25), one(0.0), one(0.0), one(0.0), one(t2_c + 273.15)
    )


def check_spot_values():
    print("\n2. Independent reference values")
    # NWS heat index chart (weather.gov/ama/heatindex): 90 degF at 60% RH reads 100 degF.
    hi_f = one_hour((90 - 32) * 5 / 9, 60, 2)["heat_index_c"][0] * 9 / 5 + 32
    check("NWS chart: 90 degF, 60% RH -> 100 degF", abs(hi_f - 100) <= 1.0, f"got {hi_f:.1f} degF")
    # Environment Canada wind chill table: -20 degC air, 30 km/h wind reads -33.
    wc = one_hour(-20, 70, 30 / 3.6)["wind_chill_c"][0]
    check("Environment Canada table: -20 degC, 30 km/h -> -33", abs(wc - (-33)) <= 0.6, f"got {wc:.2f} degC")

    # Solar zenith vs pvlib NREL SPA (true zenith, no refraction).
    points = [
        (33.4484, -112.074, "2026-06-21T19:30:00Z"),  # Phoenix, near solar noon, solstice
        (61.2181, -149.9003, "2026-12-21T21:00:00Z"),  # Anchorage, winter midday
        (25.7617, -80.1918, "2026-03-20T12:15:00Z"),  # Miami, equinox morning
        (47.6062, -122.3321, "2026-09-16T01:00:00Z"),  # Seattle, evening
        (21.3069, -157.8583, "2026-08-01T22:00:00Z"),  # Honolulu, midday
    ]
    worst = 0.0
    for lat, lon, stamp in points:
        when = pd.Timestamp(stamp)
        reference = float(pvlib.solarposition.spa_python(pd.DatetimeIndex([when]), lat, lon)["zenith"].iloc[0])
        ours = float(np.degrees(np.arccos(runner.cos_solar_zenith(np.array([when.timestamp()]), lat, lon)[0])))
        if reference < 90:  # below the horizon the runner clips cos to 0 (90 degrees)
            worst = max(worst, abs(ours - reference))
        else:
            worst = max(worst, 0.0 if ours == 90.0 else abs(ours - 90.0))
    check("Solar zenith vs pvlib NREL SPA (5 points)", worst <= 0.5, f"max |diff| {worst:.3f} degrees")


# -----------------------------------------------------------------------------
# 3. Radiation plausibility
# -----------------------------------------------------------------------------


def mrt_c(t2_c, rh_pct, cloud_fraction, ssrd, fdir, dni, cossza):
    t2_k = one(t2_c + 273.15)
    e_hpa = tmf.calculate_saturation_vapour_pressure(t2_k) * rh_pct / 100.0
    mrt_k = runner.mean_radiant_temperature_k(t2_k, e_hpa, one(cloud_fraction), one(ssrd), one(fdir), one(dni), one(cossza))
    return float(mrt_k[0]) - 273.15


def check_radiation_plausibility():
    print("\n3. Mean radiant temperature plausibility")
    noon = mrt_c(30, 40, 0.0, 900, 780, 880, 0.95)
    check("Clear-sky summer noon: MRT 45-75 degC with air at 30 degC", 45 <= noon <= 75, f"MRT {noon:.1f} degC")
    night = mrt_c(20, 70, 0.0, 0, 0, 0, 0)
    check("Clear night: MRT 0-15 degC below air (20 degC)", 5 <= night <= 20, f"MRT {night:.1f} degC")
    overcast = mrt_c(20, 70, 1.0, 0, 0, 0, 0)
    check("Overcast night is warmer than clear night", overcast > night, f"{overcast:.1f} vs {night:.1f} degC")


# -----------------------------------------------------------------------------
# 4. EHF / ECF
# -----------------------------------------------------------------------------


def check_excess_heat():
    print("\n4. Excess Heat / Cold Factor")
    last = runner.FETCH_DAYS - 1
    hot = np.full(runner.FETCH_DAYS, 20.0)
    hot[-3:] = 30.0
    ehf, ecf = runner.excess_heat_and_cold(hot, last, 25.0, 10.0)
    # 3-day mean 30, prior 30-day mean 20: EHI_sig = 30 - 25 = 5, EHI_accl = 10.
    check("Heatwave: EHF = 5 x 10 = 50, ECF = 0", (ehf, ecf) == (50.0, 0.0), f"EHF {ehf}, ECF {ecf}")
    ehf_before, _ = runner.excess_heat_and_cold(hot, last - 3, 25.0, 10.0)
    check("Day before the hot spell uses no future days: EHF = 0", ehf_before == 0.0, f"EHF {ehf_before}")

    cold = np.full(runner.FETCH_DAYS, 20.0)
    cold[-3:] = 0.0
    ehf, ecf = runner.excess_heat_and_cold(cold, last, 25.0, 5.0)
    # EHI_sig = 0 - 5 = -5, EHI_accl = -20: ECF = -(-5) x min(-1, -20) = -100.
    check("Cold spell: ECF = -100, EHF = 0", (ehf, ecf) == (0.0, -100.0), f"EHF {ehf}, ECF {ecf}")
    check("Lookback length is 33 days", runner.EHF_LOOKBACK_DAYS == 33 and runner.FETCH_DAYS == 62)


# -----------------------------------------------------------------------------
# 5. Run outputs
# -----------------------------------------------------------------------------


def check_outputs(directory):
    print(f"\n5. Outputs in {directory}")
    table = json.loads((directory / "heat_indices.output.json").read_text())
    summary = json.loads((directory / "heat_summary.output.json").read_text())
    rows, meta = table["rows"], table["metadata"]
    check("Columns match the frozen schema", table["columns"] == runner.TABLE_COLUMNS)
    check("Every row has exactly those columns", all(list(r) == runner.TABLE_COLUMNS for r in rows))

    end = date.fromisoformat(meta["date"])
    expected_dates = [(end - timedelta(days=runner.OUTPUT_DAYS - 1 - i)).isoformat() for i in range(runner.OUTPUT_DAYS)]
    cities = [(c["city"], c["state"]) for c in summary["cities"]]
    by_city = {key: [r for r in rows if (r["city"], r["state"]) == key] for key in cities}
    check(
        f"{runner.OUTPUT_DAYS} consecutive days per city ending {end}",
        all([r["date"] for r in city_rows] == expected_dates for city_rows in by_city.values()),
        f"{len(cities)} cities, {len(rows)} rows",
    )
    no_climatology = {w.split(":")[0] for w in meta["warnings"]}
    covered = [r for r in rows if f"{r['city']}, {r['state']}" not in no_climatology]
    check(
        "EHF and ECF populated for every city in the climatology",
        bool(covered) and all(r["ehf"] is not None and r["ecf"] is not None for r in covered),
        f"{len(covered)} rows",
    )
    check("EHF >= 0 and ECF <= 0", all(r["ehf"] >= 0 and r["ecf"] <= 0 for r in covered))

    def within(column, low, high):
        values = [r[column] for r in rows]
        present = [v for v in values if v is not None]
        check(
            f"{column} within {low}..{high}",
            all(low <= v <= high for v in present),
            f"{len(present)} values, {len(values) - len(present)} null, range {min(present, default=None)}..{max(present, default=None)}",
        )

    within("utci_c", -60, 60)
    within("wbgt_c", -10, 40)
    within("wbgt_simple_c", -10, 45)
    within("heat_index_c", -50, 70)
    within("wind_chill_c", -60, 5)
    within("heat_force", 0, 10)
    within("wbgt_peak_hour_local", 0, 23)
    check("utci_c and wbgt_c present on every row", all(r["utci_c"] is not None and r["wbgt_c"] is not None for r in rows))
    labels = {
        "utci_category": {label for _, label in runner.UTCI_CATEGORIES} | {runner.UTCI_BELOW_ALL},
        "heat_index_category": {label for _, label in runner.HEAT_INDEX_CATEGORIES_F} | {runner.HEAT_INDEX_BELOW_ALL},
        "wbgt_work_category": {label for _, label in runner.WORK_REST_SCHEDULES} | {runner.WORK_REST_ABOVE_ALL},
    }
    for column, allowed in labels.items():
        check(f"{column} uses known labels", all(r[column] in allowed for r in rows))
    check("is_forecast is boolean", all(isinstance(r["is_forecast"], bool) for r in rows))

    check("Summary lists the same cities as the table", len(cities) == len({(r["city"], r["state"]) for r in rows}))
    check(
        "Summary history has 30 entries per city, today = newest",
        all(len(c["history"]) == runner.OUTPUT_DAYS and c["today"] == c["history"][-1] for c in summary["cities"]),
    )
    check(
        "Summary carries run metadata",
        all(summary.get(key) == meta[key] for key in ("date", "data_source", "thermofeel_version", "window_days")),
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    parser.add_argument("--output", type=Path, help="directory holding heat_indices.output.json and heat_summary.output.json")
    args = parser.parse_args()

    check_against_thermofeel_tables()
    check_spot_values()
    check_radiation_plausibility()
    check_excess_heat()
    if args.output:
        check_outputs(args.output)

    print(f"\n{'All checks passed' if not failures else f'{len(failures)} check(s) failed: ' + ', '.join(failures)}")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
