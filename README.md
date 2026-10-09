# Kansas Wind Potential

A Next.js and TypeScript scrollytelling project for exploring potential wind farm locations in Kansas.

## Getting started

```bash
npm install
npm run dev
```

The interactive map reads `public/data/kansas_wind.geojson`, containing 4,154 Kansas point sites from the NREL WIND Toolkit Power Data Site Index. Regenerate it from the source CSV with:

```bash
python analysis/process_wind.py path/to/wtk_site_metadata.csv
```

The map colors sites by modeled `capacity_factor` or average `wind_speed_mps`. Each displayed grid cell is centered on one source site and carries that site's original value; the display does not interpolate or manufacture values between sites.

## Wind data source

- Dataset: NREL WIND Toolkit Power Data Site Index
- DOI: https://doi.org/10.7799/1329290
- Catalog: https://data.nlr.gov/submissions/54
- Coordinate reference system: WGS 84 longitude/latitude (`EPSG:4326`)
- Coverage used here: the 4,154 source rows whose `State` value is `Kansas`
- Important: values are modeled site estimates, not measurements or guaranteed project output.

## Modeled annual output

The site calculates the Kansas technical-resource estimate as:

```text
annual MWh = sum(site capacity MW × site capacity factor × 8,760 hours)
```

For the 4,154 Kansas records, this produces 61,230 MW of modeled capacity, a 45.84% capacity-weighted factor, 28,067 MW of average output, and 245.87 TWh of annual energy. The calculation uses the dataset's `capacity_mw` directly and does not multiply by `fraction_of_usable_area` a second time.

The map and calculations include all 4,154 modeled Kansas sites. The site does not apply additional protected-land, residential-setback, high-slope, or minimum-capacity-factor exclusions.

For context, the U.S. Energy Information Administration reports 41,258,210 MWh (41.258 TWh) of Kansas retail electricity sales in 2024. The modeled annual wind output is about 5.96 times that benchmark: https://www.eia.gov/electricity/state/Kansas/

Reserved data paths:

- `public/data/transmission.geojson`
- `public/data/exclusions.geojson`

## Grid context map

The second map reads `public/data/kansas_grid.geojson`, a browser-ready export
of two complementary layers from the unsolved PyPSA-USA Kansas baseline:

- A provisional synthetic AC topology containing every non-zero 115 kV-and-above
  branch that touches Kansas, plus its co-located network nodes.
- The two Kansas ReEDS planning zones, neighboring connected zones, ten modeled
  transfer interfaces, and eleven aggregated generation centers. Wind and solar
  are always included; conventional generation is included at 250 MW or larger.

The map opens on the detailed topology and lets the reader switch to the
planning-interface representation. The detailed network is useful for tracing
connectivity but is synthetic and must not be presented as surveyed utility
infrastructure. The interface layer is the active model representation.

Regenerate the file after refreshing the baseline analysis outputs with:

```bash
npm run data:grid
```

Interface width represents modeled directional transfer capacity, not observed
power flow. Generator markers are regional aggregates at zone centers, not
individual plant coordinates. Annual generation and branch flow remain
unavailable until the network is solved or historical observations are joined.

## Generation, flow, and congestion data path

Keep observed and modeled values separate:

1. **Observed annual generation:** ingest the matching-year EIA-923 annual file
   and aggregate net generation by plant and prime mover. Join EIA-860 plant
   coordinates for map placement. For the current baseline, use 2019 data.
2. **Observed interchange:** EIA-930 supplies hourly transfers between balancing
   authorities. It is useful for SPP boundary context but does not publish flow
   on individual AC lines.
3. **Observed congestion:** download SPP Real-Time Balancing Market binding
   constraints, effective limits, and bus/location LMP files. Rank facilities by
   binding intervals, shadow-price dollars, and the LMP congestion component.
   Constraint names will need a maintained crosswalk to map features; not every
   monitored element can be safely or unambiguously geolocated.
4. **Modeled branch flow:** run hourly PyPSA dispatch on a topology detailed
   enough for the question. Export generator dispatch, branch `p0`/`p1`, bus
   marginal prices, and constraint duals. For each branch compute signed net
   MWh, absolute MWh, maximum utilization, hours above 90%/95% of rating, and
   congestion rent. The current 98-zone transport model can answer regional
   interface questions; a county ReEDS or clustered TAMU case is required for
   finer spatial claims.

Annual branch throughput is not a capacity field. For hourly snapshots it is
`sum(abs(flow_mw) * snapshot_weight_hours)`; retain signed net MWh separately so
heavy two-way use is not canceled out. Validate modeled generation against
EIA-923 and modeled price/constraint patterns against SPP before describing a
location as a congestion center.

