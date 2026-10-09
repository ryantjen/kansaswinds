# Automated checks

Run every check with:

```bash
python -m unittest discover -s tests -v
```

The suite verifies:

- signed, snapshot-weighted MW-to-MWh integration;
- separate net energy and absolute two-way branch throughput;
- utilization thresholds, including the zero-capacity edge case;
- a hand-calculated 75% generator capacity factor;
- a balanced two-bus power-flow example;
- rejection of missing or negative snapshot weights;
- generator, branch, congestion-rent, LMP, and nodal-balance exports against a
  tiny PyPSA-shaped network whose answers can be calculated by hand;
- rejection of ambiguous provenance and partial result folders; and
- consistency between the experiment definition and the initial `p52`/`p53`
  ReEDS-zone resolution;
- run-size configuration overlays, lease calculations, state transitions, Git
  reproducibility gates, fixed remote command construction, one-job locking,
  shutdown failure handling, and result checksum rejection;
- mocked GCP stopped/running, SSH, environment, dirty-repository, and transfer
  behavior; and
- Streamlit `AppTest` coverage for comparison, preview/confirmation, monitoring,
  logs, and failure warnings without starting a VM.

These tests do not claim that synthetic examples are model results, and they do
not replace PyPSA-USA's upstream optimization tests.
