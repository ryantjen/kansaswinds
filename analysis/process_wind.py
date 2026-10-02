"""Convert the NREL WIND Toolkit site index to Kansas GeoJSON points.

Usage: python analysis/process_wind.py path/to/wtk_site_metadata.csv
"""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

OUTPUT = Path(__file__).parents[1] / "public" / "data" / "kansas_wind.geojson"


def main(source: Path) -> None:
    features = []
    with source.open(newline="", encoding="utf-8-sig") as handle:
        for row in csv.DictReader(handle):
            if row["State"] != "Kansas":
                continue
            features.append(
                {
                    "type": "Feature",
                    "id": int(row["site_id"]),
                    "geometry": {
                        "type": "Point",
                        "coordinates": [float(row["longitude"]), float(row["latitude"])],
                    },
                    "properties": {
                        "site_id": int(row["site_id"]),
                        "state": row["State"],
                        "county": row["County"],
                        "fraction_of_usable_area": float(row["fraction_of_usable_area"]),
                        "power_curve": int(row["power_curve"]),
                        "capacity_mw": float(row["capacity"]),
                        "wind_speed_mps": float(row["wind_speed"]),
                        "capacity_factor": float(row["capacity_factor"]),
                        "full_timeseries_directory": int(row["full_timeseries_directory"]),
                        "full_timeseries_path": row["full_timeseries_path"],
                    },
                }
            )

    collection = {
        "type": "FeatureCollection",
        "name": "Kansas WIND Toolkit sites",
        "metadata": {
            "source": "NREL WIND Toolkit Power Data Site Index",
            "doi": "10.7799/1329290",
            "source_crs": "EPSG:4326",
            "feature_count": len(features),
        },
        "features": features,
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(collection, separators=(",", ":")), encoding="utf-8")
    print(f"Wrote {len(features):,} Kansas sites to {OUTPUT}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("Pass the path to wtk_site_metadata.csv")
    main(Path(sys.argv[1]))
