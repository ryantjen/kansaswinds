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
              This planning-scale view maps Kansas generation and the regional interfaces that carry power into and out of the state. It is designed to reveal candidate bottlenecks, not individual transmission towers.
            </p>
            <p className="mt-3">
              The PyPSA-USA baseline has not been dispatched, so interface limits are shown without invented power-flow or annual-generation values.
            </p>
          </div>
        </div>
        <div className="mx-auto max-w-[1800px]">
          <GridMap />
        </div>
      </section>

      <section className="border-y border-ink/15 bg-white/35 px-5 py-24 md:px-10">
        <div className="mx-auto grid max-w-6xl gap-12 lg:grid-cols-2">
          <div>
            <p className="mb-4 text-xs font-semibold uppercase tracking-[0.22em] text-wind">What the map can answer</p>
            <h2 className="font-serif text-4xl tracking-tight md:text-5xl">A first screen for transmission pressure.</h2>
          </div>
          <div className="space-y-5 text-ink/70">
            <p className="leading-7">Compare high-quality wind areas above with the size and directionality of nearby planning interfaces below. Actual congestion requires an optimized dispatch scenario and is not claimed here.</p>
            <div className="grid gap-4 sm:grid-cols-2">
              <MetricCard label="Grid resolution" value="2 Kansas zones" />
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
