/** Snapshot — every headline stat, every period, one screen.
 *
 * Deliberately the plainest page in the app (user: "focus is on info, not
 * looks"). No charts, no cards, no interpretation: a table you read.
 *
 * Stats run DOWN and periods run ACROSS, per the user's preference. It also
 * happens to be the layout that fits: 15 stats as columns would need
 * horizontal scrolling, whereas 6-7 periods as columns do not.
 */
import { useMemo, useState } from "react";
import { EmptyState } from "../components/shared";
import { cn } from "../lib/cn";
import {
  SNAPSHOT_ROWS,
  snapshotColumns,
  type CustomRange,
} from "../lib/snapshot";
import { useData } from "../state/DataContext";

/** Counts are integers; ratios get 2dp. A period with no games shows "—" for
 * ratios rather than 0.00: a ratio of nothing is undefined, not zero, and
 * rendering it as 0.00 reads as a collapse in form (which is exactly how the
 * "my fours FKDR shows 0" report happened on Trends). */
function cell(value: number, kind: "count" | "ratio", games: number): string {
  if (kind === "count") return value.toLocaleString();
  if (games === 0) return "—";
  return value.toFixed(2);
}

export function SnapshotPage() {
  const { data, loading } = useData();
  const [mode, setMode] = useState<string>("");
  const [custom, setCustom] = useState<CustomRange>({ from: "", to: "" });

  const games = data?.games ?? [];
  const modeGames = useMemo(
    () => (mode ? games.filter((g) => g.mode === mode) : games),
    [games, mode],
  );
  const columns = useMemo(
    () => snapshotColumns(modeGames, new Date(),
      custom.from && custom.to ? custom : undefined),
    [modeGames, custom],
  );

  if (loading && !data) return <div className="text-sm text-muted-foreground">Loading…</div>;
  if (!data?.games.length) return <EmptyState>No games yet.</EmptyState>;

  const num = "px-3 py-1.5 text-right font-mono tabular-nums whitespace-nowrap";

  return (
    <div className="space-y-4 pb-24">
      <div>
        <h1 className="text-3xl font-bold">Snapshot</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Every stat, every period. Week, month and year are rolling windows ending
          today — not calendar months.
        </p>
      </div>

      {/* No minimum-games filter here, unlike Trends: this is a raw numbers
          page, and "Trios: 18 games" is a fact worth showing. */}
      <div className="flex flex-wrap items-center gap-3">
        <div className="flex flex-wrap gap-1.5">
          {["", ...(data?.modes ?? [])].map((m) => (
            <button
              key={m || "all"}
              onClick={() => setMode(m)}
              className={cn(
                "rounded-full border px-3 py-1 text-sm transition-colors",
                mode === m
                  ? "border-foreground/60 bg-muted text-foreground"
                  : "border-border text-muted-foreground hover:text-foreground",
              )}
            >
              {m || "All modes"}
            </button>
          ))}
        </div>
        <label className="ml-auto flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
          custom
          <input
            type="date"
            value={custom.from}
            onChange={(e) => setCustom((c) => ({ ...c, from: e.target.value }))}
            className="rounded-md border border-border bg-background px-2 py-1 text-sm text-foreground outline-none"
          />
          to
          <input
            type="date"
            value={custom.to}
            onChange={(e) => setCustom((c) => ({ ...c, to: e.target.value }))}
            className="rounded-md border border-border bg-background px-2 py-1 text-sm text-foreground outline-none"
          />
          {(custom.from || custom.to) && (
            <button
              onClick={() => setCustom({ from: "", to: "" })}
              className="text-muted-foreground underline hover:text-foreground"
            >
              clear
            </button>
          )}
        </label>
      </div>

      <div className="overflow-x-auto rounded-lg border border-border">
        <table className="w-full border-collapse text-sm">
          <thead>
            <tr className="bg-muted/30">
              <th className="sticky left-0 z-10 bg-background px-3 py-2 text-left text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
                Stat
              </th>
              {columns.map((c) => (
                <th key={c.key} className="px-3 py-2 text-right">
                  <div className="text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
                    {c.label}
                  </div>
                  <div className="font-mono text-[10px] font-normal text-muted-foreground/70">
                    {c.totals.games.toLocaleString()} games
                  </div>
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-border/70">
            {SNAPSHOT_ROWS.map((row) => (
              <tr key={row.key} className="hover:bg-muted/20">
                <td
                  className={cn(
                    "sticky left-0 z-10 bg-background px-3 py-1.5 whitespace-nowrap",
                    row.derived
                      ? "pl-6 text-muted-foreground"
                      : "font-medium text-foreground",
                  )}
                >
                  {row.label}
                </td>
                {columns.map((c) => (
                  <td
                    key={c.key}
                    className={cn(num, row.derived ? "text-muted-foreground" : "text-foreground")}
                  >
                    {cell(row.value(c.totals), row.kind, c.totals.games)}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <p className="text-xs text-muted-foreground">
        Games whose log cut off before the outcome are left out entirely — they
        can't be scored as a win or a loss, so counting them would make games
        played disagree with wins + losses. Resolve one by hand on the Games page
        (right-click) and it starts counting here.
      </p>
      <p className="text-xs text-muted-foreground">
        Ratios divide by 1 when the bottom number is 0, so a period with kills and
        no deaths shows the kill count rather than an error — the same rule the
        rest of the app uses, so these numbers always agree with Today and Trends.
      </p>
    </div>
  );
}
