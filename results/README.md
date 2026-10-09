# Experiment results

This directory has two intentionally separate areas:

- `examples/` contains small, tracked **synthetic examples** used to test and
  demonstrate the read-only dashboard. They are not PyPSA results and must not
  be cited as evidence.
- `runs/` contains local outputs from real PyPSA-USA experiments. It is ignored
  by Git because solved networks and hourly results can be large.
- `jobs/` contains the launcher's local reconnect records. It is ignored by Git
  and contains identifiers and status only, never GCP credentials.

Every completed run must include `manifest.json`, `summary.json`,
`generators.csv`, `branches.csv`, `bus_prices.csv`, and `violations.csv`.
`manifest.json` must explicitly classify the data as `model_output`,
`model_input`, or `synthetic_example`. The dashboard rejects ambiguous or
partial result folders.

Launcher-produced manifests also identify full-year versus sampled chronology,
the exact main-repository and PyPSA-USA submodule commits, VM identity,
environment versions, input hashes, timestamps, and checksums for every required
downloaded output. A download is rejected if a required table is absent or any
declared checksum differs.
