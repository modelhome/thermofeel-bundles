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

## Task list

1. Create `modelhome/thermofeel-bundles` on GitHub (public) and push `main`
   (boilerplate + vendored `feat`). Confirm with John first.
2. Build `thermal-indices/` through `feat` (brief 0001).
3. Register `thermal-indices/` on Model Home from its subfolder URL, run it, and
   put it on a daily schedule.
4. Later siblings, composed through a Flow: labour productivity, heat mortality,
   cooling-energy demand.
