"use client";

import type { Feature, FeatureCollection, Point, Polygon } from "geojson";
import * as maplibregl from "maplibre-gl";
import { useEffect, useMemo, useRef, useState } from "react";

const DATA_URL = "/data/kansas_wind.geojson";
const KANSAS_BOUNDS: [[number, number], [number, number]] = [[-102.2, 36.85], [-94.45, 40.15]];
const COLOR_LOW = "#c9dfd4";
const COLOR_HIGH = "#075d4f";
const CELL_HALF_WIDTH = 0.0116;
const CELL_HALF_HEIGHT = 0.009;

type Metric = "capacity_factor" | "wind_speed_mps";
type WindProperties = {
  site_id: number;
  state: string;
  county: string;
  fraction_of_usable_area: number;
  power_curve: number;
  capacity_mw: number;
  wind_speed_mps: number;
  capacity_factor: number;
  full_timeseries_directory: number;
  full_timeseries_path: string;
};
type WindData = FeatureCollection<Point, WindProperties>;
type WindGrid = FeatureCollection<Polygon, WindProperties>;

const METRICS: Record<Metric, { label: string; shortLabel: string; format: (value: number) => string }> = {
  capacity_factor: {
    label: "Modeled capacity factor",
    shortLabel: "Capacity factor",
    format: (value) => `${(value * 100).toFixed(1)}%`,
  },
  wind_speed_mps: {
    label: "Average wind speed",
    shortLabel: "Wind speed",
    format: (value) => `${value.toFixed(2)} m/s`,
  },
};

function popupContent(properties: WindProperties) {
  const root = document.createElement("div");
  root.className = "wind-popup";
  const title = document.createElement("p");
  title.className = "wind-popup__title";
  title.textContent = `${properties.county} County`;
  root.appendChild(title);

  const rows: Array<[string, string]> = [
    ["Capacity factor", METRICS.capacity_factor.format(properties.capacity_factor)],
    ["Wind speed", METRICS.wind_speed_mps.format(properties.wind_speed_mps)],
    ["Usable area", `${(properties.fraction_of_usable_area * 100).toFixed(1)}%`],
    ["Modeled capacity", `${properties.capacity_mw.toFixed(0)} MW`],
    ["Site ID", String(properties.site_id)],
  ];
  const list = document.createElement("dl");
  for (const [label, value] of rows) {
    const term = document.createElement("dt");
    const detail = document.createElement("dd");
    term.textContent = label;
    detail.textContent = value;
    list.append(term, detail);
  }
  root.appendChild(list);
  return root;
}

function toGridCells(data: WindData): WindGrid {
  return {
    type: "FeatureCollection",
    features: data.features.map((feature) => {
      const [longitude, latitude] = feature.geometry.coordinates;
      return {
        type: "Feature",
        id: feature.id,
        properties: feature.properties,
        geometry: {
          type: "Polygon",
          coordinates: [[
            [longitude - CELL_HALF_WIDTH, latitude - CELL_HALF_HEIGHT],
            [longitude + CELL_HALF_WIDTH, latitude - CELL_HALF_HEIGHT],
            [longitude + CELL_HALF_WIDTH, latitude + CELL_HALF_HEIGHT],
            [longitude - CELL_HALF_WIDTH, latitude + CELL_HALF_HEIGHT],
            [longitude - CELL_HALF_WIDTH, latitude - CELL_HALF_HEIGHT],
          ]],
        },
      };
    }),
  };
}

