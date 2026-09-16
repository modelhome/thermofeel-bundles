# Plan: Thermal indices

Source brief: docs/features/0001-thermal-indices.md
Status: blocked — `climatology.csv` not built (needs John's Copernicus CDS key); AC-2, AC-3, AC-4, AC-6 and AC-8 await it
Planned against commit: `ed9de00` (local `main`: top-level boilerplate + vendored feat, no
GitHub remote yet)
Base commit: `ed9de00` (branch `feat/0001-thermal-indices`)

## Outcome

A public `modelhome/thermofeel-bundles` repo whose `thermal-indices/` folder is a
self-contained Model Home model. Run with no input, it fetches the last two months of weather
for 89 US cities from Open-Meteo, computes thermofeel's heat-stress index set, and returns 30
days of daily values per city, both as a long-format table and as a JSON file shaped for a
future map-and-trend SPA. Adding the folder's GitHub URL on Model Home produces a model that can
run on a daily schedule with no parameters.

## Scope

### In scope

As in the brief: the `thermal-indices/` bundle (Modelfile, Dockerfile, runner, sample input,
city list, committed climatology table and build script), a committed validation check, the
bundle's README/CLAUDE.md documentation, and the top-level README bundle-table row.

### Out of scope

As in the brief: the three downstream damage-function models and any Flow wiring, the SPA, and
any Model Home platform change. Also out of scope for this plan: a configurable WBGT workload
class (default only, documented as configurable later), heat-wave severity (EHF ÷ EHF85),
and thermofeel 2.3.0's newer indices (the package is 2.3.0; only the brief's index set is emitted).

## Review answers (John, 2026-09-16)

- **Q1** Network egress at run time: accepted, keep the run-time fetch.
- **Q2** Two JSON outputs (option A): accepted "for now"; a CSV platform output may come later.
- **Q3** EHF/ECF labelled with the last day of the 3-day window, daily mean (Tmin + Tmax) / 2:
  accepted.
- **Q4** ERA5 archive first, forecast endpoint for the recent tail (option A): accepted, with
  the instruction to **document it** (README "Weather data" section: which days come from which
  endpoint, why, what `is_forecast` means, and the seam).
- **Q5** Create the public repo: done (`modelhome/thermofeel-bundles`, `main` pushed at
  `ed9de00`).
- **thermofeel version:** use **2.3.0** unless it causes problems. Checked: the 2.2.0 → 2.3.0
  diff only adds code, and thermofeel's own `test_thermofeel.py` + `test_excess_heat.py` pass
  (48 tests) with `thermofeel==2.3.0`, `numpy==2.5.3`, Python 3.12. Pinned to 2.3.0.
- **Downward longwave:** John asked whether a trusted source exists; if not, keep the
  estimation. Findings (probed 2026-09-16), none fits a no-key hourly point fetch covering both
  the last two months and today:
  - Open-Meteo: no surface longwave variable on either endpoint.
  - NASA POWER (no key, JSON): hourly `ALLSKY_SFC_LW_DWN` (CERES SYN1deg) ends ~3.5 months back
    (last valid 2026-05-31); the near-real-time FLASHFlux product is daily only, ~5-day lag.
  - Copernicus CDS ERA5 `surface_thermal_radiation_downwards`: the trusted match for
    thermofeel's `strd`, hourly, ~5-day lag, but needs a CDS account/API key, queued requests,
    and GRIB/NetCDF decoding; no forecast days.
  - NOAA GFS/HRRR `DLWRF` and ECMWF open-data IFS `strd`: forecasts only, GRIB2, large
    downloads.

  Decision: keep the estimation (D6); the candidates are listed in the README as a follow-up.

- **Cities (added mid-run):** "at the least include the capital of every state, plus the ten
  largest US cities that aren't already included in that list". Implemented as the union of the
  brief's 51 cities, the 50 state capitals, and the ten largest non-capital cities by the Census
  Bureau's Vintage 2024 estimates (New York, Los Angeles, Chicago, Houston, Philadelphia,
  San Antonio, San Diego, Dallas, Jacksonville, Fort Worth): **89 cities**. See D10.
- **Climatology source (asked mid-run):** Open-Meteo counts a request spanning more than two
  weeks as multiple calls, so a 30-year daily history costs ~783 calls per city (~70,000 for 89
  cities) against the free tier's 10,000/day. John chose **Copernicus CDS ERA5** (option 1 of 4:
  CDS ERA5, NASA POWER MERRA-2, Open-Meteo over ~7 days, paid Open-Meteo). See D16.
