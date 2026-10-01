"use client";

import type { Feature, FeatureCollection, GeoJsonProperties, Geometry, Position } from "geojson";
import { useEffect, useMemo, useState } from "react";

const DATA_URL = "/data/kansas_wind.geojson";
const WIDTH = 1200;
const HEIGHT = 690;
const PADDING = 32;

type WindFeature = Feature<Geometry, GeoJsonProperties>;
type Hovered = { x: number; y: number; value: number; name?: string } | null;

function coordinatesOf(geometry: Geometry): Position[] {
  switch (geometry.type) {
    case "Polygon": return geometry.coordinates.flat();
    case "MultiPolygon": return geometry.coordinates.flat(2);
    case "GeometryCollection": return geometry.geometries.flatMap(coordinatesOf);
    default: return [];
  }
}

function capacityFactor(feature: WindFeature): number | null {
  const value = feature.properties?.capacity_factor;
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function featureName(feature: WindFeature): string | undefined {
  const value = feature.properties?.name;
  return typeof value === "string" ? value : undefined;
}

function colorAt(value: number, min: number, max: number) {
  const t = max === min ? 0.5 : (value - min) / (max - min);
  const lightness = 88 - t * 58;
  return `hsl(166 48% ${lightness}%)`;
}

function numberLabel(value: number) {
  return value <= 1 ? `${(value * 100).toFixed(1)}%` : value.toFixed(1);
}

export default function WindMap() {
  const [data, setData] = useState<FeatureCollection | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [hovered, setHovered] = useState<Hovered>(null);

  useEffect(() => {
    const controller = new AbortController();
    fetch(DATA_URL, { signal: controller.signal })
      .then((response) => {
        if (!response.ok) throw new Error(`Wind data could not be loaded (${response.status}).`);
        return response.json();
      })
      .then((json: unknown) => {
        if (!json || typeof json !== "object" || (json as FeatureCollection).type !== "FeatureCollection") {
          throw new Error("The wind data is not a GeoJSON FeatureCollection.");
        }
        setData(json as FeatureCollection);
      })
      .catch((reason: unknown) => {
        if ((reason as Error).name !== "AbortError") setError((reason as Error).message);
      });
    return () => controller.abort();
  }, []);

  const map = useMemo(() => {
    if (!data) return null;
    const features = data.features.filter((feature): feature is WindFeature =>
      feature.geometry?.type === "Polygon" || feature.geometry?.type === "MultiPolygon" || feature.geometry?.type === "GeometryCollection"
    );
    const points = features.flatMap((feature) => coordinatesOf(feature.geometry));
    const values = features.map(capacityFactor).filter((value): value is number => value !== null);
    if (!points.length) return { error: "No polygon geometry was found in the wind dataset." } as const;
    if (!values.length) return { error: "No numeric capacity_factor values were found in the wind dataset." } as const;

    const xs = points.map(([x]) => x);
    const ys = points.map(([, y]) => y);
    const minX = Math.min(...xs), maxX = Math.max(...xs), minY = Math.min(...ys), maxY = Math.max(...ys);
    const scale = Math.min((WIDTH - PADDING * 2) / (maxX - minX), (HEIGHT - PADDING * 2) / (maxY - minY));
    const offsetX = (WIDTH - (maxX - minX) * scale) / 2;
    const offsetY = (HEIGHT - (maxY - minY) * scale) / 2;
    const project = ([x, y]: Position) => [offsetX + (x - minX) * scale, HEIGHT - offsetY - (y - minY) * scale];
    const ringPath = (ring: Position[]) => ring.map((point, index) => `${index ? "L" : "M"}${project(point).join(",")}`).join(" ") + " Z";
    const path = (geometry: Geometry): string => {
      if (geometry.type === "Polygon") return geometry.coordinates.map(ringPath).join(" ");
      if (geometry.type === "MultiPolygon") return geometry.coordinates.flatMap((polygon) => polygon.map(ringPath)).join(" ");
      if (geometry.type === "GeometryCollection") return geometry.geometries.map(path).join(" ");
      return "";
    };
    return { features, path, min: Math.min(...values), max: Math.max(...values) } as const;
  }, [data]);

  const mapError = error ?? (map && "error" in map ? map.error : null);

  return (
    <div className="relative mx-auto min-h-[55vh] max-w-[1800px] overflow-hidden rounded-2xl border border-ink/15 bg-[#dfe9e5] shadow-[0_20px_70px_rgba(23,32,29,0.08)]">
      <div className="absolute left-5 top-5 z-10 rounded-lg bg-prairie/90 px-4 py-3 backdrop-blur md:left-8 md:top-8">
        <p className="text-xs font-semibold uppercase tracking-[0.18em] text-ink/55">Kansas</p>
        <p className="mt-1 font-serif text-xl">Wind capacity factor</p>
      </div>

      {!data && !mapError && <div className="grid min-h-[55vh] place-items-center text-sm text-ink/55">Loading wind data…</div>}
      {mapError && (
        <div className="grid min-h-[55vh] place-items-center px-6 text-center">
          <div className="max-w-lg rounded-xl border border-ink/15 bg-prairie/90 p-6">
            <p className="font-serif text-2xl">Wind data unavailable</p>
            <p className="mt-2 text-sm leading-6 text-ink/65">{mapError}</p>
            <p className="mt-3 font-mono text-xs text-ink/50">{DATA_URL}</p>
          </div>
        </div>
      )}

      {map && !("error" in map) && (
        <>
          <svg viewBox={`0 0 ${WIDTH} ${HEIGHT}`} role="img" aria-label="Kansas polygons colored by capacity factor" className="block min-h-[55vh] w-full">
            <g>
              {map.features.map((feature, index) => {
                const value = capacityFactor(feature);
                return (
                  <path key={feature.id?.toString() ?? index} d={map.path(feature.geometry)} fill={value === null ? "#d3d7d3" : colorAt(value, map.min, map.max)} fillRule="evenodd" stroke="#f3f0e6" strokeWidth="0.75" vectorEffect="non-scaling-stroke" tabIndex={value === null ? -1 : 0}
                    aria-label={value === null ? "Capacity factor unavailable" : `${featureName(feature) ? `${featureName(feature)}, ` : ""}capacity factor ${numberLabel(value)}`}
                    onPointerMove={(event) => value !== null && setHovered({ x: event.clientX, y: event.clientY, value, name: featureName(feature) })}
                    onPointerLeave={() => setHovered(null)}
                    onFocus={() => value !== null && setHovered({ x: 24, y: 24, value, name: featureName(feature) })}
                    onBlur={() => setHovered(null)}
                    className="outline-none transition-opacity hover:opacity-75 focus:opacity-75" />
                );
              })}
            </g>
          </svg>
          <div className="absolute bottom-5 right-5 rounded-lg bg-prairie/90 px-4 py-3 text-xs backdrop-blur md:bottom-8 md:right-8">
            <div className="mb-2 h-2 w-40 rounded-full" style={{ background: `linear-gradient(to right, ${colorAt(map.min, map.min, map.max)}, ${colorAt(map.max, map.min, map.max)})` }} />
            <div className="flex justify-between text-ink/65"><span>{numberLabel(map.min)}</span><span>{numberLabel(map.max)}</span></div>
          </div>
        </>
      )}

      {hovered && (
        <div className="pointer-events-none fixed z-50 -translate-y-full rounded-md bg-ink px-3 py-2 text-xs text-white shadow-lg" style={{ left: hovered.x + 12, top: hovered.y - 8 }}>
          {hovered.name && <p className="mb-1 text-white/65">{hovered.name}</p>}
          <p>Capacity factor · {numberLabel(hovered.value)}</p>
        </div>
      )}
    </div>
  );
}
