# Kansas Wind Potential

A Next.js and TypeScript scrollytelling project for exploring potential wind farm locations in Kansas.

## Getting started

```bash
npm install
npm run dev
```

Add the sourced wind polygons at `public/data/kansas_wind.geojson`. Each polygon must contain a numeric `capacity_factor` property. The map deliberately shows an unavailable state when the file or property is missing; it does not generate fallback data.

Reserved data paths:

- `public/data/transmission.geojson`
- `public/data/exclusions.geojson`

## Non-goals for v0.1

- Grid optimization
- Nationwide model
- Hourly dispatch
- Storage
- Transmission expansion