- **Longwave, corrected finding:** the CDS dataset chosen for the climatology,
  `reanalysis-era5-single-levels-timeseries` (hourly point CSVs, CC BY 4.0), *does* include
  `surface_thermal_radiation_downwards`. It is the trusted source for thermofeel's `strd`, but it
  lags ~5 days, has no forecast days, and needs a CDS key inside the model container, which Model
  Home has no secret mechanism for. The estimate (D6) stays; this dataset is the documented
  upgrade path.

The original questions are kept below for context.

### Q1 — Network egress at run time (answered: accepted)

**Finding: egress is permitted; no architecture change needed.** Evidence from the `modelhome`
repo at the time of planning:

- Model Jobs run in the `modelhome-runs` namespace. The chart's only NetworkPolicy
  (`infra/helm/modelhome/templates/networkpolicy-deps.yaml`) restricts *ingress to Postgres and
  Redis*; nothing restricts egress from run pods, locally (kind's CNI enforces no policy anyway)
  or on DOKS prod.
- Existing production models already download data at run time (the CLIMADA hurricane model
  fetches NASA distance-to-coast data inside its run).

**Recommendation:** keep the run-time Open-Meteo fetch. John to confirm he's not planning to
lock down run-pod egress; if he is, Open-Meteo's two hosts would need an allowlist entry (a
platform change, surfaced here, not made). *Affects:* runner design.

### Q2 — The CSV cannot be a Model Home output (answered: A)

The platform collects only `/run/<name>.output.json` for each declared output and parses it as
JSON (`backend/app/services/model_run_executor.py`, and the sidecar in `k8s_runner.py` uploads
only `*.output.json`). A CSV written by the runner is discarded on-platform, so the brief's
"primary CSV" can't reach anyone who runs the model through Model Home, including the SPA and
downstream Flow steps.

Options:

- **(A, recommended)** Two JSON outputs. `heat_indices` carries the long-format table as JSON
  records, one object per (city, date) with exactly the brief's column names, plus run
  metadata. `heat_summary` is the SPA-shaped JSON. When run locally the runner *also* writes
  `heat_indices.csv` (same columns) next to the summary output, for spreadsheet users; the README
  says plainly this file exists only off-platform. Downstream damage-function models consume
  `heat_indices`, so they compose through a Flow with no parsing.
- (B) Keep CSV primary and ask for a platform change to collect non-JSON artifacts. Out of this
  brief's scope; blocks AC-8.
- (C) Embed the CSV text as a string field inside a JSON output. Works on-platform but is
  unfriendly to both the SPA and Flow composition.

*Affects:* output schema, Modelfile, AC-3, AC-8.

### Q3 — Which day an EHF value belongs to, and what "daily mean" means (answered: as recommended)

thermofeel follows Nairn & Fawcett (2014) exactly, and it differs from the brief's reference
definition in two ways:

1. **Window direction.** thermofeel documents EHF for day *i* as using the 3-day mean of days
   *i, i+1, i+2* and the 30-day mean of days *i−30 … i−1* (forward-looking). The brief says
   "3-day mean ending today". Same arithmetic, different date label: the forward form needs two
   days *after* `date`, which only a forecast can supply.
2. **Daily mean.** thermofeel's `daily_mean_temperature` is (Tmin + Tmax) / 2, as in Nairn &
   Fawcett. The brief names Open-Meteo's `temperature_2m_mean` (a 24-hour average), which runs
   systematically different from (Tmin + Tmax) / 2.

