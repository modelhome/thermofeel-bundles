# thermal-indices: US Daily Heat Stress

A Model Home model that reports how hot (or cold) it *feels*, and how dangerous
that is for people working outdoors, in 89 US cities: today and every day of
the last 30. It runs with no input, so it can be scheduled once a day.

For each city and day it returns the daily peak of every heat-stress index in
[thermofeel](https://github.com/ecmwf/thermofeel) (ECMWF's operational
thermal-comfort library, version 2.3.0), plain-language risk bands, and the
Excess Heat and Excess Cold Factors measured against the city's own
1991–2020 climate.

- [Run it](#run-it)
- [Input](#input)
- [Outputs](#outputs)
- [Cities](#cities)
- [Weather data](#weather-data)
- [How the indices are computed](#how-the-indices-are-computed)
- [Radiation and mean radiant temperature](#radiation-and-mean-radiant-temperature)
- [Excess Heat and Excess Cold Factors](#excess-heat-and-excess-cold-factors)
- [Risk bands](#risk-bands)
- [Determinism](#determinism)
- [Validation](#validation)
- [Rebuilding the climatology](#rebuilding-the-climatology)
- [Licences and attribution](#licences-and-attribution)

## Run it

**On Model Home:** create a model from
`https://github.com/modelhome/thermofeel-bundles/tree/main/thermal-indices`
and run it with an empty input `{}`. To keep it current, put it on a daily
schedule with that same empty input.

**Locally** (needs network access, including for the sample):

```bash
# with Docker; the build context is this folder, as on Model Home
cd thermal-indices
docker build -t thermofeel-thermal-indices:local .
docker run --rm thermofeel-thermal-indices:local > heat_indices.json

# or directly with Python 3.12
uv run --no-project --python 3.12 --with thermofeel==2.3.0 --with numpy==2.5.3 \
    --with tzdata==2026.4 python thermal-indices/runner.py thermal-indices/sample_input.json \
    run/heat_summary.output.json > run/heat_indices.output.json
```

`sample_input.json` is fixed to 2026-08-15 and four cities (Phoenix, Houston,
Chicago, Minneapolis) so it runs in a few seconds and its days all come from
ERA5. The full 89-city run takes one to two minutes.

## Input

One JSON object. Both fields are optional; `{}` is the normal input.

| Field | Meaning | Default |
|---|---|---|
| `date` | Last day of the 30-day window, `YYYY-MM-DD` | today (UTC) |
| `cities` | `[{name, state, lat, lon}, ...]` to use instead of the built-in list | [`cities.json`](./cities.json) |

A missing, empty (`""`) or `null` field falls back to its default. Days up to
16 days ahead are allowed and use forecasts. EHF and ECF need a city's
climatology, so for a custom city that isn't in the built-in list (matched by
`name` and `state`) they are null and the run records a warning.

## Outputs

| Output | Shape | Use it for |
|---|---|---|
| `heat_indices` | `{metadata, columns, rows}`, one row per city per day | analysis, and as the input to later damage-function models |
| `heat_summary` | `{generated_at, date, data_source, thermofeel_version, window_days, ..., cities: [{city, state, lat, lon, today, history}]}` | a map of today plus a 30-day trend per city |

Run locally, the runner also writes `heat_indices.csv` (the same table) next to
the summary file. Model Home keeps only JSON outputs, so on the platform the CSV
is not saved.

### Columns

| Column | Unit | Meaning |
|---|---|---|
| `city`, `state`, `lat`, `lon` | | where |
| `date` | | the city's local calendar day |
| `is_forecast` | | `true` if the day's weather came from the forecast endpoint (see [Weather data](#weather-data)) |
| `wbgt_peak_hour_local` | hour | local hour of the day's highest WBGT; the next four columns are from that hour |
| `t2m_c` | °C | air temperature |
| `rh_pct` | % | relative humidity |
| `wind_10m_ms` | m/s | wind speed at 10 m |
| `shortwave_wm2` | W/m² | incoming sunlight |
| `t2m_mean_c` | °C | daily mean temperature, (min + max) / 2 |
| `utci_c` | °C | Universal Thermal Climate Index, daily max |
| `utci_category` | | UTCI stress band |
| `wbgt_c` | °C | Wet Bulb Globe Temperature (Liljegren, in the sun), daily max |
| `wbgt_simple_c` | °C | simplified WBGT from temperature and humidity only, daily max |
| `wbgt_work_category` | | work/rest schedule at `wbgt_c` |
| `heat_index_c` | °C | NWS heat index (adjusted Rothfusz), daily max |
| `heat_index_category` | | NWS heat index band |
| `humidex_c` | °C | humidex, daily max |
| `apparent_temp_c` | °C | apparent temperature (no radiation), daily max |
| `net_c` | °C | normal effective temperature, daily max |
| `heat_force` | 0–10 | KNMI heat force from `wbgt_c` |
| `wind_chill_c` | °C | wind chill, daily **min**; null when no hour qualified |
| `ehf` | °C² | Excess Heat Factor, ≥ 0 |
| `ecf` | °C² | Excess Cold Factor, ≤ 0 |

Nullable: `wind_chill_c` often (see below); `utci_c`, `wbgt_c` and the columns
derived from them only if radiation is unavailable or the WBGT solver fails for
every hour (not expected for these cities); `ehf`/`ecf` for custom cities.

`metadata` (in `heat_indices`, and at the top level of `heat_summary`) records
`generated_at`, `retrieved_at`, `date`, `window_days`, `data_source`,
`thermofeel_version`, the `climatology` source and method, the radiation and
workload `assumptions`, and any `warnings`.

## Cities

[`cities.json`](./cities.json) lists 89 cities. Each has a `groups` list saying
why it is included:

- **`state_capital`** — the capital of every state (50).
- **`largest_non_capital`** — the ten largest US cities that aren't state
  capitals, by the US Census Bureau's Vintage 2024 population estimates
  ([`sub-est2024.csv`](https://www2.census.gov/programs-surveys/popest/datasets/2020-2024/cities/totals/sub-est2024.csv)):
  New York, Los Angeles, Chicago, Houston, Philadelphia, San Antonio, San Diego,
  Dallas, Jacksonville, Fort Worth.
- The stories a heat map should tell (from the original brief):
  - **`dry_heat`**: Phoenix, Las Vegas, Tucson, Sacramento, Fresno, Bakersfield,
    Riverside, El Paso, Albuquerque, Salt Lake City, Boise.
  - **`humid_heat`**: Houston, San Antonio, Dallas, Austin, New Orleans, Baton
    Rouge, Jackson, Memphis, Little Rock, Mobile, Miami, Tampa, Orlando,
    Jacksonville, Savannah, Charleston SC.
  - **`population_ac_demand`**: New York, Philadelphia, Washington DC, Baltimore,
    Chicago, St. Louis, Kansas City, Indianapolis, Columbus, Detroit.
  - **`cold`**: Minneapolis, Fargo, Bismarck, Great Falls, Denver, Buffalo,
    Boston, Portland ME, Anchorage.
  - **`mild_pacific`**: Seattle, Portland OR, San Francisco, Los Angeles,
    San Diego.

**Coordinates** are the official "Populated Place" coordinates from the
[USGS Geographic Names Information System](https://www.usgs.gov/tools/geographic-names-information-system-gnis)
(GNIS, domestic names file of 2026-08-28), usually the historic downtown;
`gnis_id` identifies each record. Each was cross-checked against the same place
in the Census Bureau's
[2020 Gazetteer](https://www2.census.gov/geo/docs/maps-data/data/gazetteer/2020_Gazetteer/2020_Gaz_place_national.zip)
to rule out same-named towns elsewhere in the state. The Gazetteer's own
"internal points" were not used: for cities with large water or wilderness areas
they are far from where people live (San Francisco's is 54 km out in the
Pacific; Anchorage's is 33 km into the mountains). `timezone` is the IANA zone
Open-Meteo reports for each point.

## Weather data

All weather comes from [Open-Meteo](https://open-meteo.com), which needs no API
key. Each city makes one or two requests covering **62 days** ending on `date`
(why 62: see [EHF](#excess-heat-and-excess-cold-factors)).

**Which days come from where.** The model prefers ERA5, the ECMWF reanalysis,
because the climatology is ERA5 too, so EHF and ECF compare like with like:

1. **ERA5 archive** — `https://archive-api.open-meteo.com/v1/archive` with
   `models=era5`. ERA5 lags real time by about 5–6 days. Every day of the window
   that ERA5 fully covers comes from here.
2. **Forecast** — `https://api.open-meteo.com/v1/forecast` (default
   `best_match` model mix, mostly NOAA HRRR and GFS over the US). The remaining
   recent days (typically the last 6–7, including today) come from here. For
   past days this is the forecast models' own recent analysis; for today and
   later it is a forecast.

Days from step 2 have **`is_forecast = true`**. Their values can change when
ERA5 catches up and a later run fetches them from the archive. The days from
the two sources can show a small step where they meet, because ERA5 (a ~31 km
reanalysis grid) and the forecast models (down to 3 km) represent the same
weather slightly differently. The model does not try to smooth that step.

Why not use one source? The forecast endpoint only serves about 70 days of
history (measured September 2026), which leaves little margin over the 62 days
needed, and its data would be compared against an ERA5 baseline on every day.
ERA5 alone cannot supply the most recent week.

**Hourly variables** (both endpoints, `timezone=auto`, `timeformat=unixtime`,
`wind_speed_unit=ms`): `temperature_2m`, `relative_humidity_2m`,
`wind_speed_10m`, `surface_pressure`, `cloud_cover`,
`shortwave_radiation_instant`, `direct_radiation_instant`,
`direct_normal_irradiance_instant`. The radiation variables are the
instantaneous values, not preceding-hour averages, because thermofeel's radiation
formulas pair a flux with the sun's position at the same moment. Eight
variables keep each request at the lowest call weight under Open-Meteo's
[terms](https://open-meteo.com/en/terms): a full run costs about 450 of the free
tier's 10,000 daily calls.

A day that neither source covers completely fails the whole run with the city
and date on stderr, rather than publishing a map with a gap.

## How the indices are computed

1. **Hourly.** Every index is computed for every hour of the 62-day window.
   Open-Meteo supplies Celsius; thermofeel works in Kelvin. The runner converts
   once, in `hourly_indices`, and converts back once. Dew point comes from
   relative humidity via thermofeel.
2. **Daily.** Hours are grouped into each city's local calendar day (so
   daylight-saving days have 23 or 25 hours). Each heat index becomes its daily
   **maximum**; wind chill becomes its daily **minimum**. The last 30 days are
   reported.

| Index | thermofeel function | Notes |
|---|---|---|
| UTCI | `calculate_utci` | needs mean radiant temperature (below); wind clamped to 0.5–17 m/s, the polynomial's fitting range |
| WBGT (Liljegren) | `calculate_wbgt_liljegren` | sun and wind aware; KNMI's operational guards; uses surface pressure, sunlight, direct fraction and solar angle |
| WBGT simple | `calculate_wbgt_simple` | temperature and humidity only |
| Heat index | `calculate_heat_index_adjusted` | NWS Rothfusz regression with adjustments; the simplified form is validated but not reported |
| Humidex | `calculate_humidex` | |
| Apparent temperature | `calculate_apparent_temperature` | Steadman / BoM, no radiation |
| Normal effective temperature | `calculate_normal_effective_temperature` | |
| Heat force | `calculate_heat_force` | KNMI 0–10 scale, from the daily max Liljegren WBGT |
| Wind chill | `calculate_wind_chill` | only hours with air ≤ 5 °C and wind 5–80 km/h, thermofeel's stated validity range; null on days with none |
| EHF, ECF | `excess_heat.*` | see below |

**Solar angle.** thermofeel 2.x no longer computes the sun's position. The
runner's `cos_solar_zenith` implements NOAA's solar calculator equations (after
Meeus) for each hour's exact UTC time; the check below compares it with pvlib's
NREL Solar Position Algorithm.

## Radiation and mean radiant temperature

UTCI needs the **mean radiant temperature** (MRT): roughly, how much heat a
person absorbs from sun, sky and ground. thermofeel's
`calculate_mean_radiant_temperature` (Di Napoli et al. 2020) is written for
ERA5's seven radiation fluxes. Open-Meteo provides some of them directly and
the rest are estimated:

| thermofeel input | ERA5 meaning | Here | |
|---|---|---|---|
| `ssrd` | sunlight reaching the ground | `shortwave_radiation_instant` | direct |
| `fdir` | direct-beam sunlight on a flat surface | `direct_radiation_instant` | direct |
| `dsrp` | direct-beam sunlight facing the sun | `direct_normal_irradiance_instant` | direct |
| `cossza` | cosine of the solar zenith angle | computed (NOAA equations) | computed |
| `ssr` | net sunlight (after reflection) | `ssrd × (1 − 0.20)`: fixed albedo 0.20 | **estimated** |
| `strd` | infrared from the sky | clear-sky emissivity from Prata (1996) using air temperature and humidity, raised for cloud cover with Unsworth & Monteith (1975): ε = (1 − 0.84c)·ε_clear + 0.84c, `strd = ε σ T⁴` | **estimated** |
| `strr` | net infrared | `strd − 0.97 σ T⁴`: the ground radiates at air temperature with emissivity 0.97 | **estimated** |

Open-Meteo has no infrared (longwave) radiation variable, and its
`terrestrial_radiation` is top-of-atmosphere sunlight, not usable here. The
estimates affect **UTCI only**; Liljegren WBGT uses sunlight, its direct
fraction and the solar angle, not longwave, and every other index uses no
radiation. In the check below, a clear summer noon at 30 °C gives an MRT of
about 50 °C, a clear night at 20 °C about 12 °C, and an overcast night about
18 °C.

**A measured alternative** exists: the Copernicus Climate Data Store's ERA5
hourly time series (`reanalysis-era5-single-levels-timeseries`) includes
`surface_thermal_radiation_downwards`. It isn't used at run time because it
lags about five days (so it can't cover the recent days that matter most), and
it needs an API key inside the model container, which Model Home has no secret
mechanism for. It is the natural upgrade if UTCI accuracy starts to matter.

## Excess Heat and Excess Cold Factors

EHF (Nairn & Fawcett 2014, [doi:10.3390/ijerph120100227](https://doi.org/10.3390/ijerph120100227))
flags a heatwave when a city's recent three days are hot both for its climate
and for what people there have just been used to. ECF is the cold analogue
(Nairn 2013). The runner uses thermofeel's `excess_heat` functions unchanged,
with `clip=True`:

- daily mean temperature `T = (Tmin + Tmax) / 2` (thermofeel's
  `daily_mean_temperature`, as in Nairn & Fawcett), from the hourly series;
- `short` = mean of T over the 3 days **ending on the reported date**;
- `prior` = mean of T over the 30 days before those 3;
- `EHI_sig = short − T95`, `EHI_accl = short − prior`;
- `EHF = max(0, EHI_sig) × max(1, EHI_accl)` (≥ 0);
- `ECF = −min(0, short − T05) × min(−1, EHI_accl)` (≤ 0; more negative is colder).

**Which date a value belongs to.** Nairn & Fawcett and thermofeel's docstrings
attach the index to the *first* day of the 3-day window (days i, i+1, i+2).
This model attaches it to the *last* day, so a value never depends on days
after its date and today's value doesn't rest on two days of forecast. The
arithmetic is identical; only the label moves two days later.

**Why 62 days.** The earliest reported day needs its own 3-day window plus the
30 days before it: 33 days ending on that day. 30 reported days therefore need
30 + 33 − 1 = 62 days.

**Thresholds** `T95` and `T05` come from [`climatology.csv`](./climatology.csv):
the 95th and 5th percentiles of every daily mean temperature in 1991–2020 at the
city's ERA5 grid point, over the whole period (not a day-of-year window, which
is how Nairn & Fawcett define them). Source: hourly ERA5 2 m temperature from the
Copernicus Climate Data Store dataset
[`reanalysis-era5-single-levels-timeseries`](https://cds.climate.copernicus.eu/datasets/reanalysis-era5-single-levels-timeseries)
(Hersbach et al. 2020, [doi:10.1002/qj.3803](https://doi.org/10.1002/qj.3803)),
grouped into local days the same way as the runtime. The model reads this table
and never recomputes it.

## Risk bands

**`utci_category`** — the UTCI assessment scale (Bröde et al. 2012, as listed
in thermofeel's UTCI guide), on the daily max UTCI, lower bound inclusive:
extreme cold stress (< −40 °C), very strong cold stress (−40), strong cold
stress (−27), moderate cold stress (−13), slight cold stress (0), no thermal
stress (9), moderate heat stress (26), strong heat stress (32), very strong heat
stress (38), extreme heat stress (≥ 46).

**`heat_index_category`** — the National Weather Service classification
([weather.gov/ama/heatindex](https://www.weather.gov/ama/heatindex)) on the daily
max heat index: None (< 80 °F), Caution (80–90 °F), Extreme Caution (90–103 °F),
Danger (103–124 °F), Extreme Danger (≥ 125 °F). The heat index assumes shade;
NWS notes full sun can add up to 15 °F.

**`wbgt_work_category`** — a work/rest schedule from the NIOSH Recommended
Exposure Limit for **acclimatized** workers
([NIOSH 2016, *Occupational Exposure to Heat and Hot Environments*](https://www.cdc.gov/niosh/docs/2016-106/), chapter 8):
`REL [°C-WBGT] = 56.7 − 11.5 · log₁₀(M)`, with M the one-hour time-weighted
metabolic rate in watts. **Default workload:** moderate work at 300 W (NIOSH
Table 5-1 puts moderate at 234–349 W), resting at 117 W, normal one-layer work
clothing (no clothing adjustment). Averaging work and rest over the hour gives
these limits for the daily max `wbgt_c`:

| WBGT at or below | Category |
|---|---|
| 28.2 °C | No restriction |
| 29.0 °C | 45 min work / 15 min rest |
| 30.0 °C | 30 min work / 30 min rest |
| 31.3 °C | 15 min work / 45 min rest |
| above | Work not recommended |

This is a population-level indicator from modelled weather, not a site
assessment: an employer setting schedules should measure WBGT on site. The
workload, acclimatization and clothing are fixed for now; making them inputs is
a planned follow-up.

## Determinism

- **Deterministic given the inputs and the upstream data as of retrieval.**
  The same `date` and cities give the same results for the same Open-Meteo data.
  The newest days (`is_forecast = true`, typically the last 6–7) are
  preliminary and get revised, so re-running an old `date` later can shift those
  days slightly — the same situation as re-pulling market data. `retrieved_at`
  and `is_forecast` make this auditable.
- **The whole window is recomputed on every run.** Each run recalculates all
  30 days with the current code, so the trend always reflects the current code
  version, not whatever code ran on each past day. This is deliberate: the trend
  stays internally consistent and improves as the code improves.

There is no randomness and no dependence on the clock beyond the `date` default
and the `retrieved_at` / `generated_at` stamps.

## Validation

[`check_indices.py`](./check_indices.py) (not part of the image; needs network):

```bash
uv run --no-project --python 3.12 --with thermofeel==2.3.0 --with numpy==2.5.3 \
    --with tzdata==2026.4 --with pvlib==0.15.2 \
    python thermal-indices/check_indices.py --output run
```

1. **thermofeel's expected values.** It downloads thermofeel's own test cases
   and expected results from the GitHub tag matching the installed version,
   feeds them through the runner's Celsius-facing `hourly_indices`, and compares:
   WBGT simple, apparent temperature, NET and wind chill match to 1e-6 °C;
   heat index and humidex to 0.05 °C (they go through a dew-point round trip);
   Liljegren WBGT, heat force and UTCI match exactly on the cases inside the
   runner's guards (daylight; wind 0.5–17 m/s).
2. **Independent references.** NWS heat index chart (90 °F, 60 % RH → 100 °F),
   Environment Canada wind chill table (−20 °C, 30 km/h → −33), and solar zenith
   against pvlib's NREL SPA.
3. **Radiation plausibility** for clear noon, clear night and overcast night.
4. **EHF/ECF** on synthetic series with hand-computed answers, including that a
   value never uses days after its date.
5. **`--output DIR`**: the column set, 30 consecutive days per city, EHF/ECF
   present, value ranges, category labels, and that the summary matches the
   table.

## Rebuilding the climatology

[`build_climatology.py`](./build_climatology.py) produced `climatology.csv`. It
only needs rerunning if the city list changes. It needs a free
[Copernicus CDS account](https://cds.climate.copernicus.eu) with the ERA5 licence
accepted and the API key in `~/.cdsapirc`:

```bash
uv run --no-project --python 3.12 --with cdsapi==0.7.7 --with numpy==2.5.3 \
    --with tzdata==2026.4 python thermal-indices/build_climatology.py
```

Downloads are cached in `thermal-indices/.climatology-cache/` (git-ignored), so
an interrupted build picks up where it stopped.

## Licences and attribution

- This bundle: MIT (see the repository `LICENSE`).
- [thermofeel](https://github.com/ecmwf/thermofeel): Apache-2.0, © ECMWF.
  Installed from PyPI in the image; no thermofeel code is copied into this repo.
- Weather data by [Open-Meteo.com](https://open-meteo.com/), licensed
  [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). Open-Meteo's free
  API is for non-commercial use.
- ERA5: Hersbach et al. (2020), Copernicus Climate Change Service, CC BY 4.0.
  Contains modified Copernicus Climate Change Service information.
- City coordinates: USGS GNIS (public domain). Population ranking: US Census
  Bureau (public domain).