Official starting points:

- EIA-923: https://www.eia.gov/electricity/data/eia923/
- EIA-930 API browser: https://www.eia.gov/opendata/browser/electricity/rto/interchange-data
- SPP real-time market data: https://portal.spp.org/groups/real-time-balancing-market
- SPP annual State of the Market reports: https://www.spp.org/markets-operations/market-monitoring/state-of-the-market/

## Experiments, tests, and result inspection

The experiment tooling initially uses the same coarse 98-zone ReEDS model as
the baseline. Kansas therefore has two candidate planning zones: `p52`
(western Kansas) and `p53` (eastern Kansas). Results at this stage cannot rank
counties, substations, or parcels.

Validate the experiment definition without starting a solve:

```bash
python -m analysis.run_experiment experiments/reeds_zonal_2019.json --dry-run
```

From the PyPSA-USA environment, run the existing upstream optimization and
collect a timestamped result bundle:

```bash
python -m analysis.run_experiment experiments/reeds_zonal_2019.json --execute
```

The runner records the experiment and model configuration, input hashes,
software versions, Git state, expected solver settings, summary metrics,
generator output, branch flows, LMPs, and numerical consistency flags. It does
not reimplement or modify the core mathematical model.

Run the lightweight mathematical and result-contract tests with the standard
library test runner:

```bash
python -m unittest discover -s tests -v
```

Install and open the multipage dashboard with:

```bash
python -m pip install -r requirements-dashboard.txt
streamlit run dashboard/app.py
```

The **Results** page is read-only and never contacts GCP. Tracked examples under
`results/examples/` are prominently labeled synthetic. The separately labeled
**Launch experiment** and **Job status** pages can start the configured VM,
submit a checked-in experiment, monitor logs and its safety lease, validate a
downloaded bundle, and stop the VM. Actual model runs are written to the
Git-ignored `results/runs/`; local job records are kept in `results/jobs/`.

### GCP launcher workflow

The launcher is pinned to project `kansas-winds`, VM `kansas-psypa`, and zone
`us-central1-a`. It uses your existing authenticated `gcloud` CLI profile; no
cloud credential is stored in the repository or browser.

1. Run `gcloud auth login` and `gcloud config set project kansas-winds` outside
   the app if the local CLI is not already authenticated.
2. Open **Launch experiment** and choose **Detect VM setup**. The wizard starts
   a stopped VM temporarily, locates the checkout, verifies the named PyPSA
   environment, and restores the VM's prior stopped state.
3. Save the detected remote checkout. Only non-secret connection metadata is
   written to the Git-ignored `.kansaswinds/launcher.json`.
4. Commit the local work, push it to `origin/main`, and ensure the PyPSA-USA
   submodule matches the recorded commit. The launcher refuses dirty, detached,
   or unpushed code and never commits or pushes for you.
5. Select a checked-in template and choose 24-hour smoke, 168-hour pilot, or
   8,760-hour production. Review the exact commit, temporal scope, VM state,
   resolution, and lease before confirming the billable action.
6. Monitor **Job status**. The detached remote worker survives closing the
   dashboard, permits only one active solve, and installs a 2-hour, 6-hour, or
   24-hour shutdown lease. Failed solves retain a 60-minute diagnostic window.
   If a safety lease stopped the VM while the dashboard was closed, use the
   explicit **Start VM and reconnect** action to recover status or results under
   a fresh lease.

Smoke and pilot runs annualize sampled chronology and are visibly marked as
non-decision-grade. The launcher changes the snapshot count only; it preserves
the pinned PyPSA-USA workflow and mathematical formulation.

Run the controlled live preflight without submitting PyPSA with:

```bash
python -m analysis.gcp_acceptance
```

It starts the VM only when needed, checks the repository, environment,
resources, and shutdown authority, and restores an initially stopped VM in a
`finally` path.

See [`experiments/README.md`](experiments/README.md) and
[`results/README.md`](results/README.md) for the data contracts.

## Non-goals for v0.1

- Grid optimization
- Nationwide model
- Hourly dispatch
- Storage
- Transmission expansion

## PyPSA-USA research baseline

The separate, reproducible power-system baseline is documented in
[`pypsa/README.md`](pypsa/README.md). It builds an unsolved 2019 Eastern
Interconnection network first; it does not yet add hypothetical wind,
transmission expansion, or congestion optimization. The full data-model build
is intended for a 32–64 GB Linux machine, with 64 GB strongly recommended.
Build instructions and resource estimates are kept in the same PyPSA README.
