# Thermal indices

## Outcome

`modelhome/thermofeel-bundles` has a `thermal-indices/` bundle: a self-contained Model Home
model that, given a date and a list of US cities, fetches that day's weather (plus the
trailing window it needs), computes the full thermofeel "feels-like" and occupational
heat-stress index set per city for the most recent 30 days, and writes a long-format CSV
plus a convenience JSON shaped for a map-and-trend SPA.

Pasting the subfolder's GitHub URL into the "new model from repo" form at
`http://localhost:5173/models/new/repo` creates a working model that runs on a daily schedule
with no parameters. It is the first of a planned gallery of daily damage-function models, and
its output is designed as a clean input for the downstream ones.

## Scope

### In scope

Repo-wide conventions (mirror `QuantLib-bundles/bond/`, read thermofeel's source and tests
before coding, determinism for fetching bundles, Dockerfile pinning) are in the repo
[`CLAUDE.md`](../../CLAUDE.md) and apply here without being restated.

**Bundle contents.** `thermal-indices/` holds `Modelfile.toml`, `Dockerfile`, `runner.py`, a
sample input JSON, the baked-in city list, the committed climatology table, and the committed
climatology-build script. The top-level `README.md` bundle table lists `thermal-indices/`
(inputs → outputs) in bond's table style, and `CLAUDE.md` gains the bundle's design notes,
Modelfile format, verified results, and task list, as bond's does.

**Input schema** (JSON, declared in bond's `Modelfile.toml` input format):

- `date` — ISO date (`YYYY-MM-DD`), the last day of the output window ("today"). Defaults to
  the current UTC date at run time when omitted, so the scheduled run needs no parameters.
- `cities` — array of `{name, state, lat, lon}`. Defaults to the baked-in city list; an
  explicit array overrides it.

**Baked-in city list.** Coordinates from an authoritative, cited source. At the least it includes
the capital of every state plus the ten largest US cities that aren't state capitals (added at
plan review, 2026-09-16), together with the cities below, chosen to tell the four stories a good
map needs:

- Dry heat: Phoenix AZ, Las Vegas NV, Tucson AZ, Sacramento CA, Fresno CA, Bakersfield CA,
  Riverside CA, El Paso TX, Albuquerque NM, Salt Lake City UT, Boise ID
- Humid heat (high WBGT): Houston TX, San Antonio TX, Dallas TX, Austin TX, New Orleans LA,
  Baton Rouge LA, Jackson MS, Memphis TN, Little Rock AR, Mobile AL, Miami FL, Tampa FL,
  Orlando FL, Jacksonville FL, Savannah GA, Charleston SC
- Big-population / AC demand (Northeast + Midwest): New York NY, Philadelphia PA,
  Washington DC, Baltimore MD, Chicago IL, St. Louis MO, Kansas City MO, Indianapolis IN,
  Columbus OH, Detroit MI
- Cold / wind-chill / ECF signal: Minneapolis MN, Fargo ND, Bismarck ND, Great Falls MT,
  Denver CO, Buffalo NY, Boston MA, Portland ME, Anchorage AK
- Mild Pacific baseline: Seattle WA, Portland OR, San Francisco CA, Los Angeles CA,
  San Diego CA

**Weather fetch.**

- Source: Open-Meteo (free, no API key). One request per city returns the whole window.
- Raw window: 63 days of hourly + daily data ending on `date` (30 output days + the 33-day
  EHF lookback for the earliest output day); the length is a named constant. Default to the
  forecast endpoint with `past_days`/`forecast_days` covering the window including `date`; if
  it won't reliably serve the full past window, split older days to the ERA5 archive endpoint.
  Document which endpoints are used.
- Variables: hourly `temperature_2m`, `relative_humidity_2m`, `wind_speed_10m`, and the
  radiation components needed for MRT (`shortwave_radiation`, `direct_radiation`,
  `diffuse_radiation`, and the best available longwave/terrestrial term); daily
  `temperature_2m_mean` (for EHF/ECF) plus `temperature_2m_max`/`min`.
- Each output day carries `is_forecast = true` when its weather was preliminary/forecast at
  retrieval (roughly the last ~5 days), else `false`. Run-level `data_source`, `retrieved_at`,
  and `thermofeel_version` go in the JSON metadata (and README), not per row.

