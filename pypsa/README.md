# Kansas PyPSA-USA baseline

This is the active power-system research path for the project. It builds one
coarse, unsolved regional baseline and stops there.

## Active baseline

| Setting | Choice |
| --- | --- |
| Upstream source | PyPSA-USA submodule pinned at `fbe5883f57563ef038eea777cb2f8a114e49084c` |
| Geography | Complete Eastern Interconnection |
| Transmission model | ReEDS/NARIS transport topology and interface limits |
| Spatial resolution | 98 ReEDS zones |
| Kansas zones | `p52` and `p53` |
| Planning, demand, and weather year | 2019 |
| Time resolution | All 8,760 hourly snapshots |
| Demand | Historical EIA-930 profile, spatially distributed by PyPSA-USA |
| Renewable profiles | Atlite with the prebuilt 2019 ERA5 cutout |
| Solver | HiGHS is configured, but no optimization is run |

The complete Eastern network preserves Kansas imports and exports. The 98-zone
ReEDS model is intentionally coarse: it represents constrained regional
interfaces, not individual Kansas substations or every physical transmission
line.

The only project-owned files needed for this path are:

- `pypsa/config.kansas-baseline.yaml` — complete baseline configuration.
- `analysis/kansas_baseline.py` — post-build Kansas inspection and map.
- `external/pypsa-usa` — pinned upstream workflow; keep it unmodified.

## Build the unsolved baseline on Linux

Use 64 GB RAM if available. A 32 GB machine is a borderline, best-effort
option because two upstream preprocessing rules each declare a 30,000 MB
memory requirement. The commands below use one core so jobs and Atlite workers
remain serialized and memory use is minimized.

Run these commands from the root of a fresh clone of this repository.

### 1. Install host tools and micromamba

```bash
sudo apt-get update
sudo apt-get install --yes git curl ca-certificates bzip2 tmux

mkdir -p "$HOME/.local"
curl -Ls https://micro.mamba.pm/api/micromamba/linux-64/latest \
  | tar -xj -C "$HOME/.local" bin/micromamba

export PATH="$HOME/.local/bin:$PATH"
export MAMBA_ROOT_PREFIX="$HOME/micromamba"
eval "$(micromamba shell hook --shell bash)"
```

### 2. Initialize and verify the pinned upstream source

```bash
git submodule update --init --recursive

test "$(git -C external/pypsa-usa rev-parse HEAD)" = \
  "fbe5883f57563ef038eea777cb2f8a114e49084c"

git -C external/pypsa-usa diff --exit-code
```

Do not run `init_pypsa_usa.sh` and do not copy
`workflow/repo_data/config/` over `workflow/config/`. The pinned submodule
already contains the matching workflow configuration files.

### 3. Create the exact upstream environment

```bash
micromamba create --yes \
  --file external/pypsa-usa/workflow/envs/environment.yaml
micromamba activate pypsa-usa

python --version
snakemake --version
```

The environment includes HiGHS. Do not configure Gurobi for this phase. The
baseline configuration also disables dynamic fuel pricing, so no EIA API key
is required for this build.

### 4. Confirm the build plan without running it

```bash
cd external/pypsa-usa/workflow

snakemake data_model \
  --dry-run \
  --cores 1 \
  --configfile ../../../pypsa/config.kansas-baseline.yaml
```

The target must be exactly `data_model`. Do not invoke `solve_network` and do
not run bare `snakemake` without a target.

### 5. Build only the unsolved baseline network

For a long remote session, start `tmux` first:

```bash
tmux new -s pypsa-baseline
```

Then run:

```bash
snakemake data_model \
  --cores 1 \
  --rerun-incomplete \
  --printshellcmds \
  --latency-wait 60 \
  --configfile ../../../pypsa/config.kansas-baseline.yaml
```

If a rule fails for a transient reason, rerun the same command. Snakemake will
reuse completed outputs.

The completed, unsolved network must appear at:

```text
external/pypsa-usa/workflow/resources/KansasBaseline/eastern/
  elec_s98_c98_ec_lv1.0__E.nc
```

Verify it without starting another workflow target:

```bash
test -s resources/KansasBaseline/eastern/elec_s98_c98_ec_lv1.0__E.nc
```

Stop here. Do not run optimization, add wind, or change transmission.

## Expected resources

These are planning estimates, not hard limits. Download sizes come from the
pinned public artifacts; extracted-data and environment sizes were measured
from the partial local build. Rule memory comes from the pinned Snakemake
workflow.

| Stage | Expected disk use | Expected peak RAM | Basis |
| --- | ---: | ---: | --- |
| Repository and micromamba environment | 3–5 GiB | 2–4 GiB | Local environment measured 3.17 GiB |
| Static grid/data bundles and extraction | 7–10 GiB | Up to 5 GiB | 1.54 GB compressed; extracted `data/` measured 6.35 GiB |
| 2019 ERA5 cutout retrieval | 5–10 GiB | Up to 5 GiB | Cutout is 4.95 GB; extra room covers a partial/temp download |
| Shapes and detailed Eastern base network | 0.2–1 GiB | 3–5 GiB | Current provisional resources measure 0.19 GiB |
| Plant inventory | Usually <1 GiB output; allow 5–20 GiB temporary space | 30 GiB | `build_powerplants` declares 30,000 MB |
| Fuel-price assembly | Usually <1 GiB output; allow several GiB temporary space | 30 GiB | `build_fuel_prices` declares 30,000 MB |
| Wind and solar profile construction | Roughly 1–5 GiB output/temp | About 10–25 GiB with `--cores 1`; upstream heuristic can request 25–40 GiB at four workers | Full weather and land rasters are processed here |
| Demand, generator attachment, simplification, and 98-zone clustering | Roughly 2–10 GiB | About 10–30 GiB, input-size dependent | Upstream rules calculate memory from intermediate file sizes |
| Final `.nc` network | Likely below 2 GiB | A few GiB to load later | Unsolved 98-zone network |

Provision at least 50 GiB free disk; 80 GiB free is safer. A 100 GB persistent
volume is a reasonable minimum after accounting for the operating system and
package caches.

For memory, 64 GB is strongly recommended. On a 32 GB host, use the one-core
command exactly as shown, close other memory-intensive processes, and expect
that `build_powerplants`, `build_fuel_prices`, or renewable-profile generation
may still exceed available RAM. Do not substitute heavy swap usage for RAM.

## Data interpretation

Keep these categories separate:

- **Observed historical data:** EIA/SPP statistics used later for validation.
- **PyPSA-USA inputs:** distributed 2019 load, reconstructed generator fleet,
  ERA5-derived renewable availability, and ReEDS/NARIS transfer limits.
- **Model outputs:** dispatch, flows, prices, or curtailment from an optimized
  network. None exist at this stage.
- **Our scenarios:** hypothetical wind or transmission changes. None exist.

“2019 baseline” therefore means 2019 demand, weather, and planning horizon. The
generator fleet is reconstructed by the pinned workflow from its PUDL release
using build and retirement dates; transmission limits are modeled ReEDS/NARIS
inputs rather than observed hourly line ratings.

## Current status

- The upstream submodule is clean and pinned.
- The configuration has passed YAML checks and a Snakemake dry run.
- A provisional detailed topology exists locally, but its provenance predates
  restoration of the pinned configuration and it should be rebuilt on Linux.
- The final 98-zone `.nc` baseline does not exist yet.
- No optimization, hypothetical wind scenario, or transmission expansion has
  been run.
