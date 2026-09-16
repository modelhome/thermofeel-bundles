# thermofeel-bundles

Standalone Model Home **model bundles** that wrap
[thermofeel](https://github.com/ecmwf/thermofeel) computations. Each bundle is a
self-contained folder with everything Model Home needs to run one model: a
`Modelfile.toml`, a `Dockerfile`, a `runner.py`, and sample input(s).

This repo is **not** a fork of thermofeel. thermofeel (Apache-2.0) is pulled in
as a pinned pip package inside each bundle's Docker image, so this MIT repo holds
only the Model Home packaging layer and never redistributes thermofeel's code.
Keep it that way.

```
thermofeel-bundles/
  CLAUDE.md                 ← you are here
  README.md
  LICENSE                   (MIT)
  .claude/skills/feat/      ← vendored feat skill (brief → plan → PR workflow)
  docs/features/            ← feature briefs (NNNN-name.md)
  docs/plans/               ← implementation plans, one per brief
  <bundle>/                 ← one self-contained model per folder
```

The planned gallery is a set of daily damage-function models. The first bundle
computes thermal indices; later siblings (labour productivity, heat mortality,
cooling-energy demand) consume its output and are composed with it through a
Model Home Flow.

---

## The template: `QuantLib-bundles/bond/`

[`modelhome/QuantLib-bundles`](https://github.com/modelhome/QuantLib-bundles),
especially its `bond/` bundle, is the authoritative template for this repo.
Read it before starting a bundle and mirror it. Consistency with `bond` matters
more than any local preference:

- **`Modelfile.toml` keys.** `name`, `description`, `run`, `image`, `args`,
  `[resources]`, `[[inputs]]` with a documented `[inputs.schema]` (every
  property has a plain-language `description`; the schema's `default` is what
  the platform offers as the "Example to paste", so it must stay runnable), and
  `[[outputs]]` with `[outputs.schema]`. Rationale the schema can't express goes
  in TOML comments beside it — units, validity domain, determinism.
- **Runner I/O contract.** Input JSON file path(s) arrive as positional args.
  The result JSON goes to **stdout** and nothing else does — logs go to stderr.
  The Modelfile's `run` redirects stdout to `run/<output>.output.json`.
- **`required = []` and defaults in the runner.** A present-but-empty value
  (`""` or `null`) falls back the same way a missing key does, so the model runs
  standalone or composed.
- **Dockerfile.** `python:3.12-slim`, `WORKDIR /app`, exact `==` pins installed
  in one `pip install --no-cache-dir` layer, `COPY` paths relative to the bundle
  folder, `ENTRYPOINT ["python", "runner.py"]`, and a `CMD` naming the bundled
  sample input so a bare `docker run` works.

## Model Home platform facts (verified against the platform code)

- **Build context is the bundle subfolder.** Adding a model from
  `github.com/modelhome/thermofeel-bundles/tree/main/<bundle>` promotes that
  folder to the build-context root, exactly like `cd <bundle> && docker build .`.
  Never use repo-relative `COPY <bundle>/...` paths; the on-platform build fails.
- **Every output is a JSON file.** The platform collects only
  `/run/<name>.output.json` for each declared `[[outputs]]` name and parses it
  with `json.loads`. Any other file a runner writes (a CSV, a PNG) is discarded
  on-platform. One output can come from the stdout redirect; further outputs are
  passed to the runner as `{output:NAME}` args, which resolve to
  `/run/NAME.output.json`.
- **Model containers have outbound network access.** No NetworkPolicy restricts
  the runs namespace (the only policy protects Postgres and Redis), and existing
  models already download data at run time. A bundle that fetches at run time
  must still fail clearly (non-zero exit, reason on stderr) when a fetch fails.
- **A schedule re-sends a fixed input.** A scheduled run passes the same stored
  input every time, so anything that should change per run (such as "today")
  must be defaulted inside the runner, not baked into the schedule's input.

## Conventions for every bundle

- **Read the upstream source and tests before coding.** Take function
  signatures, units, and formulae from thermofeel's source and test suite, not
  from its README. thermofeel functions mostly take and return **Kelvin**; most
  weather APIs return **Celsius**. Unit slips are the classic bug here — convert
  at one boundary and name variables with their unit (`t2_k`, `t2_c`).
- **Validate against thermofeel's own expected values.** Each bundle commits a
  check that runs its index code on thermofeel's test cases and compares with
  thermofeel's expected-value tables.
- **Pin everything** in the Dockerfile. Don't add a dependency when numpy, the
  standard library, or an existing pin will do.
- **Readable over clever.** Inputs are small (tens of cities × weeks × hours);
  vectorise where thermofeel already does, otherwise favour plain code.
- **No emojis** in source files.

### Determinism for bundles that fetch data

A bundle that pulls data at run time is deterministic given its inputs **and the
upstream data as of retrieval**, the same category as a market-data pull. State
this in the bundle's README and Modelfile comments, and make it auditable:

- stamp `retrieved_at`, the data source, and library versions in the output
  metadata;
- flag any values that the upstream source may still revise (for example
  preliminary or forecast weather);
- introduce no randomness and no wall-clock dependence beyond an explicit
  "today" default and the `retrieved_at` stamp.

## How features are built: `feat`

Features are developed from versioned briefs with the vendored
[`feat`](./.claude/skills/feat/SKILL.md) skill, so the brief, the plan, and the
implementation land together in one pull request:

1. `/feat create <name>` scaffolds `docs/features/NNNN-<name>.md`. Hand-written
   briefs in the same template are fine.
2. `/feat plan <name>` writes `docs/plans/NNNN-<name>.md` and stops. John reviews
   and revises the plan before anything is built.
3. `/feat run <name>` implements the approved plan on `feat/NNNN-<name>` and
   stops at the pull request. It never merges, releases, or deploys.

Repo-wide conventions live in this file; briefs reference them rather than
restating them.

## The `thermal-indices/` bundle

**US Daily Heat Stress.** Given an optional `date` and `cities`, fetches 62 days of
hourly Open-Meteo weather per city, computes thermofeel 2.3.0's heat-stress
indices hourly, reduces them to local-day maxima (wind chill: minimum), and
reports the last 30 days with Excess Heat / Excess Cold Factors against a
committed 1991-2020 ERA5 climatology. Brief: `docs/features/0001-thermal-indices.md`;
plan with every decision and its reasoning: `docs/plans/0001-thermal-indices.md`.
User-facing documentation: [`thermal-indices/README.md`](./thermal-indices/README.md).

```
thermal-indices/
  Modelfile.toml          two JSON outputs; semantic annotations
  Dockerfile              python:3.12-slim + thermofeel/numpy/tzdata pins
  runner.py               the model
  sample_input.json       2026-08-15, Phoenix/Houston/Chicago/Minneapolis
  cities.json             89 cities: GNIS coordinates, IANA time zone, why included
  climatology.csv         per-city T95/T05 (built once by build_climatology.py)
  build_climatology.py    one-time ERA5 build via Copernicus CDS (not in the image)
  check_indices.py        validation (not in the image)
  README.md
```

### Design notes

- **Two JSON outputs, not CSV.** Model Home keeps only `<name>.output.json`, so
  the long-format table is `heat_indices` (`{metadata, columns, rows}`) and the
  per-city view is `heat_summary`. The CSV is written beside the summary for
  off-platform use only. `heat_indices` comes from the stdout redirect;
  `heat_summary` is an `{output:heat_summary}` arg.
- **Input default is `{}`.** Schema `default = {}` makes the "Example to paste"
  what a daily schedule should send. `date` defaults inside the runner to the
  UTC date; `cities` to `cities.json`.
- **ERA5 first, forecast for the tail.** The archive (`models=era5`) supplies
  every day it fully covers; the forecast endpoint supplies the rest (~7 days)
  and those rows get `is_forecast = true`. Keeps EHF/ECF like-for-like with the
  ERA5 climatology. A day neither source covers fails the run.
- **Units at one boundary.** `hourly_indices` takes Celsius, calls thermofeel in
  Kelvin, returns Celsius. `check_indices.py` exercises that exact function.
- **Radiation.** `*_instant` Open-Meteo variables; cos(solar zenith) from NOAA's
  equations; downward longwave estimated (Prata 1996 + Unsworth & Monteith 1975),
  albedo 0.20, surface emissivity 0.97. Only UTCI depends on the estimates. The
  measured alternative is CDS ERA5 `surface_thermal_radiation_downwards` (lags
  ~5 days, needs a key in the container).
- **EHF/ECF are labelled with the last day of the 3-day mean** (thermofeel labels
  the first); daily mean = (Tmin + Tmax) / 2 in both runtime and climatology.
  62 fetched days = 30 output + 33 lookback - 1.
- **Work/rest bands** from the NIOSH REL (acclimatized, moderate work 300 W, rest
  117 W). Not configurable yet.
- **Open-Meteo budget.** Eight hourly variables keep each request at minimum
  call weight; a full run is ~178 requests, ~450 weighted calls (free tier:
  10,000/day, non-commercial). A 30-year climatology through Open-Meteo would
  cost ~70,000, which is why the build uses Copernicus CDS.
- **Compact JSON outputs** (no indentation), unlike bond: 2,670 rows would be
  ~2 MB per output indented, ~1.3 MB compact.

### Modelfile

Mirrors `bond`: `run` redirects stdout to `run/heat_indices.output.json`,
`args = ["{input:heat_request}", "{output:heat_summary}"]`. Adds the Modelfile
annotation fields Model Home validates (`determinism`, `expected_runtime`,
`validity_domain`, `not_for`, `provenance`, per-property `unit`). Model Home's
validator requires a *string* `type` on every required key, so nullable columns
declare their base type and say when they can be null in the description.
Validate from the `modelhome` repo with
`uv run python -m orchestration.modelfile validate <path>/thermal-indices/Modelfile.toml`
(currently OK, no annotation warnings).

### Verified results (2026-09-16)

- `check_indices.py`: all checks pass. thermofeel 2.3.0 expected values through
  `hourly_indices`: WBGT simple, apparent temperature, NET, wind chill, Liljegren
  WBGT, heat force and UTCI exact (max |diff| <= 3e-12 degC); heat index 1.9e-3
  and humidex 3.4e-3 degC (dew-point round trip). NWS chart 90 degF / 60% ->
  99.7 degF; Environment Canada -20 degC / 30 km/h -> -32.57; solar zenith within
  0.006 degrees of pvlib's NREL SPA.
- Sample (2026-08-15, 4 cities, **placeholder** climatology): 120 rows; Phoenix
  WBGT 34.5 degC and UTCI 44.7 degC on 2026-08-15; Houston heat index "Danger".
- Full default run (2026-09-16, 89 cities, **placeholder** climatology):
  3 min 13 s, 2,670 rows, 7 forecast days per city, every output check passes.
- Docker build and run (default CMD and the Modelfile's mounted layout) produce
  rows identical to the local run.
- **Not yet verified:** the real `climatology.csv` (needs a CDS key), EHF/ECF
  values from it, and the Model Home import (AC-8).

### Task list

1. Build `climatology.csv` with `build_climatology.py` (needs John's CDS key in
   `~/.cdsapirc`), sanity-check the thresholds, commit it.
2. Re-run the sample, the full default run, `check_indices.py --output` and the
   Docker build with the real table; update the verified results above.
3. AC-8: add the model on the local Model Home stack from the branch subfolder
   URL and run it with `{}`; check the run page copes with ~2.6 MB of output.
4. Mark the PR ready once 1-3 pass; John merges.
5. After merge: register on Model Home from `main` and put it on a daily
   schedule with `{}`.
6. Follow-ups: configurable WBGT workload/acclimatization; measured longwave;
   the labour-productivity, heat-mortality and cooling-demand sibling bundles
   consuming `heat_indices` through a Flow.

## Task list

1. ~~Create `modelhome/thermofeel-bundles` on GitHub and push `main`.~~ Done 2026-09-16.
2. Finish `thermal-indices/` (brief 0001): see that bundle's task list above.
3. Later siblings, composed through a Flow: labour productivity, heat mortality,
   cooling-energy demand.