**Computation.**

- Convert Open-Meteo's Celsius to thermofeel's Kelvin carefully and validate against
  thermofeel's test values.
- Compute every index hourly, then reduce to one value per day: the daily maximum of each
  heat-stress index (daily minimum for wind chill). Record the local hour at which the
  headline index (WBGT) peaks.
- No-radiation indices (must be exact): Heat Index (adjusted + simplified), Humidex,
  Apparent Temperature, Normal Effective Temperature, WBGT-simple, Wind Chill, KNMI Heat
  Force (0–10).
- Radiation-dependent indices (best-effort, documented): UTCI and Liljegren WBGT need mean
  radiant temperature, which needs radiation components and the cosine of the solar zenith
  angle. thermofeel 2.x no longer computes solar zenith (it expects `earthkit-meteo` to), so
  compute cos(solar zenith) from lat/lon/UTC time with a documented solar-position routine or
  `earthkit-meteo`. Map Open-Meteo radiation variables onto thermofeel's MRT inputs and
  document every approximation where an ERA5 flux has no clean Open-Meteo equivalent. Where
  radiation is genuinely unavailable for a city/day, emit these indices as null rather than
  guessing; on the default US-cities/Open-Meteo path they should always be present.
- EHF / ECF: use thermofeel's implementation and defer to its exact formulae. Per output day
  this needs the daily-mean-temperature series (3-day current + prior 30-day = 33-day
  lookback) and a per-city climatological percentile. Reference definitions (confirm against
  thermofeel): EHI_sig = (3-day mean ending today) − T95; EHI_accl = (3-day mean) − (prior
  30-day mean); EHF = max(0, EHI_sig) × max(1, EHI_accl); ECF is the cold analogue using T05.

**Climatology baseline (committed, one-time build).** A committed script (e.g.
`build_climatology.py`) pulls 1991–2020 daily mean temperature per city centroid from the
Open-Meteo ERA5 archive and computes the whole-period 95th and 5th percentiles. Both the script
and its output table are committed (e.g. `climatology.csv`:
`city, state, lat, lon, t95_c, t05_c, source, period, method`). The runtime reads the table
and never recomputes climatology.

**Output** — two artifacts per run, written per bond's output-path convention. This schema is
frozen: it is the contract the SPA will build against.

1. Primary — long-format CSV, one row per (city, date) for the 30-day window. Columns:
   - Identifiers/flags: `city, state, lat, lon, date, is_forecast, wbgt_peak_hour_local`
   - Drivers echoed: `t2m_c` (air temp at the WBGT peak hour), `rh_pct`, `wind_10m_ms`,
     `shortwave_wm2` (nullable), `t2m_mean_c` (daily mean used by EHF/ECF)
   - Indices: `utci_c` (nullable), `utci_category`, `wbgt_c` (Liljegren, nullable),
     `wbgt_simple_c`, `wbgt_work_category`, `heat_index_c`, `heat_index_category`,
     `humidex_c`, `apparent_temp_c`, `net_c`, `heat_force`, `wind_chill_c`, `ehf`, `ecf`
   - `utci_category`: the standard 10-point UTCI thermal-stress scale.
     `heat_index_category`: NWS bands (Caution / Extreme Caution / Danger / Extreme Danger).
     `wbgt_work_category`: ISO 7243 / OSHA work-rest band under a documented default workload
     and acclimatisation class (e.g. moderate metabolic rate, acclimatised worker), stated in
     the Modelfile's validity-domain annotation and the README, and noted as configurable
     later.
2. Convenience JSON shaped for the SPA:

   ```json
   {
     "generated_at": "...", "date": "YYYY-MM-DD", "data_source": "...",
     "thermofeel_version": "2.3.0", "window_days": 30,
     "cities": [
       { "city": "...", "state": "...", "lat": 0.0, "lon": 0.0,
         "today": { "...": "all indices for date" },
         "history": [ { "date": "...", "...": "all indices; 30 entries, oldest to newest" } ] }
     ]
   }
   ```

**Validation.** A committed check demonstrates that the no-radiation indices match
thermofeel's expected/test values within tolerance, and that UTCI and Liljegren WBGT fall in
physically plausible ranges under the documented radiation/MRT assumptions.

