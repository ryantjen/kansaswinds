# Experiments

Experiment definitions are immutable JSON inputs to `analysis.run_experiment`.
The first definition intentionally keeps the existing full-Eastern, 98-zone
ReEDS resolution. Within Kansas, the optimizer can distinguish only western
zone `p52` from eastern zone `p53`.

An optional `launcher` object controls whether the Streamlit launcher exposes a
template and which fixed run sizes it permits. It does not expose arbitrary
solver, policy, topology, or cost edits. For sampled runs, the launcher writes a
unique generated copy of the experiment and model configuration under
`remote_jobs/<run-id>/`; checked-in templates remain unchanged.

Validate the definition and print its exact workflow command without writing:

```bash
python -m analysis.run_experiment experiments/reeds_zonal_2019.json --dry-run
```

Run the upstream PyPSA-USA solve and collect its outputs:

```bash
python -m analysis.run_experiment experiments/reeds_zonal_2019.json --execute
```

Or collect a solved network produced elsewhere:

```bash
python -m analysis.run_experiment experiments/reeds_zonal_2019.json \
  --solved-network path/to/solved-network.nc
```

The runner never changes the mathematical model. It calls the pinned
PyPSA-USA `solve_network` rule so that upstream land-use, policy, reserve, and
link constraints remain active. Real runs are written to `results/runs/` and
are ignored by Git.
