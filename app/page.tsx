import ConstraintToggle from "@/components/ConstraintToggle";
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
      </section>

      <section className="border-y border-ink/15 bg-white/35 px-5 py-24 md:px-10">
        <div className="mx-auto grid max-w-6xl gap-12 lg:grid-cols-2">
          <div>
            <p className="mb-4 text-xs font-semibold uppercase tracking-[0.22em] text-wind">Coming next</p>
            <h2 className="font-serif text-4xl tracking-tight md:text-5xl">From wind resource to buildable potential.</h2>
          </div>
          <div className="space-y-5 text-ink/70">
            <p className="leading-7">Later sections will introduce transmission and exclusions only when their source files are available.</p>
            <div className="grid gap-4 sm:grid-cols-2">
              <MetricCard label="Mapped metric" value="Capacity factor" />
              <MetricCard label="Geography" value="Kansas" />
            </div>
            <ConstraintToggle disabled />
            <PotentialCalculator />
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
