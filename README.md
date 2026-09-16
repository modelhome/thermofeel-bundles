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

The first bundle, `thermal-indices/` (daily US heat stress), is in progress.

## Quick start

```bash
# the build context is the bundle folder, the same one Model Home builds from
cd <bundle>
docker build -t thermofeel-<bundle>:local .
docker run --rm thermofeel-<bundle>:local
```

Or, when creating a new model on Model Home, paste the bundle folder's GitHub
URL (for example `https://github.com/modelhome/thermofeel-bundles/tree/main/<bundle>`)
into the "classic import" option.

See [`CLAUDE.md`](./CLAUDE.md) for the conventions every bundle follows, and
how features are briefed, planned, and built.
