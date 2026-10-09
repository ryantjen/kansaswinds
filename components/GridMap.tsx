"use client";

import type { Feature, FeatureCollection, Geometry } from "geojson";
import * as maplibregl from "maplibre-gl";
import { useEffect, useMemo, useRef, useState } from "react";

const DATA_URL = "/data/kansas_grid.geojson";
const GRID_BOUNDS: [[number, number], [number, number]] = [[-103.35, 35.25], [-93.2, 41.45]];

type GridProperties = {
  kind: "zone" | "interface" | "generator" | "network_line" | "network_node";
  [key: string]: string | number | boolean | null;
};
type GridData = FeatureCollection<Geometry, GridProperties>;

function formatMw(value: unknown) {
  return typeof value === "number"
    ? `${new Intl.NumberFormat("en-US", { maximumFractionDigits: 0 }).format(value)} MW`
    : "Not available";
}

function formatKm(value: unknown) {
  return typeof value === "number"
    ? `${new Intl.NumberFormat("en-US", { maximumFractionDigits: 1 }).format(value)} km`
    : "Not available";
}

function addRows(root: HTMLElement, rows: Array<[string, string]>) {
  const list = document.createElement("dl");
  for (const [label, value] of rows) {
    const term = document.createElement("dt");
    const detail = document.createElement("dd");
    term.textContent = label;
    detail.textContent = value;
    list.append(term, detail);
  }
  root.appendChild(list);
}

function popupContent(properties: GridProperties) {
  const root = document.createElement("div");
  root.className = "grid-popup";
  const title = document.createElement("p");
  title.className = "grid-popup__title";

  if (properties.kind === "network_line") {
    title.textContent = `${properties.voltage_kv} kV AC branch`;
    root.appendChild(title);
    addRows(root, [
      ["Thermal capacity", formatMw(properties.capacity_mw)],
      ["Modeled length", formatKm(properties.length_km)],
      ["Endpoints", `${properties.bus0} → ${properties.bus1}`],
      ["Annual power flow", "Requires solved hourly dispatch"],
      ["Topology", "Synthetic / provisional"],
    ]);
  } else if (properties.kind === "network_node") {
    title.textContent = `${properties.max_voltage_kv} kV network node`;
    root.appendChild(title);
    addRows(root, [
      ["Connected branches", String(properties.branch_count)],
      ["County ID", String(properties.counties || "Not available")],
      ["State", String(properties.states || "Not available")],
      ["Bus IDs", String(properties.bus_ids)],
      ["Topology", "Synthetic / provisional"],
    ]);
  } else if (properties.kind === "generator") {
    title.textContent = `${properties.fuel} generation center`;
    root.appendChild(title);
    addRows(root, [
      ["Zone", String(properties.zone_name)],
      ["Fuel / technology", String(properties.fuel)],
      ["Capacity", formatMw(properties.capacity_mw)],
      ["Annual generation", "Not available — unsolved"],
      ["Status", String(properties.status)],
    ]);
  } else {
    title.textContent = `${properties.zone0_name} ↔ ${properties.zone1_name}`;
    root.appendChild(title);
    const rows: Array<[string, string]> = properties.internal
      ? [
          ["West → east limit", formatMw(properties.direction_0_to_1_mw)],
          ["East → west limit", formatMw(properties.direction_1_to_0_mw)],
        ]
      : [
          ["Into Kansas limit", formatMw(properties.into_kansas_capacity_mw)],
          ["Out of Kansas limit", formatMw(properties.out_of_kansas_capacity_mw)],
        ];
    rows.push(
      ["Daily power flow", "Not available — unsolved"],
      ["Representation", "Regional planning interface"],
    );
    addRows(root, rows);
  }
  return root;
}

