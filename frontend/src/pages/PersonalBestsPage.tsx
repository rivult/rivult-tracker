/** Personal Bests — scale-forever records, celebrated. Records are ABSOLUTE:
 * this page fetches its own unfiltered dashboard instead of the globally
 * filtered one (the header filter greys out here).
 */
import { useEffect, useState } from "react";
import { Calendar, Trophy } from "lucide-react";
import { api } from "../api/client";
import { EMPTY_TAG_FILTER, type Game } from "../api/types";
import { stripDreamModes } from "../state/DataContext";
import { Card, EmptyState } from "../components/shared";
import { cn } from "../lib/cn";
import { prettyDate } from "../lib/format";
import { personalBests, type BestRecord } from "../lib/bests";

export function PersonalBestsPage() {
  const [games, setGames] = useState<Game[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    api
      .dashboard(EMPTY_TAG_FILTER, [])
      .then((d) => live && setGames(stripDreamModes(d).games))
      .catch((e) => live && setError(String(e)));
    return () => {
      live = false;
    };
  }, []);

  if (error) return <div className="text-sm text-danger">Failed to load records: {error}</div>;
  if (!games) return <div className="text-sm text-muted-foreground">Loading…</div>;
  if (!games.length)
    return <EmptyState>No games yet — records start with your first tracked win.</EmptyState>;

  const { hero, records } = personalBests(games);
  const streaks = records.filter((r) => !r.key.startsWith("life-"));
  const milestones = records.filter((r) => r.key.startsWith("life-"));

  return (
    <div className="space-y-10 pb-24">
      <div>
        <h1 className="mb-1 text-3xl font-bold">Personal Bests</h1>
        <p className="text-muted-foreground">All-time records — scale-forever only.</p>
      </div>

      {hero && (
        <Card className="relative overflow-hidden p-8">
          <div className="absolute right-0 top-0 p-8 opacity-10">
            <Trophy className="h-32 w-32" />
          </div>
          <div className="mb-2 font-medium uppercase tracking-widest text-muted-foreground">
            {hero.title}
          </div>
          <div className="text-7xl font-black tracking-tighter text-success tabular-nums">
            {hero.value}
          </div>
          <div className="mt-4 flex items-center gap-2 text-sm text-muted-foreground">
            <Calendar className="h-4 w-4" />
            {hero.date ? `Set ${prettyDate(hero.date)}` : "All-time"}
            {hero.detail ? ` · ${hero.detail}` : ""}
          </div>
        </Card>
      )}

      <div className="grid grid-cols-1 gap-6 md:grid-cols-3">
        {streaks.map((r) => (
          <PbCard key={r.key} record={r} accent />
        ))}
      </div>

      <div>
        <div className="mb-3 text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
          Lifetime milestones
        </div>
        <div className="grid grid-cols-2 gap-6 md:grid-cols-4">
          {milestones.map((r) => (
            <PbCard key={r.key} record={r} />
          ))}
        </div>
      </div>
    </div>
  );
}

function PbCard({ record, accent = false }: { record: BestRecord; accent?: boolean }) {
  return (
    <Card className="flex flex-col justify-between p-6">
      <div className="mb-4 flex items-start justify-between gap-2">
        <div className="text-sm font-medium text-muted-foreground">{record.title}</div>
        {accent && <Trophy className="h-4 w-4 shrink-0 text-muted-foreground/60" />}
      </div>
      <div>
        {/* Milestones can be names ("Highland Peaks") or dates, not only
            counts. At 4xl those overflow a quarter-width card, so the size
            steps down with length and word-breaks as a last resort. */}
        <div
          className={cn(
            "mb-1.5 font-bold tabular-nums break-words",
            record.value.length > 12
              ? "text-xl"
              : record.value.length > 8
                ? "text-2xl"
                : "text-4xl",
          )}
        >
          {record.value}
        </div>
        <div className="text-xs text-muted-foreground">
          {record.date ? prettyDate(record.date) : "All-time"}
          {record.detail ? ` · ${record.detail}` : ""}
        </div>
      </div>
    </Card>
  );
}
