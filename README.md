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

Reserved data paths:

- `public/data/transmission.geojson`
- `public/data/exclusions.geojson`

## Non-goals for v0.1

- Grid optimization
- Nationwide model
- Hourly dispatch
- Storage
- Transmission expansion
