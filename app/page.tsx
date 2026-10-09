import GridMap from "@/components/GridMap";
import MetricCard from "@/components/MetricCard";
import PotentialCalculator from "@/components/PotentialCalculator";
import WindMap from "@/components/WindMap";

export default function Home() {
  return (
    <main>
      <header className="border-b border-ink/15 px-5 py-5 md:px-10">
        <div className="mx-auto flex max-w-[1600px] items-center justify-between">
          <a href="#top" className="font-serif text-lg font-semibold tracking-tight">Kansas / Wind</a>
          <span className="text-xs uppercase tracking-[0.18em] text-ink/60">An energy atlas</span>
        </div>
      </header>

      <section id="top" className="px-5 pb-8 pt-14 md:px-10 md:pt-20">
        <div className="mx-auto max-w-[1600px]">
          <p className="mb-5 text-xs font-semibold uppercase tracking-[0.22em] text-wind">The resource</p>
          <div className="grid gap-8 lg:grid-cols-[minmax(0,0.8fr)_minmax(22rem,1.2fr)] lg:items-end">
            <h1 className="max-w-4xl font-serif text-5xl leading-[0.98] tracking-[-0.045em] md:text-7xl xl:text-8xl">
              How much wind can Kansas turn into power?
            </h1>
            <p className="max-w-xl text-base leading-7 text-ink/70 lg:justify-self-end lg:text-lg">
              Explore modeled capacity factor across the state. This first view reads directly from the project’s Kansas wind dataset.
            </p>
          </div>
        </div>
      </section>

      <section aria-labelledby="map-heading" className="px-3 pb-24 md:px-6">
        <h2 id="map-heading" className="sr-only">Kansas wind capacity factor map</h2>
        <WindMap />
        <PotentialCalculator />
      </section>

      <section aria-labelledby="grid-heading" className="border-t border-ink/15 px-3 pb-24 pt-20 md:px-6 md:pt-28">
        <div className="mx-auto mb-10 grid max-w-[1600px] gap-7 px-2 md:px-4 lg:grid-cols-[minmax(0,0.9fr)_minmax(22rem,1.1fr)] lg:items-end">
          <div>
            <p className="mb-4 text-xs font-semibold uppercase tracking-[0.22em] text-grid">The grid context</p>
            <h2 id="grid-heading" className="max-w-3xl font-serif text-4xl tracking-tight md:text-5xl">
              Where new wind would meet the existing system.
            </h2>
          </div>
          <div className="max-w-2xl text-sm leading-6 text-ink/65 lg:justify-self-end md:text-base md:leading-7">
            <p>
              The topology view now exposes the provisional 115 kV-and-above AC network that touches Kansas. Switch to planning interfaces to see the coarser transfer limits used by the current PyPSA baseline.
            </p>
            <p className="mt-3">
              The detailed branches are synthetic rather than surveyed infrastructure. The baseline has not been dispatched, so capacities are shown without invented power-flow or annual-generation values.
            </p>
          </div>
        </div>
        <div className="mx-auto max-w-[1800px]">
          <GridMap />
        </div>

        <div className="mx-auto mt-10 grid max-w-[1600px] gap-px overflow-hidden rounded-2xl border border-ink/15 bg-ink/15 md:grid-cols-2 xl:grid-cols-4">
          <article className="bg-prairie p-6">
            <p className="text-xs font-semibold uppercase tracking-[0.16em] text-grid">1 · Actual generation</p>
            <h3 className="mt-3 font-serif text-2xl">Join EIA-923 by plant.</h3>
            <p className="mt-3 text-sm leading-6 text-ink/65">Use annual plant and prime-mover net generation, then attach EIA-860 coordinates. This is observed MWh, not a dispatch estimate.</p>
            <a className="mt-4 inline-block text-sm font-semibold text-wind underline decoration-wind/30 underline-offset-4" href="https://www.eia.gov/electricity/data/eia923/">EIA-923 detailed data</a>
          </article>
          <article className="bg-prairie p-6">
            <p className="text-xs font-semibold uppercase tracking-[0.16em] text-grid">2 · Actual grid movement</p>
            <h3 className="mt-3 font-serif text-2xl">Use EIA-930 for area ties.</h3>
            <p className="mt-3 text-sm leading-6 text-ink/65">EIA-930 provides hourly interchange between balancing authorities. It does not reveal flow on individual AC branches.</p>
            <a className="mt-4 inline-block text-sm font-semibold text-wind underline decoration-wind/30 underline-offset-4" href="https://www.eia.gov/opendata/browser/electricity/rto/interchange-data">EIA hourly interchange</a>
          </article>
          <article className="bg-prairie p-6">
            <p className="text-xs font-semibold uppercase tracking-[0.16em] text-grid">3 · Observed congestion</p>
            <h3 className="mt-3 font-serif text-2xl">Ingest SPP market constraints.</h3>
            <p className="mt-3 text-sm leading-6 text-ink/65">Binding constraints, effective limits, and the LMP congestion component identify recurring constrained facilities and price separation.</p>
            <a className="mt-4 inline-block text-sm font-semibold text-wind underline decoration-wind/30 underline-offset-4" href="https://portal.spp.org/groups/real-time-balancing-market">SPP real-time market data</a>
          </article>
          <article className="bg-prairie p-6">
            <p className="text-xs font-semibold uppercase tracking-[0.16em] text-grid">4 · Modeled branch flow</p>
            <h3 className="mt-3 font-serif text-2xl">Solve the hourly network.</h3>
            <p className="mt-3 text-sm leading-6 text-ink/65">For each branch, aggregate hourly MW into net and absolute MWh, utilization, congested hours, and shadow price. That makes scenario comparisons possible.</p>
          </article>
        </div>
      </section>

      <section className="border-y border-ink/15 bg-white/35 px-5 py-24 md:px-10">
        <div className="mx-auto grid max-w-6xl gap-12 lg:grid-cols-2">
          <div>
            <p className="mb-4 text-xs font-semibold uppercase tracking-[0.22em] text-wind">What the map can answer</p>
            <h2 className="font-serif text-4xl tracking-tight md:text-5xl">A first screen for transmission pressure.</h2>
          </div>
          <div className="space-y-5 text-ink/70">
            <p className="leading-7">Trace high-quality wind areas against the 115 kV+ network, then switch to the planning interfaces that constrain regional transfers. Actual congestion still requires SPP market observations or an optimized hourly dispatch and is not claimed here.</p>
            <div className="grid gap-4 sm:grid-cols-2">
              <MetricCard label="Topology" value="115 kV+ branches" />
              <MetricCard label="Model state" value="Unsolved baseline" />
            </div>
          </div>
        </div>
      </section>

      <footer className="px-5 py-8 text-sm text-ink/55 md:px-10">
        <div className="mx-auto flex max-w-[1600px] justify-between gap-4">
          <span>Kansas Wind Potential</span><span>Data before claims.</span>
        </div>
      </footer>
    </main>
  );
}