**Documentation (README).** The climatology source, period, and method with citation; the WBGT
workload assumption; the Open-Meteo endpoints and variables used; the radiation → MRT mapping
and every approximation; and both determinism semantics:

- Deterministic given `date`, the city list, and the upstream Open-Meteo data as of
  retrieval. The most recent ~5 days are preliminary/forecast and can be revised, so re-running
  the same `date` later may shift them slightly. `is_forecast` and `retrieved_at` make this
  auditable.
- Whole-window-recomputed-each-run: every run recomputes all 30 days with the current code, so
  the visible trend reflects the current code version, not whatever code ran on each historical
  day. This is intentional.

### Out of scope

- The three downstream damage-function models (labour-productivity capacity loss, heat
  mortality/health risk, cooling-energy demand) and any Flow wiring. They will be sibling
  bundles later.
- The SPA itself (its contract — the output schema above — is in scope).
- Any change to Model Home platform code. If the platform needs a change to run this bundle,
  surface it; don't implement it here.

## Acceptance criteria

- **AC-1** — `modelhome/thermofeel-bundles` exists with top-level `.gitignore`,
  `.dockerignore`, `LICENSE` (MIT), `README.md`, `CLAUDE.md`, and a `thermal-indices/`
  subfolder, all matching `QuantLib-bundles` conventions.
- **AC-2** — `thermal-indices/` contains `Modelfile.toml`, `Dockerfile`, `runner.py`, a sample
  input JSON, the baked-in city list, the committed `climatology.csv`, and the committed
  climatology-build script.
- **AC-3** — `python thermal-indices/runner.py thermal-indices/<sample_input>.json` runs end to
  end and writes the CSV + JSON with the schema above.
- **AC-4** — `docker build` from the bundle folder succeeds and `docker run` reproduces the
  same outputs (given network egress).
- **AC-5** — The no-radiation indices match thermofeel's expected/test values within
  tolerance; a committed check demonstrates this. UTCI and Liljegren WBGT fall in physically
  plausible ranges with the radiation/MRT assumptions documented.
- **AC-6** — EHF/ECF are populated for all 30 output days using the committed 1991–2020
  T95/T05 baseline and the 33-day daily-mean lookback.
- **AC-7** — With no `date` supplied, the model defaults to the current UTC date; with no
  `cities` supplied, it uses the baked-in city list. The scheduled run therefore needs no
  parameters.
- **AC-8** — Pasting the `thermal-indices/` subfolder GitHub URL into
  `http://localhost:5173/models/new/repo` creates a working model whose run produces the
  expected artifacts.
- **AC-9** — README documents the climatology source/period/method with citation, the WBGT
  workload assumption, the Open-Meteo endpoints and variables used, the radiation → MRT mapping
  and any approximations, and the two determinism semantics.

## Constraints and dependencies

- **Network egress at run time.** Unlike `bond` (fully offline), this model fetches from
  Open-Meteo when it runs. Confirm the Model Home run environment permits outbound network from
  model containers. If it does not, the architecture changes to weather-as-declared-input with
  the fetch moved into the scheduled trigger or an upstream fetch model. Raise this in the plan
  before implementing.
- **Pinned dependencies** in the Dockerfile, in bond's base and pinning style:
  `thermofeel==2.3.0` (changed from 2.2.0 at plan review), numpy, an HTTP client, pandas, and `earthkit-meteo` only if it is used
  for solar geometry.
- **Licensing.** The bundle repo is MIT; thermofeel (Apache-2.0) is pip-installed, not
  vendored.
- **Sample input** uses a fixed recent past date (not "today") so sample runs are stable, and
  3–5 cities for speed. The README notes the sample still requires network access.
- **Reproducibility.** Given `date`, the 63-day window and all derived values are determined.
  No run-time randomness or wall-clock dependence beyond the `date` default and the
  `retrieved_at` stamp.
- **Depends on** Open-Meteo's forecast and ERA5 archive APIs, thermofeel's published package,
  and `modelhome/QuantLib-bundles` as the structural template.

## General guidance

- Before you write the plan, ask any questions you need to in order to best implement the brief
