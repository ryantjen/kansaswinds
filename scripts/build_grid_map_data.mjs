import { readFileSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const resultsDir = join(root, "results", "kansas");
const resourcesDir = join(root, "external", "pypsa-usa", "workflow", "resources", "KansasBaseline", "eastern");
const MIN_TOPOLOGY_VOLTAGE_KV = 115;

function parseCsv(text) {
  const rows = [];
  let row = [];
  let field = "";
  let quoted = false;

  for (let i = 0; i < text.length; i += 1) {
    const char = text[i];
    if (char === '"') {
      if (quoted && text[i + 1] === '"') {
        field += '"';
        i += 1;
      } else {
        quoted = !quoted;
      }
    } else if (char === "," && !quoted) {
      row.push(field);
      field = "";
    } else if ((char === "\n" || char === "\r") && !quoted) {
      if (char === "\r" && text[i + 1] === "\n") i += 1;
      row.push(field);
      if (row.some((value) => value !== "")) rows.push(row);
      row = [];
      field = "";
    } else {
      field += char;
    }
  }
  if (field || row.length) {
    row.push(field);
    rows.push(row);
  }

  const [headers, ...values] = rows;
  return values.map((cells) => Object.fromEntries(headers.map((header, index) => [header, cells[index] ?? ""])));
}

function readCsv(path) {
  return parseCsv(readFileSync(path, "utf8"));
}

function number(value) {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function rings(geometry) {
  if (geometry.type === "Polygon") return geometry.coordinates;
  if (geometry.type === "MultiPolygon") return geometry.coordinates.flat();
  return [];
}

function polygonCenter(geometry) {
  const coordinates = rings(geometry).flat();
  const longitudes = coordinates.map(([x]) => x);
  const latitudes = coordinates.map(([, y]) => y);
  return [
    (Math.min(...longitudes) + Math.max(...longitudes)) / 2,
    (Math.min(...latitudes) + Math.max(...latitudes)) / 2,
  ];
}

function parseLineString(wkt) {
  const match = /^LINESTRING\s*(?:Z\s*)?\((.+)\)$/i.exec(wkt?.trim() ?? "");
  if (!match) return null;
  const coordinates = match[1].split(",").map((pair) => {
    const [x, y] = pair.trim().split(/\s+/).map(Number);
    return [x, y];
  });
  return coordinates.length >= 2 && coordinates.every(([x, y]) => Number.isFinite(x) && Number.isFinite(y))
    ? coordinates
    : null;
}

const transmission = readCsv(join(resultsDir, "transmission_touching_kansas.csv"));
const generators = readCsv(join(resultsDir, "generators.csv"));
const buses = readCsv(join(resultsDir, "buses.csv"));
const reeds = JSON.parse(readFileSync(join(resourcesDir, "Geospatial", "reeds_shapes.geojson"), "utf8"));
const detailedBuses = readCsv(join(resourcesDir, "bus_gis.csv"));
const detailedLines = readCsv(join(resourcesDir, "lines_gis.csv"));

const detailedBusById = new Map(detailedBuses.map((bus) => [bus.Bus, bus]));
const topologyLines = detailedLines.filter((line) => {
  const bus0 = detailedBusById.get(line.bus0);
  const bus1 = detailedBusById.get(line.bus1);
  const voltage = number(line.v_nom) ?? 0;
  const length = number(line.length) ?? 0;
  return voltage >= MIN_TOPOLOGY_VOLTAGE_KV
    && length > 0.05
    && (bus0?.reeds_state === "KS" || bus1?.reeds_state === "KS")
    && parseLineString(line.WKT_geometry);
});

const topologyLineFeatures = topologyLines.map((line) => {
  const bus0 = detailedBusById.get(line.bus0);
  const bus1 = detailedBusById.get(line.bus1);
  return {
    type: "Feature",
    properties: {
      kind: "network_line",
      line_id: line.Line,
      bus0: line.bus0,
      bus1: line.bus1,
      voltage_kv: number(line.v_nom),
      capacity_mw: number(line.s_nom),
      length_km: number(line.length),
      state0: bus0?.reeds_state ?? null,
      state1: bus1?.reeds_state ?? null,
      kansas_internal: bus0?.reeds_state === "KS" && bus1?.reeds_state === "KS",
      crosses_kansas_boundary: (bus0?.reeds_state === "KS") !== (bus1?.reeds_state === "KS"),
      representation: "Provisional PyPSA-USA synthetic AC branch",
    },
    geometry: { type: "LineString", coordinates: parseLineString(line.WKT_geometry) },
  };
});

const topologyNodes = new Map();
for (const line of topologyLines) {
  for (const busId of [line.bus0, line.bus1]) {
    const bus = detailedBusById.get(busId);
    const x = number(bus?.x);
    const y = number(bus?.y);
    if (x === null || y === null) continue;
    const key = `${x.toFixed(5)},${y.toFixed(5)}`;
    const existing = topologyNodes.get(key) ?? {
      coordinates: [x, y],
      busIds: new Set(),
      states: new Set(),
      counties: new Set(),
      maxVoltageKv: 0,
      branchCount: 0,
    };
    existing.busIds.add(busId);
    if (bus.reeds_state) existing.states.add(bus.reeds_state);
    if (bus.county) existing.counties.add(bus.county);
    existing.maxVoltageKv = Math.max(existing.maxVoltageKv, number(line.v_nom) ?? 0);
    existing.branchCount += 1;
    topologyNodes.set(key, existing);
  }
}

const topologyNodeFeatures = [...topologyNodes.values()].map((node) => ({
  type: "Feature",
  properties: {
    kind: "network_node",
    bus_ids: [...node.busIds].join(", "),
    states: [...node.states].join(", "),
    counties: [...node.counties].join(", "),
    max_voltage_kv: node.maxVoltageKv,
    branch_count: node.branchCount,
    representation: "Co-located buses in the provisional PyPSA-USA topology",
  },
  geometry: { type: "Point", coordinates: node.coordinates },
}));

const interfaceRows = new Map();
for (const row of transmission) {
  const key = row.physical_interface;
  if (!interfaceRows.has(key)) interfaceRows.set(key, []);
  interfaceRows.get(key).push(row);
}

const zoneIds = new Set();
for (const rows of interfaceRows.values()) {
  const [zone0, zone1] = rows[0].physical_interface.split("||");
  zoneIds.add(zone0);
  zoneIds.add(zone1);
}

const zoneNames = { p52: "Western Kansas", p53: "Eastern Kansas" };
const stateNames = { KS: "Kansas", MO: "Missouri", NE: "Nebraska", OK: "Oklahoma" };
const selectedZones = reeds.features.filter((feature) => zoneIds.has(feature.properties.name));
const zoneCenters = new Map(selectedZones.map((feature) => [feature.properties.name, polygonCenter(feature.geometry)]));
const zoneStates = new Map();

for (const row of transmission) {
  zoneStates.set(row.bus0, row.state0);
  zoneStates.set(row.bus1, row.state1);
}
for (const bus of buses) {
  const x = number(bus.x);
  const y = number(bus.y);
  if (x !== null && y !== null) zoneCenters.set(bus.Bus, [x, y]);
  zoneStates.set(bus.Bus, bus.reeds_state);
}

const zoneFeatures = selectedZones.map((feature) => {
  const id = feature.properties.name;
  const state = zoneStates.get(id) ?? null;
  return {
    type: "Feature",
    properties: {
      kind: "zone",
      zone: id,
      name: zoneNames[id] ?? `${stateNames[state] ?? state ?? "Adjacent"} planning zone`,
      state,
      in_kansas: state === "KS",
    },
    geometry: feature.geometry,
  };
});

const interfaceFeatures = [];
for (const [physicalInterface, rows] of interfaceRows) {
  const [zone0, zone1] = physicalInterface.split("||");
  const state0 = zoneStates.get(zone0) ?? rows[0].state0;
  const state1 = zoneStates.get(zone1) ?? rows[0].state1;
  const internal = state0 === "KS" && state1 === "KS";
  let intoKansas = null;
  let outOfKansas = null;
  let direction0to1 = null;
  let direction1to0 = null;

  for (const row of rows) {
    const capacity = number(row.capacity_mw);
    if (capacity === null) continue;
    if (row.bus0 === zone0 && row.bus1 === zone1) direction0to1 = capacity;
    if (row.bus0 === zone1 && row.bus1 === zone0) direction1to0 = capacity;
    if (row.state0 === "KS" && row.state1 !== "KS") outOfKansas = capacity;
    if (row.state0 !== "KS" && row.state1 === "KS") intoKansas = capacity;
  }

  const capacities = [intoKansas, outOfKansas, direction0to1, direction1to0].filter((value) => value !== null);
  interfaceFeatures.push({
    type: "Feature",
    properties: {
      kind: "interface",
      interface: physicalInterface,
      zone0,
      zone1,
      zone0_name: zoneNames[zone0] ?? `${stateNames[state0] ?? state0} ${zone0}`,
      zone1_name: zoneNames[zone1] ?? `${stateNames[state1] ?? state1} ${zone1}`,
      state0,
      state1,
      internal,
      into_kansas_capacity_mw: intoKansas,
      out_of_kansas_capacity_mw: outOfKansas,
      direction_0_to_1_mw: direction0to1,
      direction_1_to_0_mw: direction1to0,
      display_capacity_mw: Math.max(...capacities),
      daily_flow_mwh: null,
      flow_status: "Unavailable — baseline has not been solved",
      representation: "ReEDS/NARIS planning interface",
    },
    geometry: { type: "LineString", coordinates: [zoneCenters.get(zone0), zoneCenters.get(zone1)] },
  });
}

const carrierDetails = {
  onwind: { fuel: "Wind", category: "wind" },
  solar: { fuel: "Solar", category: "solar" },
  OCGT: { fuel: "Natural gas peaker", category: "conventional" },
  CCGT: { fuel: "Natural gas combined cycle", category: "conventional" },
  coal: { fuel: "Coal", category: "conventional" },
  nuclear: { fuel: "Nuclear", category: "conventional" },
  oil: { fuel: "Oil", category: "conventional" },
};
const selectedGenerators = generators.filter((row) => {
  const capacity = number(row.p_nom) ?? 0;
  return capacity > 0 && (row.carrier === "onwind" || row.carrier === "solar" || capacity >= 250);
});
const groupedGenerators = new Map();
for (const row of selectedGenerators) {
  if (!groupedGenerators.has(row.bus)) groupedGenerators.set(row.bus, []);
  groupedGenerators.get(row.bus).push(row);
}

const generatorFeatures = [];
for (const [zone, rows] of groupedGenerators) {
  const center = zoneCenters.get(zone);
  rows.forEach((row, index) => {
    const detail = carrierDetails[row.carrier] ?? { fuel: row.carrier, category: "conventional" };
    const angle = (Math.PI * 2 * index) / rows.length - Math.PI / 2;
    const radius = rows.length > 1 ? 0.26 : 0;
    generatorFeatures.push({
      type: "Feature",
      properties: {
        kind: "generator",
        generator: row.Generator,
        fuel: detail.fuel,
        category: detail.category,
        carrier: row.carrier,
        zone,
        zone_name: zoneNames[zone] ?? zone,
        capacity_mw: number(row.p_nom),
        annual_generation_mwh: null,
        annual_generation_status: "Unavailable — baseline has not been solved",
        status: "Existing in 2019 baseline",
        build_year: number(row.build_year),
        location_basis: "Aggregated PyPSA-USA zone center",
      },
      geometry: {
        type: "Point",
        coordinates: [center[0] + Math.cos(angle) * radius, center[1] + Math.sin(angle) * radius],
      },
    });
  });
}

const output = {
  type: "FeatureCollection",
  name: "Kansas grid planning context",
  properties: {
    model_year: 2019,
    model_status: "Unsolved PyPSA-USA input data model",
    spatial_resolution: "98 ReEDS planning zones",
    topology_status: "Provisional 115 kV+ synthetic AC network; not surveyed infrastructure",
    topology_voltage_floor_kv: MIN_TOPOLOGY_VOLTAGE_KV,
  },
  features: [
    ...zoneFeatures,
    ...interfaceFeatures,
    ...topologyLineFeatures,
    ...topologyNodeFeatures,
    ...generatorFeatures,
  ],
};

const outputPath = join(root, "public", "data", "kansas_grid.geojson");
writeFileSync(outputPath, `${JSON.stringify(output)}\n`, "utf8");
console.log(`Wrote ${output.features.length} features to ${outputPath}`);
