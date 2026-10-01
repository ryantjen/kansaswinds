type ConstraintToggleProps = { disabled?: boolean };

export default function ConstraintToggle({ disabled = false }: ConstraintToggleProps) {
  return (
    <div className="flex items-center justify-between rounded-xl border border-ink/15 p-4">
      <div><p className="font-medium text-ink">Land constraints</p><p className="text-sm">Awaiting exclusions.geojson</p></div>
      <button type="button" disabled={disabled} aria-label="Toggle land constraints" className="h-7 w-12 cursor-not-allowed rounded-full bg-ink/15 p-1 opacity-70">
        <span className="block h-5 w-5 rounded-full bg-white shadow-sm" />
      </button>
    </div>
  );
}
