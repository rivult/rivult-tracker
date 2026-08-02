/** App header: name · tag filter dropdown. The filter is global and persistent
 * across stat pages; on pages where it doesn't apply it is greyed out, never
 * hidden.
 *
 * The All/Untagged/Tagged toggle that used to sit here was removed 2026-08-01:
 * it duplicated what the tag list already does (untagged = exclude all, tagged
 * = include all) and two overlapping controls made the active filter ambiguous.
 */
import { useMemo, useRef, useState } from "react";
import { ChevronDown, Filter, X } from "lucide-react";
import type { Tag } from "../api/types";
import { cn } from "../lib/cn";
import { tagColor } from "../lib/format";
import { useData } from "../state/DataContext";

export function Header({ filterApplies }: { filterApplies: boolean }) {
  const { data, filter, setFilter } = useData();
  const [open, setOpen] = useState(false);
  const btnRef = useRef<HTMLButtonElement>(null);
  const tags = data?.tags ?? [];

  const activeCount = filter.include.length + filter.exclude.length;
  const isActive = activeCount > 0;

  const cycle = (t: Tag) => {
    const inInc = filter.include.includes(t.name);
    const inExc = filter.exclude.includes(t.name);
    // off -> include -> exclude -> off
    if (!inInc && !inExc) {
      setFilter({ ...filter, include: [...filter.include, t.name] });
    } else if (inInc) {
      setFilter({
        ...filter,
        include: filter.include.filter((n) => n !== t.name),
        exclude: [...filter.exclude, t.name],
      });
    } else {
      setFilter({ ...filter, exclude: filter.exclude.filter((n) => n !== t.name) });
    }
  };

  // Spelled out rather than "+2 · −1": a bare "−1" reads as negative one, not
  // as "one tag excluded", which is the opposite of reassuring on a chip whose
  // whole job is telling you the numbers below are filtered.
  const summary = useMemo(() => {
    if (!isActive) return "Tag filter";
    const parts: string[] = [];
    if (filter.include.length) parts.push(`${filter.include.length} only`);
    if (filter.exclude.length) parts.push(`${filter.exclude.length} hidden`);
    return parts.join(" · ");
  }, [filter, isActive]);

  return (
    <header className="flex h-12 shrink-0 items-center border-b border-border bg-background px-4 z-30">
      <div className="w-52 shrink-0 font-bold tracking-tight">
        Rivult <span className="text-muted-foreground font-medium">Bedwars Tracker</span>
      </div>

      <div className={cn("flex flex-1 items-center justify-center gap-3", !filterApplies && "pointer-events-none opacity-40")}>
        <div className="relative">
          <button
            ref={btnRef}
            onClick={() => setOpen(!open)}
            className={cn(
              "flex items-center gap-2 rounded-md border px-3 py-1.5 text-sm transition-colors",
              isActive
                ? "border-success/60 bg-success/10 text-foreground"
                : "border-border bg-muted text-muted-foreground hover:text-foreground",
            )}
          >
            <Filter className="h-4 w-4" />
            <span>{summary}</span>
            <ChevronDown className={cn("h-4 w-4 opacity-50 transition-transform", open && "rotate-180")} />
          </button>

          {open && (
            <>
              <div className="fixed inset-0 z-40" onClick={() => setOpen(false)} />
              <div className="absolute right-0 top-full z-50 mt-1.5 w-64 rounded-lg border border-border bg-card p-2 shadow-xl shadow-black/50">
                <div className="flex items-center justify-between px-1.5 pb-1.5">
                  <span className="text-[11px] uppercase tracking-wider text-muted-foreground">
                    Include / exclude tags
                  </span>
                  {activeCount > 0 && (
                    <button
                      onClick={() => setFilter({ ...filter, include: [], exclude: [] })}
                      className="flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground"
                    >
                      <X className="h-3 w-3" /> clear
                    </button>
                  )}
                </div>
                {tags.length === 0 && (
                  <div className="px-1.5 py-2 text-sm text-muted-foreground">
                    No tags yet — create them from any game row.
                  </div>
                )}
                {tags.map((t) => {
                  const state = filter.include.includes(t.name)
                    ? "include"
                    : filter.exclude.includes(t.name)
                      ? "exclude"
                      : "off";
                  return (
                    <button
                      key={t.id}
                      onClick={() => cycle(t)}
                      title="Click to cycle: off → include → exclude"
                      className="flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-sm transition-colors hover:bg-muted"
                    >
                      <span className="h-2 w-2 rounded-full" style={{ backgroundColor: tagColor(t.name, t.color) }} />
                      <span className="flex-1 text-left">{t.name}</span>
                      {state === "include" && (
                        <span className="rounded bg-success/20 px-1.5 py-0.5 text-[11px] font-medium text-success">include</span>
                      )}
                      {state === "exclude" && (
                        <span className="rounded bg-danger/20 px-1.5 py-0.5 text-[11px] font-medium text-danger">exclude</span>
                      )}
                    </button>
                  );
                })}
                <div className="mt-1 border-t border-border px-1.5 pt-1.5 text-[11px] leading-4 text-muted-foreground">
                  Applies everywhere: Today, Games, Breakdowns, Trends.
                </div>
              </div>
            </>
          )}
        </div>
      </div>

      <div className="w-52 shrink-0 text-right text-xs text-muted-foreground truncate">
        {data?.you ? `tracking ${data.you}` : ""}
      </div>
    </header>
  );
}
