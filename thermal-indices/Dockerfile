# to build and run from your local machine (build context is this thermal-indices/
# folder, which is also what Model Home uses when the model is added from
# github.com/modelhome/thermofeel-bundles/tree/main/thermal-indices):
#   cd thermal-indices && docker build -t thermofeel-thermal-indices:local .
#   docker run --rm thermofeel-thermal-indices:local        # uses sample_input.json
#   docker run --rm -v "$PWD/run:/run" thermofeel-thermal-indices:local \
#       /run/heat_request.json /run/heat_summary.output.json > run/heat_indices.output.json
# The model fetches weather from Open-Meteo, so the container needs network access.

FROM python:3.12-slim

WORKDIR /app

# thermofeel is pure Python on numpy. tzdata supplies the time-zone database that
# python:3.12-slim lacks (used to group hours into each city's local days).
# Pin for reproducibility.
RUN pip install --no-cache-dir -U pip \
    && pip install --no-cache-dir thermofeel==2.3.0 numpy==2.5.3 tzdata==2026.4

COPY runner.py cities.json climatology.csv sample_input.json ./

ENTRYPOINT ["python", "runner.py"]

# irl the input/output paths come from the Modelfile; for local testing we
# default to the bundled sample input.
CMD ["sample_input.json"]
