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

The second map reads `public/data/kansas_grid.geojson`, a compact browser-ready
export of the unsolved PyPSA-USA Kansas baseline. It contains the two Kansas
ReEDS planning zones, the neighboring zones connected to them, ten modeled
transfer interfaces, and eleven aggregated generation centers. Wind and solar
are always included; conventional generation is included at 250 MW or larger.

Regenerate the file after refreshing the baseline analysis outputs with:

```bash
npm run data:grid
```

Interface width represents modeled directional transfer capacity, not a
surveyed physical transmission line or observed power flow. Generator markers
are regional aggregates at zone centers, not individual plant coordinates.
Annual generation and daily interface flow remain unavailable until the
network is solved or historical observations are joined.

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
