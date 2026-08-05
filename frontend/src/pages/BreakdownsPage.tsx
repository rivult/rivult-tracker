/** Breakdowns — hub-and-detail. The landing grid of section cards is the
 * extensibility mechanism (adding a breakdown = adding a card in
 * lib/breakdowns.ts). Every detail page is the same component: sorted table
 * + bar chart, min-games threshold, date-range chips (range is a FILTER
 * here — "does this pattern still hold lately" — never the axis).
 */
import { useMemo, useState } from "react";
import { ArrowLeft, ArrowUpRight } from "lucide-react";
import {
  Bar,
  BarChart,
  Cell,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { Card, CardLabel, EmptyState, RangePicker } from "../components/shared";
import { cn } from "../lib/cn";
import { ratio } from "../lib/format";
import {
  DEFAULT_MIN_GAMES,
  SECTIONS,
  groupBy,
  sectionByKey,
  type BreakdownRow,
} from "../lib/breakdowns";
import { ALL_TIME_RANGE, aggregate, inRange, type DateRange } from "../lib/stats";
import { useData } from "../state/DataContext";
import { useNav } from "../state/NavContext";

export function BreakdownsPage() {
  const { data, loading } = useData();
  // the open section lives in nav state, not here, so the sidebar entry and
  // the back button can both get you out of a detail view
  const { current, openDetail, back } = useNav();
  const selected = current.detail ?? null;
  const games = data?.games ?? [];

  if (loading && !data) return <div className="text-sm text-muted-foreground">Loading…</div>;

  if (selected) {
    const section = sectionByKey(selected);
    if (section) return <SectionDetail sectionKey={selected} onBack={back} />;
  }

  return (
    <div className="space-y-6 pb-24">
      <div>
        <h1 className="mb-2 text-3xl font-bold">Breakdowns</h1>
        <p className="text-muted-foreground">
          Hub-and-detail analysis across derived logs and manual tags.
        </p>
      </div>

      <div className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
        {SECTIONS.map((s) => {
          // BUG THIS FIXES: this counted with the raw grouper and never called
          // s.prepare, so Streak State (the only section with one) grouped
          // every game to null and advertised "0 groups" for a section that
          // works the moment you open it. It also counted rows the detail
          // table then hides, so "152 groups" promised 152 findings when ~26
          // cleared the bar.
          const prepared = s.prepare ? s.prepare(games) : games;
          const groups = groupBy(prepared, s.grouper).filter(
            (r) => r.agg.games >= DEFAULT_MIN_GAMES,
          ).length;
          return (
            <button
              key={s.key}
              onClick={() => openDetail(s.key)}
              className="group flex flex-col gap-2 rounded-lg border border-border bg-card p-5 text-left transition-colors hover:border-muted-foreground/50"
            >
              <div className="flex w-full items-center justify-between">
                <h3 className="text-lg font-semibold">{s.title}</h3>
                <ArrowUpRight className="h-4 w-4 text-muted-foreground opacity-0 transition-opacity group-hover:opacity-100" />
              </div>
              <p className="text-sm text-muted-foreground">{s.desc}</p>
              <div className="mt-3 flex items-center gap-2">
                <span className="w-fit rounded bg-muted px-2 py-1 font-mono text-xs text-muted-foreground">
                  {groups} group{groups === 1 ? "" : "s"}
                </span>
                {s.source === "tag" && (
                  <span className="w-fit rounded bg-warn/10 px-2 py-1 text-xs text-warn">
                    needs tagging
                  </span>
                )}
              </div>
            </button>
          );
        })}
      </div>
    </div>
  );
}

type DetailSort = "name" | "games" | "fkdr" | "wlr" | "beds";

const COLUMNS: { key: DetailSort; label: string }[] = [
  { key: "games", label: "Games" },
  { key: "fkdr", label: "FKDR" },
  { key: "wlr", label: "W/L" },
  { key: "beds", label: "Beds broken" },
];

function sortValue(r: BreakdownRow, key: DetailSort): number {
  switch (key) {
    case "fkdr":
      return r.agg.fkdr;
    case "wlr":
      return r.agg.wlr;
    case "beds":
      return r.agg.bedsBroken;
    default:
      return r.agg.games;
  }
}

/** Name sorts alphabetically; every other column is numeric. `numeric: true`
 * keeps digit-bearing names in human order (Hour 2 before Hour 10). */
function compareRows(a: BreakdownRow, b: BreakdownRow, key: DetailSort): number {
  if (key === "name") {
    return a.name.localeCompare(b.name, undefined, { numeric: true, sensitivity: "base" });
  }
  return sortValue(a, key) - sortValue(b, key);
}

/** Range per breakdown section, remembered while the app is open.
 *
 * Deliberately module state and NOT persisted: opening a section should show
 * ALL TIME (the honest default — a 30-day window silently hid most of your
 * history), but flipping one section to 7d and stepping back into it shouldn't
 * lose that. A relaunch resets everything to all-time. */
const sectionRanges = new Map<string, DateRange>();

function SectionDetail({ sectionKey, onBack }: { sectionKey: string; onBack: () => void }) {
  const { data } = useData();
  const section = sectionByKey(sectionKey)!;
  const [range, setRangeState] = useState<DateRange>(
    () => sectionRanges.get(sectionKey) ?? ALL_TIME_RANGE,
  );
  const setRange = (next: DateRange) => {
    sectionRanges.set(sectionKey, next);
    setRangeState(next);
  };
  const [threshold, setThreshold] = useState(DEFAULT_MIN_GAMES);
  const [sort, setSort] = useState<DetailSort>("games");
  const [desc, setDesc] = useState(true);

  const games = useMemo(() => inRange(data?.games ?? [], range), [data, range]);
  const overall = useMemo(() => aggregate(games).fkdr, [games]);
  const rows = useMemo(() => {
    // some dimensions (streak) need the whole list before grouping
    const prepared = section.prepare ? section.prepare(games) : games;
    return groupBy(prepared, section.grouper);
  }, [games, section]);
  const visible = useMemo(() => {
    const kept = rows.filter((r) => r.agg.games >= threshold);
    return kept.sort((a, b) => compareRows(a, b, sort) * (desc ? -1 : 1));
  }, [rows, threshold, sort, desc]);
  const hidden = rows.length - visible.length;
  const chartRows = visible.slice(0, 12);

  const header = (key: DetailSort, label: string, align: "left" | "right" = "right") => (
    <button
      onClick={() => {
        if (sort === key) setDesc(!desc);
        else {
          setSort(key);
          // names read best A→Z first; numbers read best biggest-first
          setDesc(key !== "name");
        }
      }}
      className={cn(
        "text-[11px] font-medium uppercase tracking-wider hover:text-foreground",
        align === "right" ? "text-right" : "text-left",
        sort === key ? "text-foreground" : "text-muted-foreground",
      )}
    >
      {label}
      {sort === key ? (desc ? " ▼" : " ▲") : ""}
    </button>
  );

  return (
    <div className="space-y-6 pb-24">
      <div>
        <button
          onClick={onBack}
          className="mb-3 flex items-center gap-1.5 text-sm text-muted-foreground transition-colors hover:text-foreground"
        >
          <ArrowLeft className="h-4 w-4" /> All breakdowns
        </button>
        <h1 className="mb-1 text-3xl font-bold">{section.title}</h1>
        <p className="text-muted-foreground">{section.desc}</p>
      </div>

      <div className="flex flex-wrap items-center gap-4">
        <RangePicker value={range} onChange={setRange} />
        <label className="flex items-center gap-2 text-sm text-muted-foreground">
          min games
          <input
            type="number"
            min={1}
            value={threshold}
            onChange={(e) => setThreshold(Math.max(1, Number(e.target.value) || 1))}
            className="w-16 rounded-md border border-border bg-card px-2 py-1 text-sm text-foreground outline-none"
          />
        </label>
      </div>

      {visible.length === 0 ? (
        <EmptyState>
          {section.key === "tags"
            ? "No tagged games in this window — right-click any game row to tag it."
            : "No groups clear the minimum-games bar in this window."}
        </EmptyState>
      ) : (
        <>
          <Card className="p-5">
            <CardLabel>FKDR by {section.title.toLowerCase()}</CardLabel>
            <div className="mt-4 w-full min-w-0" style={{ height: 36 * chartRows.length + 40 }}>
              <ResponsiveContainer width="100%" height="100%" minWidth={1} minHeight={1}>
                <BarChart data={chartRows.map((r) => ({ name: r.name, fkdr: r.agg.fkdr }))} layout="vertical">
                  <XAxis type="number" hide />
                  <YAxis
                    type="category"
                    dataKey="name"
                    width={150}
                    axisLine={false}
                    tickLine={false}
                    tick={{ fill: "#a1a1aa", fontSize: 12 }}
                  />
                  <Tooltip
                    cursor={{ fill: "#27272a" }}
                    contentStyle={{
                      backgroundColor: "#18181b",
                      border: "1px solid #27272a",
                      borderRadius: "6px",
                      fontSize: 12,
                    }}
                    formatter={(v) => [`${ratio(Number(v))} FKDR`, ""]}
                  />
                  <ReferenceLine x={overall} stroke="#a1a1aa" strokeDasharray="3 3" />
                  <Bar dataKey="fkdr" radius={[0, 4, 4, 0]} barSize={18}>
                    {chartRows.map((r) => (
                      <Cell key={r.name} fill={r.agg.fkdr >= overall ? "#22c55e" : "#ef4444"} />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </div>
            <div className="mt-1 text-[11px] text-muted-foreground">
              dashed line = overall FKDR {ratio(overall)} in this window
            </div>
            {section.key === "items" && (
              <div className="mt-1 text-[11px] text-muted-foreground">
                Rows overlap — a game that bought a potion and a pearl counts in both. Compare
                each row against the dashed overall line.
              </div>
            )}
          </Card>

          <Card className="overflow-hidden">
            <div className="grid grid-cols-[1.6fr_0.6fr_0.6fr_0.9fr_0.7fr] gap-x-4 border-b border-border bg-muted/20 px-4 py-2.5">
              {header("name", section.title, "left")}
              {COLUMNS.map((c) => (
                <span key={c.key} className="text-right">
                  {header(c.key, c.label)}
                </span>
              ))}
            </div>
            <div className="divide-y divide-border/70">
              {visible.map((r) => (
                <div
                  key={r.name}
                  className="grid grid-cols-[1.6fr_0.6fr_0.6fr_0.9fr_0.7fr] items-center gap-x-4 px-4 py-2.5 text-sm hover:bg-muted/20"
                >
                  <span className="truncate font-medium">{r.name}</span>
                  <span className="text-right font-mono tabular-nums text-muted-foreground">
                    {r.agg.games}
                  </span>
                  <span
                    className={cn(
                      "text-right font-mono font-medium tabular-nums",
                      r.agg.fkdr >= overall ? "text-success" : "text-danger",
                    )}
                  >
                    {ratio(r.agg.fkdr)}
                  </span>
                  <span className="text-right font-mono tabular-nums">
                    {r.agg.wins}–{r.agg.losses}{" "}
                    <span className="text-xs text-muted-foreground">({ratio(r.agg.wlr)})</span>
                  </span>
                  <span className="text-right font-mono tabular-nums">{r.agg.bedsBroken}</span>
                </div>
              ))}
            </div>
          </Card>

          {hidden > 0 && (
            <div className="text-xs text-muted-foreground">
              {hidden} small-sample group{hidden === 1 ? "" : "s"} hidden (fewer than {threshold}{" "}
              games).
            </div>
          )}
        </>
      )}
    </div>
  );
}
