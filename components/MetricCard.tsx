type MetricCardProps = { label: string; value: string };

export default function MetricCard({ label, value }: MetricCardProps) {
  return (
    <div className="rounded-xl border border-ink/15 bg-prairie/70 p-5">
      <p className="text-xs uppercase tracking-[0.16em] text-ink/50">{label}</p>
      <p className="mt-2 font-serif text-2xl text-ink">{value}</p>
    </div>
  );
}
