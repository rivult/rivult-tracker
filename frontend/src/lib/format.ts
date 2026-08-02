/** Formatting helpers shared across pages. */

export function mmss(s: number | null | undefined): string {
  if (s == null) return "—";
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}

export function playtime(s: number): string {
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  return h ? `${h}h ${m}m` : `${m}m`;
}

/** Local date as "YYYY-MM-DD" — matches the backend's `date` column.
 * Never toISOString(): at 11pm local, UTC is already tomorrow. */
export function localISO(d: Date): string {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(
    d.getDate(),
  ).padStart(2, "0")}`;
}

export function todayISO(): string {
  return localISO(new Date());
}

export function daysAgoISO(days: number): string {
  return localISO(new Date(Date.now() - days * 86_400_000));
}

/** "2026-08-14" -> "Aug 14, 2026" (parsed as local, not UTC). */
export function prettyDate(iso: string): string {
  const [y, m, d] = iso.split("-").map(Number);
  if (!y || !m || !d) return iso;
  return new Date(y, m - 1, d).toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
}

export function prettyDateShort(iso: string): string {
  const [y, m, d] = iso.split("-").map(Number);
  if (!y || !m || !d) return iso;
  return new Date(y, m - 1, d).toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
  });
}

/** Ratio display: whole numbers stay clean, others get 2 decimals. */
export function ratio(n: number): string {
  return Number.isInteger(n) ? String(n) : n.toFixed(2);
}

/** Signed delta for improvement/decline labels. */
export function signed(n: number, digits = 2): string {
  return `${n >= 0 ? "+" : ""}${n.toFixed(digits)}`;
}

/** Deterministic fallback color for tags the backend stored without one. */
const TAG_PALETTE = [
  "#ff7b72",
  "#d29922",
  "#58a6ff",
  "#7ee787",
  "#d2a8ff",
  "#f778ba",
  "#79c0ff",
  "#ffa657",
];

export function tagColor(name: string, stored: string | null): string {
  if (stored) return stored;
  let h = 0;
  for (const c of name) h = (h * 31 + c.charCodeAt(0)) >>> 0;
  return TAG_PALETTE[h % TAG_PALETTE.length];
}
