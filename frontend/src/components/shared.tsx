/** Small shared presentational pieces used across pages. */
import type { ReactNode } from "react";
import { ArrowDownRight, ArrowUpRight } from "lucide-react";
import { cn } from "../lib/cn";
import { ratio } from "../lib/format";
import { DEFAULT_RANGE, RANGE_KEYS, type DateRange, type RangeKey } from "../lib/stats";

export function Card({ className, children }: { className?: string; children: ReactNode }) {
  return (
    <div className={cn("rounded-lg border border-border bg-card", className)}>{children}</div>
  );
}

export function CardLabel({ children }: { children: ReactNode }) {
  return (
    <div className="text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
      {children}
    </div>
  );
}

export function EmptyState({ children }: { children: ReactNode }) {
  return (
    <div className="rounded-lg border border-dashed border-border p-8 text-center text-sm text-muted-foreground">
      {children}
    </div>
  );
}

/** Per-page date-range control (never in the header — different pages can
 * hold different windows simultaneously). */
export function RangeChips({
  value,
  onChange,
}: {
  value: RangeKey;
  onChange: (r: RangeKey) => void;
}) {
  return (
    <div className="flex rounded-md bg-muted p-0.5">
      {RANGE_KEYS.map((r) => (
        <button
          key={r}
          onClick={() => onChange(r)}
          className={cn(
            "rounded-sm px-3 py-1 text-sm transition-colors",
            value === r
              ? "bg-card text-foreground shadow-sm"
              : "text-muted-foreground hover:text-foreground",
          )}
        >
          {r === "all" ? "All time" : r}
        </button>
      ))}
    </div>
  );
}

/** Presets PLUS an exact from/to pair — "want the last month? easy", but also
 * "exactly these days".
 *
 * Picking a date switches the range to `custom` automatically; clicking a
 * preset chip clears the dates. The two can't disagree, so what's highlighted
 * is always what's actually filtering.
 */
export function RangePicker({
  value,
  onChange,
}: {
  value: DateRange;
  onChange: (r: DateRange) => void;
}) {
  const custom = value.key === "custom";
  const dateCls =
    "rounded-md border border-border bg-background px-2 py-1 text-xs text-foreground outline-none focus:border-muted-foreground/60";

  return (
    <div className="flex flex-wrap items-center gap-2">
      <div className="flex rounded-md bg-muted p-0.5">
        {RANGE_KEYS.map((r) => (
          <button
            key={r}
            onClick={() => onChange({ key: r })}
            className={cn(
              "rounded-sm px-3 py-1 text-sm transition-colors",
              value.key === r
                ? "bg-card text-foreground shadow-sm"
                : "text-muted-foreground hover:text-foreground",
            )}
          >
            {r === "all" ? "All time" : r}
          </button>
        ))}
      </div>
      <div
        className={cn(
          "flex items-center gap-1.5 rounded-md border px-2 py-1 transition-colors",
          custom ? "border-foreground/50 bg-muted/40" : "border-transparent",
        )}
      >
        <input
          type="date"
          aria-label="From date"
          value={value.from ?? ""}
          max={value.to || undefined}
          onChange={(e) =>
            onChange({ key: "custom", from: e.target.value || undefined, to: value.to })
          }
          className={dateCls}
        />
        <span className="text-xs text-muted-foreground">to</span>
        <input
          type="date"
          aria-label="To date"
          value={value.to ?? ""}
          min={value.from || undefined}
          onChange={(e) =>
            onChange({ key: "custom", from: value.from, to: e.target.value || undefined })
          }
          className={dateCls}
        />
        {custom && (
          <button
            onClick={() => onChange(DEFAULT_RANGE)}
            className="rounded px-1 text-xs text-muted-foreground hover:text-foreground"
            aria-label="Clear custom dates"
          >
            ✕
          </button>
        )}
      </div>
    </div>
  );
}

/** Numerator / denominator / ratio column — the stat grid's vertical logic:
 * row 1 good count, row 2 bad count, row 3 the ratio they produce. */
export function StatColumn({
  title,
  ratioValue,
  goodLabel,
  goodValue,
  badLabel,
  badValue,
  deEmphasized = false,
}: {
  title: string;
  ratioValue: number;
  goodLabel: string;
  goodValue: number;
  badLabel: string;
  badValue: number;
  deEmphasized?: boolean;
}) {
  return (
    <div className={cn("flex flex-col gap-5", deEmphasized && "origin-top-left scale-95 opacity-60")}>
      <div className="flex flex-col gap-2.5">
        <div>
          <div className="text-xl font-medium">{goodValue}</div>
          <div className="text-xs text-muted-foreground">{goodLabel}</div>
        </div>
        <div>
          <div className="text-xl font-medium">{badValue}</div>
          <div className="text-xs text-muted-foreground">{badLabel}</div>
        </div>
      </div>
      <div className="border-t border-border pt-3">
        <div className="text-3xl font-bold tabular-nums">{ratio(ratioValue)}</div>
        <div className="text-xs font-medium uppercase tracking-wider text-muted-foreground">{title}</div>
      </div>
    </div>
  );
}

/** Green-up / red-down delta arrow next to a hero number. */
export function DeltaArrow({ delta, digits = 2 }: { delta: number; digits?: number }) {
  const up = delta >= 0;
  return (
    <div
      className={cn(
        "flex items-center text-2xl font-bold",
        up ? "text-success" : "text-danger",
      )}
      title="vs previous played day"
    >
      {up ? <ArrowUpRight className="mr-0.5 h-7 w-7" /> : <ArrowDownRight className="mr-0.5 h-7 w-7" />}
      {Math.abs(delta).toFixed(digits)}
    </div>
  );
}
