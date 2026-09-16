# thermofeel-bundles

Standalone [Model Home](https://modelhome.run) model bundles built on
[thermofeel](https://github.com/ecmwf/thermofeel), ECMWF's operational library
for human thermal-comfort and heat-stress indices. Each subfolder is a
self-contained model: a `Modelfile.toml`, a `Dockerfile`, a `runner.py`, and
sample inputs.

This is not a fork of thermofeel — thermofeel (Apache-2.0) is installed as a
pinned pip package inside each bundle's image, not vendored here.

## Bundles

| Bundle | Model | Inputs → Outputs |
|---|---|---|
| [`thermal-indices/`](./thermal-indices) | Daily US heat stress: thermofeel indices for 89 cities over the last 30 days, from Open-Meteo weather | optional date + cities (empty for today) → per-city daily UTCI, WBGT, heat index, humidex, apparent temperature, NET, wind chill, heat force, EHF/ECF and risk bands; plus a per-city today + history summary |

## Quick start

```bash
# the build context is the bundle folder, the same one Model Home builds from
cd thermal-indices
docker build -t thermofeel-thermal-indices:local .
docker run --rm thermofeel-thermal-indices:local   # needs network access
```

Or run the runner directly:

```bash
# from the repository root
mkdir -p run
uv run --no-project --python 3.12 --with thermofeel==2.3.0 --with numpy==2.5.3 \
    --with tzdata==2026.4 python thermal-indices/runner.py thermal-indices/sample_input.json \
    run/heat_summary.output.json > run/heat_indices.output.json
```

Or, when creating a new model on Model Home, paste the bundle folder's GitHub
URL (for example `https://github.com/modelhome/thermofeel-bundles/tree/main/thermal-indices`)
into the "classic import" option.

Each bundle's README covers its inputs, outputs, data sources, and assumptions
([`thermal-indices/README.md`](./thermal-indices/README.md)). See
[`CLAUDE.md`](./CLAUDE.md) for the design notes, the conventions every bundle
follows, verified results, and how features are briefed, planned, and built.
