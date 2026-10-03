"use client";

import type { FeatureCollection, Point } from "geojson";
import { useEffect, useMemo, useState } from "react";

const DATA_URL = "/data/kansas_wind.geojson";
const HOURS_PER_YEAR = 8_760;
const KANSAS_2024_CONSUMPTION_TWH = 41.25821;

type SiteProperties = { capacity_mw: number; capacity_factor: number };
type WindData = FeatureCollection<Point, SiteProperties>;
type CalculationCardProps = { eyebrow: string; value: string; description: string; featured?: boolean };

function CalculationCard({ eyebrow, value, description, featured = false }: CalculationCardProps) {
  return (
    <article className={`rounded-2xl border p-6 md:p-7 ${featured ? "border-wind bg-wind text-white" : "border-ink/15 bg-white/45"}`}>
      <p className={`text-xs font-semibold uppercase tracking-[0.16em] ${featured ? "text-white/60" : "text-ink/45"}`}>{eyebrow}</p>
      <p className="mt-4 font-serif text-4xl tracking-[-0.035em] md:text-5xl">{value}</p>
      <p className={`mt-3 text-sm leading-6 ${featured ? "text-white/70" : "text-ink/60"}`}>{description}</p>
    </article>
  );
}

export default function PotentialCalculator() {
  const [data, setData] = useState<WindData | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    fetch(DATA_URL, { signal: controller.signal })
      .then((response) => {
        if (!response.ok) throw new Error(`Calculation data could not be loaded (${response.status}).`);
        return response.json();
      })
      .then((json: WindData) => setData(json))
      .catch((reason: unknown) => {
        if ((reason as Error).name !== "AbortError") setError((reason as Error).message);
      });
    return () => controller.abort();
  }, []);

  const result = useMemo(() => {
    if (!data?.features.length) return null;
    const sites = data.features.map((feature) => feature.properties);
    const totalCapacityMw = sites.reduce((sum, site) => sum + site.capacity_mw, 0);
    const averageOutputMw = sites.reduce((sum, site) => sum + site.capacity_mw * site.capacity_factor, 0);
    const annualEnergyTwh = averageOutputMw * HOURS_PER_YEAR / 1_000_000;
    return {
      siteCount: sites.length,
      totalCapacityMw,
      averageOutputMw,
      annualEnergyTwh,
      capacityWeightedFactor: averageOutputMw / totalCapacityMw,
      kansasConsumptionMultiple: annualEnergyTwh / KANSAS_2024_CONSUMPTION_TWH,
    };
  }, [data]);

  return (
    <section aria-labelledby="potential-heading" className="mx-auto max-w-[1600px] px-2 pt-12 md:px-4 md:pt-16">
      <div className="grid gap-8 border-t border-ink/15 pt-10 lg:grid-cols-[0.7fr_1.3fr] lg:gap-16">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.22em] text-wind">Putting the resource in context</p>
          <h2 id="potential-heading" className="mt-4 max-w-xl font-serif text-4xl tracking-[-0.035em] md:text-5xl">What could these modeled sites produce?</h2>
          <p className="mt-5 max-w-xl text-sm leading-7 text-ink/65">
            This is a technical-resource estimate, not a buildout forecast. It assumes every modeled site operates at its NREL capacity factor for a full year and does not add new transmission, permitting, financing, or curtailment constraints.
          </p>
        </div>

        {!result && !error && <div className="grid min-h-52 place-items-center rounded-2xl border border-ink/15 text-sm text-ink/50">Calculating from 4,154 sites…</div>}
        {error && <div className="grid min-h-52 place-items-center rounded-2xl border border-ink/15 px-6 text-center text-sm text-ink/60">{error}</div>}
        {result && (
          <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
            <CalculationCard eyebrow="2024 Kansas electricity use" value={`${KANSAS_2024_CONSUMPTION_TWH.toFixed(1)} TWh`} description="Finalized retail electricity sales reported by EIA for all Kansas sectors." />
            <CalculationCard eyebrow="Modeled Kansas capacity" value={`${(result.totalCapacityMw / 1_000).toFixed(1)} GW`} description={`Sum of NREL capacity across all ${result.siteCount.toLocaleString()} modeled Kansas sites.`} />
            <CalculationCard eyebrow="Capacity-weighted factor" value={`${(result.capacityWeightedFactor * 100).toFixed(1)}%`} description="Capacity-weighted average of the site-level modeled factors." />
            <CalculationCard eyebrow="Average continuous output" value={`${(result.averageOutputMw / 1_000).toFixed(1)} GW`} description="Modeled capacity multiplied by capacity factor at every site." />
            <CalculationCard eyebrow="Modeled annual output" value={`${result.annualEnergyTwh.toFixed(1)} TWh`} description="Average output multiplied by 8,760 hours in a standard year." featured />
            <CalculationCard eyebrow="Compared with Kansas use" value={`${result.kansasConsumptionMultiple.toFixed(1)}×`} description="Modeled annual output divided by Kansas’s 2024 retail electricity sales." />
          </div>
        )}
      </div>

      <div className="mt-8 flex flex-col gap-3 border-t border-ink/10 pt-5 text-xs leading-5 text-ink/50 md:flex-row md:items-start md:justify-between">
        <p><span className="font-semibold text-ink/70">Formula:</span> annual MWh = Σ(site capacity MW × site capacity factor × 8,760).</p>
        <p className="md:text-right">
          Sources: <a className="underline underline-offset-2 hover:text-ink" href="https://doi.org/10.7799/1329290" target="_blank" rel="noreferrer">NREL WIND Toolkit Power Data Site Index</a>
          {" · "}<a className="underline underline-offset-2 hover:text-ink" href="https://www.eia.gov/electricity/state/Kansas/" target="_blank" rel="noreferrer">U.S. EIA, Kansas Electricity Profile 2024</a>
        </p>
      </div>
    </section>
  );
}
