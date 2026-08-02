/** Expanded game row: derived metrics, roster split, colour-coded raw log.
 * Fetches /api/game/<id> lazily when the row is opened.
 */
import { useEffect, useState } from "react";
import { api } from "../api/client";
import type { GameDetail } from "../api/types";
import { ITEM_LABELS } from "../lib/breakdowns";
import { cn } from "../lib/cn";
import { mmss } from "../lib/format";

const TS_PREFIX = /^\[[0-9:]+\] [^:]*: \[CHAT\] /;
// eslint-disable-next-line no-control-regex
const COLOR_CODES = /§./g;

function lineClass(kind: string, raw: string): string {
  if (kind === "kill" && raw.includes("FINAL KILL!")) return "text-danger";
  if (kind === "kill") return "text-foreground/80";
  if (kind === "bed") return "text-warn";
  if (kind === "win") return "text-success";
  if (kind === "unparsed") return "text-sky-400";
  return "text-muted-foreground/50";
}

export function GameDetailPanel({ gameId }: { gameId: number }) {
  const [detail, setDetail] = useState<GameDetail | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    api
      .gameDetail(gameId)
      .then((d) => live && setDetail(d))
      .catch((e) => live && setError(String(e)));
    return () => {
      live = false;
    };
  }, [gameId]);

  if (error) return <div className="p-4 text-sm text-danger">Failed to load game: {error}</div>;
  if (!detail) return <div className="p-4 text-sm text-muted-foreground">Loading game…</div>;

  const you = detail.roster.filter((r) => r.is_you);
  const mates = detail.roster.filter((r) => r.is_teammate && !r.is_you);
  const opponents = detail.roster.filter((r) => !r.is_you && !r.is_teammate);

  return (
    <div className="border-t border-border bg-background/60 p-4 space-y-3">
      <div className="flex flex-wrap gap-x-5 gap-y-1 text-sm">
        <Metric label="length" value={mmss(detail.duration_s)} />
        {detail.bed_to_death_s != null && (
          <Metric label="bed → final death" value={mmss(detail.bed_to_death_s)} />
        )}
        <Metric
          label="finals"
          value={`${detail.your_final_kills ?? 0} FK / ${detail.your_final_deaths ?? 0} FD`}
        />
        <Metric
          label="kills"
          value={`${detail.your_kills ?? 0} K / ${detail.your_deaths ?? 0} D`}
        />
        {(detail.prot_level ?? 0) > 0 && (
          <Metric label="team armor" value={`prot ${detail.prot_level}`} />
        )}
        {Object.keys(detail.items ?? {}).length > 0 && (
          <Metric
            label="items"
            value={Object.entries(detail.items)
              .map(([k, n]) => `${n}× ${ITEM_LABELS[k] ?? k}`)
              .join(", ")}
          />
        )}
      </div>

      <div className="text-xs text-muted-foreground">
        <span className="text-success font-medium">{you.map((r) => r.ign).join(", ") || "you"}</span>
        {" · team "}
        <span className="text-sky-400">{mates.map((r) => r.ign).join(", ") || "—"}</span>
        {" · "}
        <span className="font-medium">{opponents.length}</span> opponents:{" "}
        {opponents.map((r) => r.ign).join(", ")}
      </div>

      <div className="max-h-60 overflow-auto rounded-md border border-border bg-background p-2.5 font-mono text-xs leading-5 whitespace-pre-wrap">
        {detail.lines.map((l) => (
          <div key={l.line_no} className={cn(lineClass(l.kind, l.raw))}>
            {l.raw.replace(TS_PREFIX, "").replace(COLOR_CODES, "")}
          </div>
        ))}
      </div>
    </div>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <span className="text-muted-foreground">
      {label} <span className="text-foreground font-medium">{value}</span>
    </span>
  );
}
