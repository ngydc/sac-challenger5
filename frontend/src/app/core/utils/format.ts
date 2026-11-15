/** Display helpers. All dates from the backend are UTC ISO strings. */

const DAY: Intl.DateTimeFormatOptions = {
  day: 'numeric',
  month: 'short',
  year: 'numeric',
  timeZone: 'UTC',
};

export function fmtDate(iso: string | null | undefined): string {
  if (!iso) return '–';
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleDateString('en-GB', DAY);
}

export function fmtRange(a: string | null | undefined, b: string | null | undefined): string {
  return a && b ? `${fmtDate(a)} – ${fmtDate(b)}` : '–';
}

export function fmtUm(r: { min: number; max: number } | null | undefined): string {
  return r ? `${r.min.toFixed(2)}–${r.max.toFixed(2)} µm` : '–';
}

export function fmtDuration(seconds: number): string {
  if (!Number.isFinite(seconds) || seconds <= 0) return 'a moment';
  if (seconds < 90) return 'about a minute';
  const min = Math.round(seconds / 60);
  if (min < 60) return `about ${min} minutes`;
  const h = Math.floor(min / 60);
  const m = Math.round((min % 60) / 5) * 5;
  return `about ${h} h${m ? ` ${m} min` : ''}`;
}

/** Bundle title: "D3" for one detector, "All detectors" for the overview. */
export function bundleTitle(b: { id: string; kind: string }): string {
  return b.kind === 'all' ? 'All detectors' : b.id;
}