**Recommendation:** label EHF/ECF with the *last* day of the 3-day window (the brief's "ending
today"), so every value is built from days up to and including its own date and never from
future forecasts; the 30-day acclimatisation mean covers the 30 days before that 3-day window.
Use (Tmin + Tmax) / 2 from the hourly series for *both* the climatology and the runtime, so the
T95/T05 thresholds and the daily means are like-for-like and match thermofeel's own definition.
The README states the relabelling explicitly and cites Nairn & Fawcett. The thermofeel
functions themselves (`significance_index`, `acclimatisation_index`, `excess_heat_factor`,
`excess_cold_factor`, with `clip=True` to match the brief's `max(0, ·)`) are used unchanged.

*Affects:* EHF/ECF section, climatology build, window length (see D4).

### Q4 — Where the older weather comes from (answered: A, document it)

Probed live on 2026-09-16:

- The forecast endpoint (`api.open-meteo.com/v1/forecast`, default `best_match` model mix,
  mostly HRRR/GFS for the US) serves hourly history back only ~70 days (to 2026-07-08 15:00),
  about a week more than the window needs.
- The ERA5 archive (`archive-api.open-meteo.com/v1/archive`, `models=era5`) lags real time by
  ~6 days (last complete hour 2026-09-10 16:00).
- Both serve every variable the plan needs, including instantaneous radiation.

Options:

- **(A, recommended)** ERA5 archive for every day it fully covers, forecast endpoint for the
  remaining recent days (~6 plus today). The climatology is ERA5, so EHF/ECF compare ERA5 days
  against an ERA5 baseline for all but the last few days, and the window isn't at the mercy of
  the forecast endpoint's ~70-day history limit. `is_forecast` has a precise meaning: the day
  came from the forecast endpoint. Cost: a small discontinuity where the two sources meet
  (ERA5's 0.25° grid vs a ~3 km forecast model), which the README documents.
- (B) Forecast endpoint for the whole window, as the brief defaults to. Smoother series, but
  compares forecast-model temperatures against an ERA5 climatology on every day, depends on a
  history limit Open-Meteo doesn't document as guaranteed, and `is_forecast` becomes a
  "last ~5 days" heuristic.

*Affects:* weather fetch, `is_forecast`, `data_source`.

### Q5 — Publishing to GitHub (answered: done)

AC-1 and AC-8 need `modelhome/thermofeel-bundles` to exist publicly, and `/feat run` needs a
GitHub remote to open its PR. Creating the repo and pushing the bootstrap `main` (commit
`ed9de00`) is an outward action that needs John's explicit go-ahead.

### Also raised for John (not blocking)

- **Open-Meteo terms.** The free API is for non-commercial use, with data under CC BY 4.0
  (attribution required). The plan adds attribution to the JSON metadata and README. If Model
  Home counts as commercial use, a paid Open-Meteo plan (an API key) would be needed; that's a
  spend decision.
- **thermofeel version.** The brief pins `thermofeel==2.2.0`; 2.3.0 is the latest release. The
  2.2.0 → 2.3.0 diff only *adds* modules and functions (new indices, Erbs/DISC direct-beam
  estimators) and changes none this plan uses. The plan keeps 2.2.0 as the brief says; bumping
  later is a one-line change.

## Assumptions and decisions

Settled here as ordinary implementation calls; each is documented in the README where users
would care.

- **D1 — Stack: numpy + standard library only.** HTTP via `urllib.request` with explicit
  retries, CSV via `csv`, time zones via `zoneinfo`. No pandas or requests: 89 cities × 62 days
  × 24 hours is small and grouping hours into local days is a few lines. Dockerfile pins
  `thermofeel==2.3.0`, `numpy==2.5.3`, and `tzdata==2026.4` (python:3.12-slim
  ships without a zoneinfo database). Base, `WORKDIR`, `ENTRYPOINT`, `CMD` as in bond. This
  departs from the brief's "pandas, an HTTP client" pin list because nothing needs them.
- **D2 — Solar geometry in-repo, no `earthkit-meteo`.** A short, commented implementation of
  the NOAA solar-position equations (Meeus-based) gives cos(solar zenith) from lat, lon, and
  UTC time, clipped at 0 below the horizon. Validated in the check against reference values
  from NOAA's solar calculator (±0.5° zenith).
- **D3 — Time handling.** Request hourly data with `timeformat=unixtime&timezone=auto`: stamps
  are unambiguous UTC seconds (for solar geometry) while the response's IANA `timezone` defines
  local days (DST-safe; 23- and 25-hour days are handled naturally). Every "day" in the output
  is the city's local calendar day. `date` defaults to the current UTC date, as the brief says.
- **D4 — Window constants.** `OUTPUT_DAYS = 30`, `EHF_LOOKBACK_DAYS = 33` (3-day + prior
  30-day), `FETCH_DAYS = OUTPUT_DAYS + EHF_LOOKBACK_DAYS − 1 = 62`, fetched as local dates
  `date − 61 … date`. The brief's 63 counts the earliest output day twice; the plan derives
  62 from the named constants, and nothing depends on the extra day.
- **D5 — Radiation inputs use Open-Meteo's instantaneous variables** (`*_instant`), which match
  thermofeel's instantaneous-flux inputs and the cos(zenith) at the timestamp, rather than the
  preceding-hour averages.
- **D6 — Radiation → MRT mapping** (`calculate_mean_radiant_temperature` inputs, all W m⁻²):

  | thermofeel input | ERA5 meaning | Source here | Exact? |
  |---|---|---|---|
  | `ssrd` | surface solar radiation downwards | `shortwave_radiation_instant` | yes |
  | `fdir` | total-sky direct solar radiation at surface (horizontal) | `direct_radiation_instant` | yes |
  | `dsrp` | direct radiation on a plane perpendicular to the beam | `direct_normal_irradiance_instant` (Open-Meteo's DNI; thermofeel would otherwise estimate it as fdir / cossza) | yes |
  | `ssr` | surface net solar radiation | `ssrd × (1 − α)`, fixed albedo α = 0.20 | approximation |
  | `strd` | surface thermal radiation downwards | Open-Meteo has no downward longwave (`terrestrial_radiation` is top-of-atmosphere, not usable). Estimated as `ε_sky σ T_a⁴`, with clear-sky emissivity from Prata (1996) using air temperature and vapour pressure, adjusted for `cloud_cover` with the Unsworth & Monteith (1975) correction | approximation |
  | `strr` | surface net thermal radiation | `strd − ε_s σ T_s⁴`, with surface emissivity ε_s = 0.97 and surface temperature ≈ 2 m air temperature (ERA5 archive serves no surface temperature) | approximation |
  | `cossza` | cosine of solar zenith angle | D2 | computed |

  UTCI uses `calculate_utci(t2_k, va, mrt, td_k=…)`. Liljegren WBGT uses
  `calculate_wbgt_liljegren(t2_k, rh, pressure=surface_pressure, va, ssrd, fdir=direct/shortwave
  fraction (0 when shortwave is 0), cossza)` and needs no longwave term, so only UTCI inherits
  the longwave approximation. A hand-computed sensitivity note in the README gives the MRT
  shift for ±0.05 albedo and ±10% `strd`.
- **D7 — Hourly → daily reduction.** Daily maximum of each heat index, daily minimum of wind
  chill, over the city's local day, ignoring NaN hours (Liljegren returns NaN where its iteration
  doesn't converge). An index with no valid hour that day is null.
  - `wbgt_peak_hour_local` is the local hour (0–23) of the daily max Liljegren WBGT, falling back
    to WBGT-simple's peak when Liljegren is null all day. `t2m_c`, `rh_pct`, `wind_10m_ms`, and
    `shortwave_wm2` are echoed at that hour.
  - `t2m_mean_c` is (Tmin + Tmax) / 2 from the hourly series (Q3).
  - `heat_index_c` is the **adjusted** (NWS/Rothfusz) heat index, since the NWS categories are
    defined on it. The simplified heat index is computed and validated in the check but not
    emitted, so the column set stays as frozen in the brief.
  - `heat_force` is `calculate_heat_force` of the daily max Liljegren WBGT, KNMI's operational
    definition and what thermofeel's own test does. It is exact given WBGT, but inherits
    Liljegren's nullability.
  - `wind_chill_c` is computed only from hours inside the formula's validity domain
    (T ≤ 5 °C and wind 5–80 km/h, per thermofeel's docstring) and is **null** on days with no
    such hour, rather than reporting a summer "wind chill" of 40 °C. This makes it nullable,
    which the brief didn't mark.
- **D8 — Categories** (string values, finalised and cited during implementation):
  - `utci_category`: the 10 UTCI assessment bands (Bröde et al. 2012), from "extreme cold stress"
    (< −40 °C) to "extreme heat stress" (> 46 °C), on the daily max UTCI. Null when UTCI is null.
  - `heat_index_category`: NWS bands on the daily max adjusted heat index in °F, i.e. "None"
    (< 80), "Caution" (80–90), "Extreme Caution" (90–103), "Danger" (103–125),
    "Extreme Danger" (≥ 125). Thresholds to be checked against the NWS page during run.
  - `wbgt_work_category`: default **moderate workload, acclimatised worker**, using the ACGIH TLV
    / OSHA Technical Manual work-rest table (consistent with ISO 7243 reference values for
    acclimatised workers). Values: "No restriction", "75% work / 25% rest",
    "50% work / 50% rest", "25% work / 75% rest", "Work not recommended". Thresholds are copied
    from the primary table during run, not from memory, and cited. Based on `wbgt_c`, null when
    `wbgt_c` is null. The assumption is stated in the Modelfile comments and README and noted as
    configurable later.
- **D9 — EHF/ECF sign convention.** EHF ≥ 0. ECF follows thermofeel/Nairn and is ≤ 0 (more
  negative = stronger cold excess). The README says so.
- **D10 — City list: `cities.json`,** 89 entries, each `{name, state, lat, lon, timezone,
  gnis_id, groups}`. `groups` records why a city is in the list (`dry_heat`, `humid_heat`,
  `population_ac_demand`, `cold`, `mild_pacific`, `state_capital`, `largest_non_capital`).
  **Deviation from the planned source:** coordinates are the official **USGS GNIS** "Populated
  Place" coordinates (the federal register of place names, usually the historic downtown), not
  the Census Gazetteer internal points. The internal points were unusable for weather in places
  with large water or wilderness areas: San Francisco's lies 54 km out in the Pacific, and
  Anchorage's 33 km into the Chugach mountains. Each GNIS point was cross-checked against the
  Census 2020 Gazetteer place of the same name (to rule out same-named towns elsewhere in the
  state); all eight points more than 15 km apart were confirmed to be the downtowns.
  `timezone` is the IANA zone Open-Meteo reports for the point. The ten largest non-capital
  cities come from the Census Bureau's Vintage 2024 city and town population estimates
  (`sub-est2024.csv`).
- **D11 — Cities without a climatology row.** Custom `cities` are matched to `climatology.csv`
  by `name` + `state`. When there's no match, `ehf`/`ecf` are null for that city, and a
  `warnings` entry in the output metadata (and a stderr line) says why. Climatology is never
  computed at run time, as the brief requires.
- **D12 — Fetch failures fail the run.** Each request retries 3 times with backoff on network
  errors, 429, and 5xx. If a city still can't be fetched, or returns gaps inside the window, the
  runner exits non-zero with the city and reason on stderr, so a scheduled run never publishes a
  silently incomplete map.
- **D13 — Modelfile.** `name = "US Daily Heat Stress"`, description naming thermofeel and
  Open-Meteo. Under Q2-A:
  `run = "docker run --rm -v \"$PWD/run:/run\" ${IMAGE} ${ARGS} > run/heat_indices.output.json"`,
  `args = ["{input:heat_request}", "{output:heat_summary}"]`, `image =
  "modelhome/thermofeel-thermal-indices:latest"`, `[resources] memory = "1Gi"`, `cpu = "1"`.
  One input `heat_request` with `required = []`, per-property plain-language descriptions, and
  schema `default = {}` so the platform's "Example to paste" is exactly what a daily schedule
  should send (a fixed date there would freeze every schedule built from it). Outputs
  `heat_indices` and `heat_summary` with typed schemas. TOML comments carry units, validity
  domains (UTCI polynomial range, wind-chill domain, WBGT workload class), and both determinism
  semantics.
- **D14 — Runner CLI.** `runner.py [input.json] [summary_output_path]`. The table JSON goes to
  stdout. The summary goes to `summary_output_path`, default `run/heat_summary.output.json`, and
  `heat_indices.csv` is written beside it. Logs go to stderr only. With no args (the Docker
  `CMD`), it reads `sample_input.json`.
- **D15 — Output metadata** (in both JSON outputs): `generated_at`, `retrieved_at`, `date`,
  `window_days`, `data_source` (both endpoint URLs, the ERA5 model name, and the CC BY 4.0
  attribution), `thermofeel_version` (read from `thermofeel.__version__`), `climatology`
  (period and method), `assumptions` (albedo, emissivities, WBGT workload class), and `warnings`.
- **D16 — Climatology build** (`build_climatology.py`, run once by hand, not in the image):
  for each city in `cities.json`, request hourly `2m_temperature` for 1991-01-01 … 2020-12-31
  from the Copernicus CDS dataset `reanalysis-era5-single-levels-timeseries` (ERA5, nearest
  0.25° grid point, CSV) via `cdsapi`. Group the UTC hours into the city's local days
  (`zoneinfo`, the city's `timezone`), take Tmin/Tmax per day, daily mean = (Tmin + Tmax) / 2,
  and whole-period `numpy.percentile` 95 and 5 (linear interpolation). Write `climatology.csv`
  with `city, state, lat, lon, t95_c, t05_c, source, period, method`. Raw CDS downloads are
  cached in a git-ignored folder so an interrupted build resumes. The script's dependencies
  (`cdsapi`, numpy, tzdata) are supplied with `uv run --with …`; `cdsapi` is not in the model
  image. It needs John's CDS account and `~/.cdsapirc`, which he sets up himself.
- **D17 — Sample input** `sample_input.json`: `date` fixed at `2026-08-15` (a recent past date
  fully covered by ERA5, so the sample is stable) and 4 cities, one per story: Phoenix AZ,
  Houston TX, Chicago IL, Minneapolis MN.
- **D18 — Validation check** `check_indices.py`, committed, not copied into the image:
  1. Downloads thermofeel's `tests/thermofeel_testcases.csv` and expected-value CSVs from the
     GitHub tag matching the installed version (so nothing Apache-licensed is vendored). Passes
     the Kelvin test cases through the **runner's own** Celsius-facing wrappers after converting
     to °C, and compares against the expected tables (heat index adjusted and simplified,
     humidex, apparent temperature, NET, WBGT-simple, wind chill, heat force, Liljegren WBGT, and
     UTCI given MRT) to thermofeel's own tolerance. This proves the unit boundary, not just
     thermofeel.
  2. Independent spot values: an NWS heat-index table point, an Environment Canada wind-chill
     table point, and NOAA solar-calculator zenith angles (D2).
  3. EHF/ECF on a synthetic daily series with a hand-computed answer, including the window
     labelling (Q3).
  4. `--output PATH`: validates a produced `heat_indices` / `heat_summary` pair, checking every
     brief column is present, 30 rows per city, `ehf`/`ecf` non-null for all default cities,
     `today` equal to the last history entry, and plausible ranges (UTCI −60…60 °C, WBGT
     −10…40 °C, MRT − T_air within −30…+70 °C).

## Implementation notes and deviations (run, 2026-09-16)

Recorded by `/feat run`. Each is a place the implementation differs from, or adds to, the
decisions above.

- **Cities (John, mid-run):** 89 cities, GNIS coordinates instead of Census internal points
  (D10 rewritten above).
- **Climatology source (John, mid-run):** Copernicus CDS ERA5 instead of Open-Meteo (D16
  rewritten above). **Blocker:** the build needs John's CDS account and `~/.cdsapirc`, which did
  not exist during the run; John chose to open the PR as a draft without it. Everything that
  needs `climatology.csv` is `blocked` below. `build_climatology.py`'s parsing and local-day
  grouping (including a 23-hour DST day) were tested on synthetic CSV data; its CDS request has
  not run against the live service.
- **D8 `wbgt_work_category` source:** the OSHA Technical Manual no longer prints the ACGIH work/rest
  table (it points to the paywalled ACGIH TLV documentation), so the bands come from the public
  NIOSH (2016) Recommended Exposure Limit equation, `REL = 56.7 − 11.5 log10(M)`, with M the
  one-hour time-weighted metabolic rate (moderate work 300 W, rest 117 W, both from NIOSH Table
  5-1). Labels are NIOSH-style schedules: "No restriction", "45 min work / 15 min rest",
  "30 min work / 30 min rest", "15 min work / 45 min rest", "Work not recommended" (limits
  28.2 / 29.0 / 30.0 / 31.3 °C).
- **D8 heat index band:** NWS gives Danger as 103–124 °F; implemented lower-bound inclusive
  (≥ 125 °F is Extreme Danger).
- **D18 solar check:** reference zenith angles come from pvlib's NREL SPA (`pvlib==0.15.2`, a
  check-only dependency) rather than hand-copied NOAA calculator values. Agreement: 0.006°.
- **D18 MRT check:** MRT is not an output column, so the "MRT − T_air" range check became three
  radiation plausibility cases (clear noon, clear night, overcast night) in the check script.
- **D18 thermofeel tables:** Liljegren WBGT and heat force are compared on daylight cases only
  (thermofeel's own test divides by zero sunlight at night; the runner uses a direct fraction of
  0) and UTCI on the cases with wind inside 0.5–17 m/s (the runner clamps wind to the
  polynomial's fitting range, a choice added during implementation and documented in the README).
- **Compact JSON outputs:** outputs are written without indentation (~1.3 MB each instead of
  ~2 MB for the full 89-city run).
- **Modelfile nullable types:** Model Home's validator requires a string `type` on every required
  key, so nullable columns declare their base type and say when they can be null in the
  description. The Modelfile also carries the platform's annotation fields (`determinism`,
  `expected_runtime`, `validity_domain`, `not_for`, `provenance`, per-property `unit`), which the
  plan didn't name.
- **Lint:** `uvx ruff check` picks up the machine's user-level ruff configuration (EXE, B, RUF
  rules); the scripts were made executable to satisfy EXE001.
- **CLAUDE.md** gained the bundle section; per-bundle user documentation lives in
  `thermal-indices/README.md` (as planned in AC-9).

## Acceptance-criteria traceability

IDs are the brief's, unchanged. "Placeholder climatology" means a scratch-copy
`climatology.csv` with made-up thresholds, used only to exercise the code path; it is not
committed.

| ID | Acceptance criterion | Implementation | Verification | Status |
|---|---|---|---|---|
| AC-1 | Repo exists with top-level `.gitignore`, `.dockerignore`, MIT `LICENSE`, `README.md`, `CLAUDE.md`, and `thermal-indices/`, matching QuantLib-bundles conventions | `main` at `ed9de00` (boilerplate + vendored feat); this branch adds `thermal-indices/`, the README bundle row and the CLAUDE.md bundle section | `gh repo create modelhome/thermofeel-bundles --public` succeeded and `main` was pushed; files reviewed against QuantLib-bundles | pass |
| AC-2 | Bundle contains Modelfile, Dockerfile, runner, sample input, city list, `climatology.csv`, climatology build script | `thermal-indices/{Modelfile.toml, Dockerfile, runner.py, sample_input.json, cities.json, build_climatology.py, check_indices.py, README.md}` | All present except **`climatology.csv`**; Modelfile passes Model Home's validator (`OK`, 0 annotation warnings) | blocked (climatology.csv needs CDS key) |
| AC-3 | Runner on the sample writes the CSV + JSON with the brief's schema | `runner.py`; two JSON outputs + CSV (Q2-A, D14) | Scratch copy with placeholder climatology: exit 0, 120 rows, `check_indices.py --output` all pass. Committed tree without the table: exits 1 with `climatology.csv is missing` | blocked (needs climatology.csv) |
| AC-4 | `docker build` from the bundle folder succeeds and `docker run` reproduces the outputs | `Dockerfile` (D1) | Scratch build context with placeholder climatology: build OK; default CMD and mounted `/run` layout both exit 0; rows identical to the local run, metadata identical except timestamps | blocked (COPY needs climatology.csv) |
| AC-5 | No-radiation indices match thermofeel's expected values; UTCI/Liljegren plausible with documented MRT assumptions | `hourly_indices`, `mean_radiant_temperature_k`, `cos_solar_zenith` | `check_indices.py` parts 1–3 all pass (see Verification); full run UTCI 8.5–51.5 °C, WBGT 11.8–37.4 °C | pass |
| AC-6 | EHF/ECF populated for all 30 days from the committed 1991–2020 baseline and 33-day lookback | `excess_heat_and_cold`, `build_climatology.py` | Synthetic series part 4 passes (EHF 50, ECF −100, no future days); full run populated EHF/ECF on all 2,670 rows **with placeholder thresholds** | blocked (real baseline not built) |
| AC-7 | No `date` → current UTC date; no `cities` → baked-in list; scheduled run needs no parameters | `parse_request`; schema `default = {}` | Full run with `{}` (placeholder climatology): 89 cities, window ending 2026-09-16 (UTC today), `check_indices.py --output` all pass | pass (defaults verified; values await the real climatology) |
| AC-8 | Pasting the subfolder URL at `/models/new/repo` creates a working model whose run produces the artifacts | Modelfile per D13; Model Home's `build_k8s_command` resolves args to `/run/heat_request.output.json`, `/run/heat_summary.output.json` and the stdout redirect to `/run/heat_indices.output.json` | Not run: the image build needs `climatology.csv` | blocked |
| AC-9 | README documents climatology source/period/method with citation, WBGT workload, Open-Meteo endpoints/variables, radiation→MRT mapping and approximations, both determinism semantics | `thermal-indices/README.md` sections Excess Heat…, Risk bands, Weather data, Radiation and mean radiant temperature, Determinism | Checklist review: all five items present, with citations | pass |

## Verification

The repo had no checks before this feature, so there is no baseline beyond "files absent"; no
regression comparison is possible or claimed. Commands run from the repo root with
`TF="uv run --no-project --python 3.12 --with thermofeel==2.3.0 --with numpy==2.5.3 --with tzdata==2026.4"`.

| Command | Purpose | Baseline result | Final result |
|---|---|---|---|
| `$TF --with pvlib==0.15.2 python thermal-indices/check_indices.py` | AC-5, AC-6: thermofeel expected values through `hourly_indices`, spot values, radiation plausibility, EHF/ECF | n/a (file absent) | All 20 index checks pass: WBGT simple / AT / NET / wind chill / Liljegren / heat force / UTCI exact (≤ 3e-12 °C), heat index 1.9e-3 °C, humidex 3.4e-3 °C, NWS 99.7 °F, EC −32.57 °C, zenith 0.006°, MRT 50.5 / 12.0 / 17.8 °C, EHF 50, ECF −100 |
| `$TF python thermal-indices/runner.py thermal-indices/sample_input.json run/heat_summary.output.json > run/heat_indices.output.json` | AC-3 | n/a | Committed tree: exit 1, "climatology.csv is missing". Scratch copy + placeholder climatology: exit 0, 120 rows, ~5 s |
| `$TF --with pvlib==0.15.2 python thermal-indices/check_indices.py --output run` | AC-3, AC-6 output checks | n/a | Scratch sample outputs: all 40 checks pass |
| `$TF python thermal-indices/runner.py run/empty.json …` with `{}`, then `check_indices.py --output` | AC-7 | n/a | Scratch copy + placeholder climatology: exit 0, 89 cities, 2,670 rows, 3 min 13 s, 7 forecast days per city, all output checks pass |
| `cd thermal-indices && docker build … && docker run …` | AC-4 | n/a | Scratch build context + placeholder climatology: build and both run forms exit 0; rows identical to local run. In-repo build blocked on climatology.csv |
| `uv run python -m orchestration.modelfile validate …/thermal-indices/Modelfile.toml` (in `modelhome`) | AC-2, AC-8: platform accepts the Modelfile | n/a | `OK`; `collect_annotation_warnings` → 0 |
| `uvx ruff check thermal-indices` | Lint | n/a | All checks passed |
| `$TF --with cdsapi==0.7.7 python thermal-indices/build_climatology.py` | AC-2, AC-6: build the baseline | n/a | Blocked: `Missing/incomplete configuration file: ~/.cdsapirc` |
| Model Home local stack: add from repo URL, run with `{}` | AC-8 | n/a | Not run (blocked on climatology.csv) |

## Implementation steps

1. **Preconditions.** Q1–Q4 answered in this file; Q5 done (GitHub repo created, `main` pushed).
   Branch `feat/0001-thermal-indices` from `main`.
2. **City list.** Select the 89 cities (D10), take GNIS coordinates cross-checked against the 2020 Census Gazetteer, and write
   `cities.json` with GNIS ids and time zones (D10).
3. **Climatology.** Write `build_climatology.py` (D16), run it once, commit `climatology.csv`.
   Sanity-check that Phoenix's T95 is well above Seattle's and Fargo's T05 well below Miami's.
4. **Runner skeleton.** Input parsing with bond-style defaults (`date`, `cities`), constants
   (D4), stderr logging, CLI and output paths (D14).
5. **Fetch.** Archive + forecast split (Q4-A), `unixtime` stamps and local-day grouping (D3),
   instantaneous radiation (D5), retries and gap detection (D12), `is_forecast` per day.
6. **Solar geometry** (D2) and the **radiation → MRT** mapping (D6).
7. **Hourly indices.** One Celsius-facing function that takes hourly arrays for a city and
   returns every index in °C, converting to Kelvin once on the way in and back once on the way
   out.
8. **Daily reduction and categories** (D7, D8), peak hour, and echoed drivers.
9. **EHF/ECF** from (Tmin + Tmax) / 2 daily means and the climatology row (Q3, D9, D11).
10. **Outputs.** `heat_indices` records + metadata (D15) to stdout, `heat_summary` to the output
    path, CSV beside it (Q2-A).
11. **`check_indices.py`** (D18); run it and fix until green.
12. **Modelfile** (D13), **Dockerfile** (D1), **sample_input.json** (D17). Docker build and run.
13. **Docs.** `thermal-indices/README.md` covering every AC-9 item, plus Open-Meteo attribution
    and terms; top-level README bundle-table row; CLAUDE.md bundle section (design notes,
    Modelfile format, verified results with real numbers from step 11/12, task list).
14. **AC-8 on the local Model Home stack**, using the pushed feature-branch subfolder URL.
15. Fill in the verification table and traceability statuses, then commit, push, and open the
    PR (brief + plan + implementation). Stop at the PR.

## Files likely to change

- `thermal-indices/Modelfile.toml`, `Dockerfile`, `runner.py`, `sample_input.json`,
  `cities.json`, `climatology.csv`, `build_climatology.py`, `check_indices.py`, `README.md` (all
  new)
- `README.md` (bundle-table row), `CLAUDE.md` (bundle section)
- `docs/features/0001-thermal-indices.md`, `docs/plans/0001-thermal-indices.md` (land in the PR)

No Model Home (`modelhome` repo) files change.

## Risks and follow-ups

- **Longwave approximation drives UTCI.** `strd`/`strr` are estimated (D6), so UTCI is
  best-effort. Liljegren WBGT, the headline index, doesn't use longwave. Follow-up: compare a
  sample of days against ERA5 `strd` from the CDS if UTCI starts feeding a damage function.
- **Source seam at the ERA5/forecast boundary** (Q4-A) may show a small step in the 30-day
  trend. Documented, not corrected.
- **Branch URL for AC-8.** Model Home may split `/tree/feat/0001-thermal-indices/thermal-indices`
  at the wrong slash. If it does, test AC-8 from a temporary slash-free branch pointing at the
  same commit, and record it (a platform limitation to surface, not fix here).
- **Output size on the run page.** ~2,670 records in `heat_indices` plus the summary is roughly
  2.6 MB of compact JSON across both outputs, stored as the run's output summary. Check that the Model Home run page stays
  responsive during AC-8; if not, surface it as a platform issue rather than trimming the frozen
  schema.
- **Open-Meteo availability, rate limits, and terms** (non-commercial free tier, CC BY 4.0). A
  daily run is ~178 requests weighing ~450 calls under Open-Meteo's counting rule, inside the free limits (10,000/day, 600/minute) if requests are paced; the terms question is John's.
- **Open-Meteo's undocumented forecast-history depth** matters less under Q4-A, but if the
  archive lag ever exceeds the forecast endpoint's history, the fetch fails loudly (D12).
- **Follow-ups (not this PR):** configurable WBGT workload class; downstream damage-function
  bundles consuming `heat_indices`; the daily schedule itself (created on Model Home after
  merge); a measured longwave source (CDS ERA5 `strd`) if UTCI accuracy starts to matter.
