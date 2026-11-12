/** "Custom…" date range: two local-date inputs and their bounds in Unix seconds. */

export type CustomDates = { from: string; to: string };

const iso = (d: Date) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;

/** The last `days` days up to today, as the starting point for a custom range. */
export function defaultCustom(days = 7): CustomDates {
  const to = new Date();
  const from = new Date(to.getFullYear(), to.getMonth(), to.getDate() - (days - 1));
  return { from: iso(from), to: iso(to) };
}

/** From the start of `from` to the end of `to`, local time. Empty fields leave that side open. */
export function customBounds({ from, to }: CustomDates): { since?: number; until?: number } {
  const day = (s: string) => {
    const [y, m, d] = s.split("-").map(Number);
    return new Date(y, m - 1, d);
  };
  let a = from ? day(from) : null;
  let b = to ? day(to) : null;
  if (a && b && a > b) [a, b] = [b, a];
  return {
    since: a ? a.getTime() / 1000 : undefined,
    until: b ? new Date(b.getFullYear(), b.getMonth(), b.getDate() + 1).getTime() / 1000 - 0.001 : undefined,
  };
}

export function CustomRange({ value, onChange, className = "input py-1 w-auto" }: {
  value: CustomDates; onChange: (v: CustomDates) => void; className?: string;
}) {
  const today = iso(new Date());
  return (
    <span className="inline-flex items-center gap-1.5" role="group" aria-label="Custom date range">
      <input type="date" className={className} value={value.from} max={value.to || today} aria-label="From"
        onChange={(e) => onChange({ ...value, from: e.target.value })} />
      <span className="text-muted">to</span>
      <input type="date" className={className} value={value.to} min={value.from || undefined} max={today} aria-label="To"
        onChange={(e) => onChange({ ...value, to: e.target.value })} />
    </span>
  );
}
