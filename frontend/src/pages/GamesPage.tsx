/** Games — dense history grouped by DAY (expandable). Local filters
 * layer on top of the global header filter; Ctrl+click multi-select for
 * batch tagging lives in GamesTable. No per-game FKDR is displayed
 * (meaningless at n=1) — sorting by it is allowed.
 */
import { useEffect, useMemo, useState } from "react";
import { ArrowDown, ArrowUp, ChevronDown, Search } from "lucide-react";
import type { Game } from "../api/types";
import { api } from "../api/client";
import { GamesTable } from "../components/GamesTable";
import { HistoryClampBanner } from "../components/Locked";
import { Card } from "../components/shared";
import { cn } from "../lib/cn";
import { daysAgoISO, prettyDate, ratio } from "../lib/format";
import {
  EMPTY_LOCAL_FILTERS,
  applyLocalFilters,
  chronological,
  distinct,
  daysOf,
  type LocalFilters,
} from "../lib/stats";
import { useData } from "../state/DataContext";

/** Sorting is for MAGNITUDE — "show me my best/worst games". Sorting
 * alphabetically by map, mode, result or teammate was removed 2026-08-01: those
 * are categories, and the filter row above already answers "show me only Rush"
 * far better than scrolling to where the R's start. */
type SortKey = "date" | "fkdr" | "length" | "finals" | "beds";

const SORTS: { key: SortKey; label: string }[] = [
  { key: "date", label: "Date" },
  { key: "fkdr", label: "FKDR" },
  { key: "length", label: "Length" },
  { key: "finals", label: "Finals" },
  { key: "beds", label: "Beds" },
];

function comparator(key: SortKey): (a: Game, b: Game) => number {
  const fk = (g: Game) =>
    (g.your_final_kills ?? 0) / Math.max(g.your_final_deaths ?? 0, 1);
  switch (key) {
    case "fkdr":
      return (a, b) => fk(a) - fk(b);
    case "length":
      return (a, b) => (a.duration_s ?? 0) - (b.duration_s ?? 0);
    case "finals":
      return (a, b) => (a.your_final_kills ?? 0) - (b.your_final_kills ?? 0);
    case "beds":
      return (a, b) => (a.beds_broken ?? 0) - (b.beds_broken ?? 0);
    default:
      return () => 0;
  }
}

const selectCls =
  "rounded-md border border-border bg-card px-2 py-1.5 text-sm text-foreground outline-none hover:bg-muted/50";

const FREE_HISTORY_DAYS = 90; // free tier sees the last 3 months