export default function WindMap() {
  const containerRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<maplibregl.Map | null>(null);
  const popupRef = useRef<maplibregl.Popup | null>(null);
  const [data, setData] = useState<WindData | null>(null);
  const [metric, setMetric] = useState<Metric>("capacity_factor");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    fetch(DATA_URL, { signal: controller.signal })
      .then((response) => {
        if (!response.ok) throw new Error(`Wind data could not be loaded (${response.status}).`);
        return response.json();
      })
      .then((json: unknown) => {
        if (!json || typeof json !== "object" || (json as WindData).type !== "FeatureCollection") {
          throw new Error("The wind data is not a GeoJSON FeatureCollection.");
        }
        setData(json as WindData);
      })
      .catch((reason: unknown) => {
        if ((reason as Error).name !== "AbortError") setError((reason as Error).message);
      });
    return () => controller.abort();
  }, []);

  const stats = useMemo(() => {
    if (!data?.features.length) return null;
    const summarize = (key: Metric) => {
      const values = data.features.map((feature) => feature.properties[key]);
      return {
        min: Math.min(...values),
        max: Math.max(...values),
        mean: values.reduce((sum, value) => sum + value, 0) / values.length,
      };
    };
    return { capacity_factor: summarize("capacity_factor"), wind_speed_mps: summarize("wind_speed_mps") };
  }, [data]);

  const gridData = useMemo(() => data ? toGridCells(data) : null, [data]);

  useEffect(() => {
    if (!containerRef.current || !gridData || mapRef.current) return;

    // Next.js cannot reliably infer MapLibre's module-worker URL after bundling.
    // Serve the official worker and its shared module from stable public paths.
    maplibregl.setWorkerUrl("/maplibre-gl-worker.mjs");

    const map = new maplibregl.Map({
      container: containerRef.current,
      style: {
        version: 8,
        sources: {
          openstreetmap: {
            type: "raster",
            tiles: ["https://tile.openstreetmap.org/{z}/{x}/{y}.png"],
            tileSize: 256,
            attribution: "© OpenStreetMap contributors",
          },
          "wind-sites": { type: "geojson", data: gridData },
        },
        layers: [
          { id: "basemap", type: "raster", source: "openstreetmap", paint: { "raster-saturation": -1, "raster-opacity": 0.42, "raster-contrast": -0.28, "raster-brightness-max": 0.96 } },
          {
            id: "wind-sites",
            type: "fill",
            source: "wind-sites",
            paint: {
              "fill-color": ["interpolate", ["linear"], ["get", "capacity_factor"], 0.314, COLOR_LOW, 0.545, COLOR_HIGH],
              "fill-opacity": ["interpolate", ["linear"], ["zoom"], 4.5, 0.94, 9, 0.82],
              "fill-outline-color": "rgba(243, 240, 230, 0.72)",
            },
          },
        ],
      },
      bounds: KANSAS_BOUNDS,
      fitBoundsOptions: { padding: 42 },
      maxBounds: [[-106, 34], [-90, 43]],
      minZoom: 4.5,
      maxZoom: 12,
      cooperativeGestures: false,
      attributionControl: false,
    });
    mapRef.current = map;
    map.addControl(new maplibregl.NavigationControl({ showCompass: false }), "bottom-right");
    map.addControl(new maplibregl.AttributionControl({ compact: true }), "bottom-right");

    const showPopup = (event: maplibregl.MapMouseEvent & { features?: Feature[] }) => {
      const feature = event.features?.[0];
      if (!feature?.properties) return;
      const properties = feature.properties as WindProperties;
      popupRef.current?.remove();
      popupRef.current = new maplibregl.Popup({ closeButton: false, closeOnClick: false, offset: 10, maxWidth: "260px" })
        .setLngLat(event.lngLat)
        .setDOMContent(popupContent(properties))
        .addTo(map);
    };

    map.on("mousemove", "wind-sites", showPopup);
    map.on("click", "wind-sites", showPopup);
    map.on("mouseenter", "wind-sites", () => { map.getCanvas().style.cursor = "pointer"; });
    map.on("mouseleave", "wind-sites", () => {
      map.getCanvas().style.cursor = "";
      popupRef.current?.remove();
    });

    return () => {
      popupRef.current?.remove();
      map.remove();
      mapRef.current = null;
    };
  }, [gridData]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !stats || !map.getLayer("wind-sites")) return;
    const range = stats[metric];
    map.setPaintProperty("wind-sites", "fill-color", ["interpolate", ["linear"], ["get", metric], range.min, COLOR_LOW, range.max, COLOR_HIGH]);
    popupRef.current?.remove();
  }, [metric, stats]);

  const definition = METRICS[metric];
  const range = stats?.[metric];

  return (
    <div className="relative mx-auto h-[68vh] min-h-[520px] max-w-[1800px] overflow-hidden rounded-2xl border border-ink/15 bg-[#dfe9e5] shadow-[0_20px_70px_rgba(23,32,29,0.08)]">
      <div ref={containerRef} className="absolute inset-0" aria-label="Movable map of Kansas WIND Toolkit sites" />

      <div className="pointer-events-none absolute left-5 top-5 z-10 max-w-[calc(100%-2.5rem)] rounded-xl bg-prairie/90 px-4 py-3 shadow-sm backdrop-blur md:left-8 md:top-8">
        <p className="text-xs font-semibold uppercase tracking-[0.18em] text-ink/55">Kansas · 4,154 modeled sites</p>
        <p className="mt-1 font-serif text-xl">{definition.label}</p>
        <p className="mt-1 text-xs text-ink/55">Drag to move · scroll or pinch to zoom</p>
      </div>

      <div className="absolute right-5 top-5 z-20 flex rounded-lg border border-ink/10 bg-prairie/90 p-1 text-xs shadow-sm backdrop-blur md:right-8 md:top-8">
        {(Object.keys(METRICS) as Metric[]).map((key) => (
          <button key={key} type="button" aria-pressed={metric === key} onClick={() => setMetric(key)} className={`rounded-md px-3 py-2 transition ${metric === key ? "bg-ink text-white" : "text-ink/65 hover:bg-white/70"}`}>
            {METRICS[key].shortLabel}
          </button>
        ))}
      </div>

      {!data && !error && <div className="pointer-events-none absolute inset-0 z-30 grid place-items-center bg-[#dfe9e5] text-sm text-ink/55">Loading wind data…</div>}
      {error && <div className="absolute inset-0 z-30 grid place-items-center bg-[#dfe9e5] px-6 text-center"><div className="rounded-xl bg-prairie p-6"><p className="font-serif text-2xl">Wind data unavailable</p><p className="mt-2 text-sm text-ink/65">{error}</p></div></div>}

      {stats && <div className="absolute bottom-7 left-5 z-10 hidden rounded-lg bg-prairie/90 px-4 py-3 text-xs text-ink/60 backdrop-blur sm:block md:left-8">
        <div><span className="font-semibold text-ink">Dataset averages</span><span className="ml-3">CF {(stats.capacity_factor.mean * 100).toFixed(1)}%</span><span className="ml-3">Wind {stats.wind_speed_mps.mean.toFixed(2)} m/s</span></div>
        <a href="https://doi.org/10.7799/1329290" target="_blank" rel="noreferrer" className="mt-1.5 inline-block underline decoration-ink/25 underline-offset-2 hover:text-ink">Source: NREL WIND Toolkit Power Data Site Index</a>
      </div>}

      {range && <div className="pointer-events-none absolute bottom-7 right-20 z-10 rounded-lg bg-prairie/90 px-4 py-3 text-xs backdrop-blur">
        <p className="mb-2 text-ink/55">{definition.shortLabel}</p>
        <div className="mb-2 h-2 w-40 rounded-full" style={{ background: `linear-gradient(to right, ${COLOR_LOW}, ${COLOR_HIGH})` }} />
        <div className="flex justify-between text-ink/65"><span>{definition.format(range.min)}</span><span>{definition.format(range.max)}</span></div>
      </div>}
    </div>
  );
}