export default function GridMap() {
  const containerRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<maplibregl.Map | null>(null);
  const popupRef = useRef<maplibregl.Popup | null>(null);
  const [data, setData] = useState<GridData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [topologyView, setTopologyView] = useState<"physical" | "planning">("physical");

  useEffect(() => {
    const controller = new AbortController();
    fetch(DATA_URL, { signal: controller.signal })
      .then((response) => {
        if (!response.ok) throw new Error(`Grid data could not be loaded (${response.status}).`);
        return response.json();
      })
      .then((json: unknown) => {
        if (!json || typeof json !== "object" || (json as GridData).type !== "FeatureCollection") {
          throw new Error("The grid data is not a GeoJSON FeatureCollection.");
        }
        setData(json as GridData);
      })
      .catch((reason: unknown) => {
        if ((reason as Error).name !== "AbortError") setError((reason as Error).message);
      });
    return () => controller.abort();
  }, []);

  const stats = useMemo(() => {
    if (!data) return null;
    const generators = data.features.filter((feature) => feature.properties?.kind === "generator");
    const interfaces = data.features.filter((feature) => feature.properties?.kind === "interface");
    const networkLines = data.features.filter((feature) => feature.properties?.kind === "network_line");
    const networkNodes = data.features.filter((feature) => feature.properties?.kind === "network_node");
    return {
      generators: generators.length,
      interfaces: interfaces.length,
      networkLines: networkLines.length,
      networkNodes: networkNodes.length,
      capacityMw: generators.reduce((sum, feature) => sum + Number(feature.properties?.capacity_mw ?? 0), 0),
    };
  }, [data]);

  useEffect(() => {
    if (!containerRef.current || !data || mapRef.current) return;
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
          grid: { type: "geojson", data },
        },
        layers: [
          {
            id: "basemap",
            type: "raster",
            source: "openstreetmap",
            paint: {
              "raster-saturation": -0.95,
              "raster-opacity": 0.48,
              "raster-contrast": -0.22,
              "raster-brightness-max": 0.96,
            },
          },
          {
            id: "planning-zones",
            type: "fill",
            source: "grid",
            filter: ["==", ["get", "kind"], "zone"],
            paint: {
              "fill-color": ["case", ["get", "in_kansas"], "#dbe8df", "#e8e5da"],
              "fill-opacity": ["case", ["get", "in_kansas"], 0.42, 0.16],
              "fill-outline-color": "rgba(23, 32, 29, 0.24)",
            },
          },
          {
            id: "interface-hit",
            type: "line",
            source: "grid",
            filter: ["==", ["get", "kind"], "interface"],
            layout: { visibility: "none" },
            paint: { "line-color": "rgba(0,0,0,0)", "line-width": 16 },
          },
          {
            id: "interfaces",
            type: "line",
            source: "grid",
            filter: ["==", ["get", "kind"], "interface"],
            layout: { visibility: "none" },
            paint: {
              "line-color": "#9a523c",
              "line-opacity": 0.78,
              "line-dasharray": [1.5, 1.15],
              "line-width": [
                "interpolate", ["linear"], ["get", "display_capacity_mw"],
                40, 1.4,
                1000, 2.7,
                5500, 6,
              ],
            },
          },
          {
            id: "network-line-hit",
            type: "line",
            source: "grid",
            filter: ["==", ["get", "kind"], "network_line"],
            paint: { "line-color": "rgba(0,0,0,0)", "line-width": 10 },
          },
          {
            id: "network-lines",
            type: "line",
            source: "grid",
            filter: ["==", ["get", "kind"], "network_line"],
            paint: {
              "line-color": [
                "interpolate", ["linear"], ["get", "voltage_kv"],
                115, "#77837e",
                161, "#426d67",
                345, "#c27931",
                500, "#8f3d32",
              ],
              "line-opacity": 0.84,
              "line-width": [
                "interpolate", ["linear"], ["get", "voltage_kv"],
                115, 0.75,
                161, 1.2,
                345, 2.25,
                500, 3.2,
              ],
            },
          },
          {
            id: "network-node-halo",
            type: "circle",
            source: "grid",
            minzoom: 5.6,
            filter: ["==", ["get", "kind"], "network_node"],
            paint: {
              "circle-radius": ["interpolate", ["linear"], ["get", "branch_count"], 1, 2.3, 8, 5.2],
              "circle-color": "#f3f0e6",
              "circle-opacity": 0.94,
            },
          },
          {
            id: "network-nodes",
            type: "circle",
            source: "grid",
            minzoom: 5.6,
            filter: ["==", ["get", "kind"], "network_node"],
            paint: {
              "circle-radius": ["interpolate", ["linear"], ["get", "branch_count"], 1, 1.35, 8, 3.8],
              "circle-color": "#17201d",
              "circle-opacity": 0.82,
            },
          },
          {
            id: "generator-halo",
            type: "circle",
            source: "grid",
            filter: ["==", ["get", "kind"], "generator"],
            paint: {
              "circle-radius": [
                "+",
                ["interpolate", ["linear"], ["sqrt", ["get", "capacity_mw"]], 1, 4.5, 80, 11],
                2,
              ],
              "circle-color": "#f3f0e6",
              "circle-opacity": 0.95,
            },
          },
          {
            id: "generators",
            type: "circle",
            source: "grid",
            filter: ["==", ["get", "kind"], "generator"],
            paint: {
              "circle-radius": ["interpolate", ["linear"], ["sqrt", ["get", "capacity_mw"]], 1, 4.5, 80, 11],
              "circle-color": [
                "match", ["get", "category"],
                "wind", "#177467",
                "solar", "#d19a28",
                "#3e4a46",
              ],
              "circle-stroke-color": "#f3f0e6",
              "circle-stroke-width": 1,
              "circle-opacity": 0.92,
            },
          },
        ],
      },
      bounds: GRID_BOUNDS,
      fitBoundsOptions: { padding: 36 },
      maxBounds: [[-108, 32], [-89, 45]],
      minZoom: 4,
      maxZoom: 11,
      cooperativeGestures: false,
      attributionControl: false,
    });
    mapRef.current = map;
    map.addControl(new maplibregl.NavigationControl({ showCompass: false }), "bottom-right");
    map.addControl(new maplibregl.AttributionControl({ compact: true }), "bottom-right");

    const showPopup = (event: maplibregl.MapMouseEvent & { features?: Feature[] }) => {
      const feature = event.features?.[0];
      if (!feature?.properties) return;
      popupRef.current?.remove();
      popupRef.current = new maplibregl.Popup({ closeButton: false, closeOnClick: false, offset: 12, maxWidth: "330px" })
        .setLngLat(event.lngLat)
        .setDOMContent(popupContent(feature.properties as GridProperties))
        .addTo(map);
    };

    for (const layer of ["interface-hit", "network-line-hit", "network-nodes", "generators"]) {
      map.on("mousemove", layer, showPopup);
      map.on("click", layer, showPopup);
      map.on("mouseenter", layer, () => { map.getCanvas().style.cursor = "pointer"; });
      map.on("mouseleave", layer, () => {
        map.getCanvas().style.cursor = "";
        popupRef.current?.remove();
      });
    }

    return () => {
      popupRef.current?.remove();
      map.remove();
      mapRef.current = null;
    };
  }, [data]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    const applyVisibility = () => {
      const physicalVisibility = topologyView === "physical" ? "visible" : "none";
      const planningVisibility = topologyView === "planning" ? "visible" : "none";
      for (const layer of ["network-line-hit", "network-lines", "network-node-halo", "network-nodes"]) {
        if (map.getLayer(layer)) map.setLayoutProperty(layer, "visibility", physicalVisibility);
      }
      for (const layer of ["interface-hit", "interfaces"]) {
        if (map.getLayer(layer)) map.setLayoutProperty(layer, "visibility", planningVisibility);
      }
    };
    if (map.loaded()) applyVisibility();
    else map.once("load", applyVisibility);
  }, [data, topologyView]);

  return (
    <div className="relative h-[66vh] min-h-[560px] overflow-hidden rounded-2xl border border-ink/15 bg-[#dde6e2] shadow-[0_20px_70px_rgba(23,32,29,0.08)]">
      <div ref={containerRef} className="absolute inset-0" aria-label="Movable map of Kansas high-voltage network topology, generation centers, and regional transmission interfaces" />

      <div className="pointer-events-auto absolute left-5 top-5 z-10 max-w-[calc(100%-2.5rem)] rounded-xl bg-prairie/90 px-4 py-3 shadow-sm backdrop-blur md:left-8 md:top-8">
        <p className="text-xs font-semibold uppercase tracking-[0.18em] text-grid">2019 · unsolved grid baseline</p>
        <p className="mt-1 font-serif text-xl">Kansas transmission topology</p>
        <div className="mt-3 flex w-fit rounded-lg border border-ink/15 bg-white/45 p-1 text-xs font-semibold">
          <button type="button" onClick={() => setTopologyView("physical")} aria-pressed={topologyView === "physical"} className={`rounded-md px-3 py-1.5 transition ${topologyView === "physical" ? "bg-ink text-white" : "text-ink/60 hover:text-ink"}`}>115 kV+ network</button>
          <button type="button" onClick={() => setTopologyView("planning")} aria-pressed={topologyView === "planning"} className={`rounded-md px-3 py-1.5 transition ${topologyView === "planning" ? "bg-ink text-white" : "text-ink/60 hover:text-ink"}`}>Planning interfaces</button>
        </div>
        <p className="mt-2 text-xs text-ink/55">Hover for details · drag to move · scroll or pinch to zoom</p>
      </div>

      <div className="pointer-events-none absolute right-5 top-5 z-10 hidden rounded-xl bg-prairie/90 px-4 py-3 text-xs shadow-sm backdrop-blur sm:block md:right-8 md:top-8">
        <p className="mb-2 font-semibold uppercase tracking-[0.14em] text-ink/55">{topologyView === "physical" ? "Nominal voltage" : "Planning layer"}</p>
        {topologyView === "physical" ? <div className="grid grid-cols-[auto_1fr] items-center gap-x-2 gap-y-1.5 text-ink/70">
          <span className="h-0.5 w-4 bg-[#77837e]" /><span>115 kV</span>
          <span className="h-0.5 w-4 bg-[#426d67]" /><span>161 kV</span>
          <span className="h-0.5 w-4 bg-[#c27931]" /><span>345 kV</span>
          <span className="h-0.5 w-4 bg-[#8f3d32]" /><span>500 kV</span>
        </div> : <div className="grid grid-cols-[auto_1fr] items-center gap-x-2 gap-y-1.5 text-ink/70">
          <span className="h-2.5 w-2.5 rounded-full bg-[#177467]" /><span>Wind</span>
          <span className="h-2.5 w-2.5 rounded-full bg-[#d19a28]" /><span>Solar</span>
          <span className="h-2.5 w-2.5 rounded-full bg-[#3e4a46]" /><span>Major conventional</span>
          <span className="h-0.5 w-4 bg-[#9a523c]" /><span>Transfer interface</span>
        </div>}
      </div>

      {!data && !error && <div className="pointer-events-none absolute inset-0 z-30 grid place-items-center bg-[#dde6e2] text-sm text-ink/55">Loading grid context…</div>}
      {error && <div className="absolute inset-0 z-30 grid place-items-center bg-[#dde6e2] px-6 text-center"><div className="rounded-xl bg-prairie p-6"><p className="font-serif text-2xl">Grid data unavailable</p><p className="mt-2 text-sm text-ink/65">{error}</p></div></div>}

      {stats && <div className="pointer-events-none absolute bottom-7 left-5 z-10 hidden max-w-2xl rounded-lg bg-prairie/90 px-4 py-3 text-xs text-ink/60 backdrop-blur sm:block md:left-8">
        {topologyView === "physical" ? <>
          <p><span className="font-semibold text-ink">{stats.networkLines.toLocaleString()} AC branches</span><span className="ml-3">{stats.networkNodes.toLocaleString()} mapped nodes</span><span className="ml-3">115 kV and above</span></p>
          <p className="mt-1.5">Synthetic, provisional topology; line width/color shows voltage, not observed flow.</p>
        </> : <>
          <p><span className="font-semibold text-ink">{stats.interfaces} interfaces</span><span className="ml-3">{stats.generators} generation centers</span><span className="ml-3">{(stats.capacityMw / 1000).toFixed(1)} GW mapped</span></p>
          <p className="mt-1.5">Dashed-line width shows directional transfer limit, not observed flow.</p>
        </>}
      </div>}
    </div>
  );
}
