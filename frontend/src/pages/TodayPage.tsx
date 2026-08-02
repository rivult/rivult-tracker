/** Today — payoff up top (FKDR hero, stat grid), double-check at the bottom
 * (THIS SESSION review/correction surface). Scoped by the global header
 * filter; everything here is today's games.
 */
import { useState } from "react";
import { Share2 } from "lucide-react";
import { Bar, BarChart, ResponsiveContainer, Tooltip, XAxis } from "recharts";
import type { Game } from "../api/types";
import { cn } from "../lib/cn";
import { AutoCommandNotice } from "../components/AutoCommandNotice";
import { GamesTable } from "../components/GamesTable";
import { ShareCardModal } from "../components/ShareCardModal";
import { TagBadge } from "../components/TagBadge";
import { TrendPeekCard } from "../components/TrendPeekCard";
import { Card, CardLabel, DeltaArrow, EmptyState, StatColumn } from "../components/shared";
import { prettyDate, prettyDateShort, ratio, todayISO } from "../lib/format";
import { aggregate, chronological, dailyRows, inRange, lastPlayedDays, todayGames } from "../lib/stats";
import { useData } from "../state/DataContext";

export function TodayPage() {
  const { data, loading, newGameIds, premium } = useData();
  const [sharing, setSharing] = useState(false);
  if (loading && !data) return <div className="text-sm text-muted-foreground">Loading…</div>;

  const games = data?.games ?? [];
  const today = todayGames(games);
  const agg = aggregate(today);
  const daily = dailyRows(games);
  const todayRow = daily.find((d) => d.date === todayISO());
  const prevRow = todayRow ? daily[daily.indexOf(todayRow) - 1] : undefined;
  const delta = todayRow && prevRow ? todayRow.fkdr - prevRow.fkdr : null;
  const week = lastPlayedDays(games, 7);

  return (
    <>
    <div className="space-y-10 pb-24">
      <AutoCommandNotice />

      {/* 1. Date caption — date only, no clock, not boxed */}
      <div className="text-sm text-muted-foreground">Today is {prettyDate(todayISO())}</div>

      {/* 2. FKDR hero — deliberately oversized; FKDR is the identity number */}
      <div className="flex flex-col gap-2">
        <CardLabel>Today's FKDR</CardLabel>
        <div className="flex items-baseline gap-4">
          <div
            className={cn(
              "text-8xl font-black tracking-tighter tabular-nums",
              !today.length && "text-muted-foreground/30",
            )}
          >
            {today.length ? ratio(agg.fkdr) : "0.00"}
          </div>
          {delta != null && <DeltaArrow delta={delta} />}
        </div>
        {!today.length && (
          <div className="text-sm text-muted-foreground">
            No games yet today — play with the tracker running and they appear here.
          </div>
        )}
      </div>

      {/* 3. Stat grid — columns are numerator / denominator / ratio pairs */}
      <div className="grid grid-cols-2 gap-8 md:grid-cols-4">
        <StatColumn title="WLR" ratioValue={agg.wlr} goodLabel="Wins" goodValue={agg.wins} badLabel="Losses" badValue={agg.losses} />
        <StatColumn title="FKDR" ratioValue={agg.fkdr} goodLabel="Final Kills" goodValue={agg.finalKills} badLabel="Final Deaths" badValue={agg.finalDeaths} />
        <StatColumn title="BBLR" ratioValue={agg.bblr} goodLabel="Beds Broken" goodValue={agg.bedsBroken} badLabel="Beds Lost" badValue={agg.bedsLost} />
        <StatColumn title="KDR" ratioValue={agg.kdr} goodLabel="Kills" goodValue={agg.kills} badLabel="Deaths" badValue={agg.deaths} deEmphasized />
      </div>

      {/* 4. Mid pair */}
      <div className="grid grid-cols-1 gap-6 md:grid-cols-2">
        <Card className="p-5">
          <CardLabel>7-day FKDR</CardLabel>
          <div className="mt-4 h-48 w-full min-w-0">
            {week.length ? (
              <ResponsiveContainer width="100%" height="100%" minWidth={1} minHeight={1}>
                <BarChart data={week}>
                  <XAxis
                    dataKey="date"
                    tickFormatter={prettyDateShort}
                    axisLine={false}
                    tickLine={false}
                    tick={{ fill: "#a1a1aa", fontSize: 11 }}
                    dy={8}
                  />
                  <Tooltip
                    cursor={{ fill: "#27272a" }}
                    contentStyle={{
                      backgroundColor: "#18181b",
                      border: "1px solid #27272a",
                      borderRadius: "6px",
                      fontSize: 12,
                    }}
                    labelFormatter={(d) => prettyDate(String(d))}
                    formatter={(value, _name, item) => [
                      `${ratio(Number(value))} FKDR · ${item.payload.games} games · ${item.payload.wins}W`,
                      "",
                    ]}
                  />
                  {/* solid white — the heights carry the signal */}
                  <Bar dataKey="fkdr" fill="#fafafa" radius={[4, 4, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            ) : (
              <div className="flex h-full items-center justify-center text-sm text-muted-foreground">
                Play a few days and the slope shows up here.
              </div>
            )}
          </div>
          <div className="mt-1 text-[11px] text-muted-foreground">
            One bar per played day — skipped days aren't shown as zero.
          </div>
        </Card>

        <TaggedGamesCard todayGames={today} allGames={games} />
      </div>

      {/* Free-tier peek at Trends (premium unlocks the full page). */}
      {!premium && <TrendPeekCard />}

      {/* 5. THIS SESSION — the tagging review/correction surface */}
      <Card className="overflow-hidden">
        <div className="flex items-center justify-between border-b border-border px-4 py-3">
          <CardLabel>This session</CardLabel>
          <div className="flex items-center gap-3">
            <span className="text-xs text-muted-foreground">
              Ctrl+click to multi-select · right-click to tag
            </span>
            {today.length > 0 && (
              <button
                onClick={() => setSharing(true)}
                className="flex items-center gap-1.5 rounded-md border border-border px-2 py-1 text-xs text-muted-foreground hover:bg-muted hover:text-foreground"
              >
                <Share2 className="h-3.5 w-3.5" /> Share card
              </button>
            )}
          </div>
        </div>
        {today.length ? (
          <GamesTable
            compact
            games={[...chronological(today)].reverse()}
            highlightIds={newGameIds}
          />
        ) : (
          <div className="p-6">
            <EmptyState>Today's games land here as the log picks them up.</EmptyState>
          </div>
        )}
      </Card>
    </div>
    {sharing && <ShareCardModal scope="session" onClose={() => setSharing(false)} />}
    </>
  );
}

/** Per-tag stats — not a duplicate of the header toggle (that's binary
 * all/tagged/untagged; this breaks it out per individual tag). */
function TaggedGamesCard({ todayGames: today, allGames }: { todayGames: Game[]; allGames: Game[] }) {
  const { data } = useData();
  let scope = today;
  let caption: string | null = null;
  if (!scope.some((g) => g.tags.length)) {
    scope = inRange(allGames, "30d");
    caption = "last 30 days — nothing tagged today";
  }

  const byTag = new Map<string, Game[]>();
  for (const g of scope) {
    for (const name of g.tags) {
      const list = byTag.get(name) ?? [];
      list.push(g);
      byTag.set(name, list);
    }
  }
  const rows = [...byTag.entries()]
    .map(([name, gs]) => ({ name, agg: aggregate(gs) }))
    .sort((a, b) => b.agg.games - a.agg.games);

  return (
    <Card className="flex flex-col p-5">
      <div className="flex items-baseline justify-between">
        <CardLabel>Tagged games</CardLabel>
        {caption && <span className="text-[11px] text-muted-foreground">{caption}</span>}
      </div>
      <div className="mt-3 flex-1 space-y-1 overflow-y-auto">
        {rows.length ? (
          rows.map((r) => (
            <div
              key={r.name}
              className="flex items-center justify-between border-b border-border/50 py-2 last:border-0"
            >
              <div className="flex items-center gap-2">
                <TagBadge name={r.name} color={data?.tags.find((t) => t.name === r.name)?.color} />
                <span className="text-xs text-muted-foreground">
                  {r.agg.games} game{r.agg.games === 1 ? "" : "s"}
                </span>
              </div>
              <div className="font-mono text-sm tabular-nums">
                <span className="text-muted-foreground">{r.agg.wins}W–{r.agg.losses}L · </span>
                {ratio(r.agg.fkdr)} <span className="text-muted-foreground text-xs">FKDR</span>
              </div>
            </div>
          ))
        ) : (
          <div className="pt-4 text-sm text-muted-foreground">
            Nothing tagged yet — right-click any game row to tag it, then compare
            performance across tags here.
          </div>
        )}
      </div>
    </Card>
  );
}