export function GamesPage() {
  const { data, loading, newGameIds, premium } = useData();
  const [filters, setFilters] = useState<LocalFilters>(EMPTY_LOCAL_FILTERS);
  // Games whose ROSTER matches the search box, from the server — rosters
  // aren't in the dashboard payload. null = no answer yet (in flight, or the
  // query is too short), which is not the same as "nobody matched".
  const [playerIds, setPlayerIds] = useState<ReadonlySet<number> | null>(null);
  const [sort, setSort] = useState<SortKey>("date");
  const [desc, setDesc] = useState(true);
  const [expanded, setExpanded] = useState<ReadonlySet<string> | null>(null);

  const games = useMemo(() => {
    // Unresolved games are merged in for DISPLAY only, so you can act on them
    // (right-click → mark win/loss/remove). They carry counted:false; every
    // number on every page still comes from data.games alone.
    //
    // Games on an un-ticked account are NOT here — the server doesn't send
    // them. They used to render greyed with a "not counted" label, which read
    // as clutter; Settings → Accounts is how you get an alt's history back.
    const all = [...(data?.games ?? []), ...(data?.unresolved ?? [])];
    if (premium) return all;
    const from = daysAgoISO(FREE_HISTORY_DAYS);
    return all.filter((g) => (g.date ?? "") >= from);
  }, [data, premium]);
  // Ask the server which games contain a player matching the search text.
  // Debounced, with a stale guard: an earlier reply arriving late would
  // otherwise widen the results for a query the user has already changed.
  useEffect(() => {
    const q = filters.search.trim();
    if (q.length < 2) {
      setPlayerIds(null);
      return;
    }
    let live = true;
    const t = window.setTimeout(() => {
      api
        .searchGames(q)
        .then((r) => live && setPlayerIds(new Set(r.game_ids)))
        // a failed roster lookup must not blank the list — fall back to
        // text-only matching, which still works entirely client-side
        .catch(() => live && setPlayerIds(null));
    }, 200);
    return () => {
      live = false;
      window.clearTimeout(t);
    };
  }, [filters.search]);

  const filtered = useMemo(
    () => applyLocalFilters(games, filters, playerIds ? new Set(playerIds) : null),
    [games, filters, playerIds],
  );
  const days = useMemo(() => daysOf(filtered), [filtered]);

  if (loading && !data) return <div className="text-sm text-muted-foreground">Loading…</div>;

  const maps = distinct(games.map((g) => g.map));
  const anyLocal =
    filters.map ||
    filters.mode ||
    filters.result ||
    filters.teammate ||
    filters.search.trim();
  // Most recent DAY starts expanded; user toggles override.
  const expandedSet = expanded ?? new Set(days.slice(0, 1).map((d) => d.key));

  const set = (patch: Partial<LocalFilters>) => setFilters({ ...filters, ...patch });

  const flatSorted =
    sort === "date"
      ? null
      : (() => {
          const cmp = comparator(sort);
          const out = [...filtered].sort((a, b) => cmp(a, b) * (desc ? -1 : 1));
          return out;
        })();

  return (
    <div className="space-y-6 pb-24">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-3xl font-bold">Games</h1>
        <div className="flex items-center gap-2 rounded-md border border-border bg-card px-3 py-1.5 text-sm">
          <Search className="h-4 w-4 text-muted-foreground" />
          <input
            value={filters.search}
            onChange={(e) => set({ search: e.target.value })}
            placeholder="Search map, player, tag…"
            className="w-52 bg-transparent outline-none placeholder:text-muted-foreground"
          />
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-2 text-sm">
        <select className={selectCls} value={filters.map} onChange={(e) => set({ map: e.target.value })}>
          <option value="">All maps</option>
          {maps.map((m) => (
            <option key={m} value={m}>{m}</option>
          ))}
        </select>
        <select className={selectCls} value={filters.mode} onChange={(e) => set({ mode: e.target.value })}>
          <option value="">All modes</option>
          {(data?.modes ?? []).map((m) => (
            <option key={m} value={m}>{m}</option>
          ))}
        </select>
        <select
          className={selectCls}
          value={filters.result}
          onChange={(e) => set({ result: e.target.value as LocalFilters["result"] })}
        >
          <option value="">Any result</option>
          <option value="WIN">Wins</option>
          <option value="FINAL_DEATH">Losses</option>
          <option value="UNRESOLVED">Unresolved</option>
        </select>
        <select
          className={selectCls}
          value={filters.teammate}
          onChange={(e) => set({ teammate: e.target.value })}
        >
          <option value="">Anyone</option>
          {(data?.teammates ?? []).map((t) => (
            <option key={t.ign} value={t.ign}>
              {t.ign} ({t.games})
            </option>
          ))}
        </select>

        <span className="ml-2 text-xs uppercase tracking-wider text-muted-foreground">sort</span>
        <select className={selectCls} value={sort} onChange={(e) => setSort(e.target.value as SortKey)}>
          {SORTS.map((s) => (
            <option key={s.key} value={s.key}>{s.label}</option>
          ))}
        </select>
        <button
          onClick={() => setDesc(!desc)}
          className="rounded-md border border-border bg-card p-1.5 hover:bg-muted/50"
          title="Flip direction"
        >
          {desc ? <ArrowDown className="h-4 w-4" /> : <ArrowUp className="h-4 w-4" />}
        </button>
        {anyLocal && (
          <button
            onClick={() => {
              setFilters(EMPTY_LOCAL_FILTERS);
              setPlayerIds(null);
            }}
            className="text-muted-foreground hover:text-foreground"
          >
            clear
          </button>
        )}
      </div>

      {!premium && <HistoryClampBanner />}

      <div className="text-xs text-muted-foreground">
        {filtered.length} game{filtered.length === 1 ? "" : "s"}
        {anyLocal ? " (filtered)" : ""}
      </div>

      {flatSorted ? (
        <Card className="overflow-hidden">
          <GamesTable games={flatSorted} highlightIds={newGameIds} />
        </Card>
      ) : (
        <div className="space-y-3">
          {days.map((s) => {
            const open = expandedSet.has(s.key);
            return (
              <Card key={s.key} className="overflow-hidden">
                <button
                  onClick={() => {
                    const next = new Set(expandedSet);
                    if (open) next.delete(s.key);
                    else next.add(s.key);
                    setExpanded(next);
                  }}
                  className="flex w-full items-center gap-3 px-4 py-3 text-left text-sm hover:bg-muted/30 transition-colors"
                >
                  <ChevronDown className={cn("h-4 w-4 text-muted-foreground transition-transform", !open && "-rotate-90")} />
                  <span className="font-medium">{s.date ? prettyDate(s.date) : "Unknown date"}</span>
                  <span className="text-muted-foreground">·</span>
                  <span>{s.agg.games} games</span>
                  <span className="text-muted-foreground">·</span>
                  <span>
                    <span className="text-success">{s.agg.wins}W</span>
                    <span className="text-muted-foreground">–</span>
                    <span className="text-danger">{s.agg.losses}L</span>
                  </span>
                  <span className="ml-auto font-mono tabular-nums">
                    {ratio(s.agg.fkdr)} <span className="text-xs text-muted-foreground">FKDR</span>
                  </span>
                </button>
                {open && (
                  <div className="border-t border-border">
                    <GamesTable
                      games={[...chronological(s.games)].reverse()}
                      highlightIds={newGameIds}
                    />
                  </div>
                )}
              </Card>
            );
          })}
          {!days.length && (
            <Card className="p-8 text-center text-sm text-muted-foreground">
              No games match the filters.
            </Card>
          )}
        </div>
      )}
    </div>
  );
}
