/** Trends — one question: am I getting better?
 *
 * Rebuilt 2026-08-01. The previous page carried three charts, five panels and
 * ~15 numbers; three of them answered this same question in different units
 * and two (week averages, the daily table) duplicated Breakdowns and Games.
 * The window slider asked the player to tune a smoothing constant, which is a
 * developer's decision wearing a user's hat — it now lives in Settings.
 *
 * What is left: a verdict sentence, one chart with a fitted trend line, and a
 * mode filter. Mode is the only surviving control because it is the only one
 * that changes the ANSWER rather than the view — Solos and Doubles are
 * different skills. Date filtering belongs to Games and Breakdowns.
 */
import { useEffect, useMemo, useState } from "react";
import {
  CartesianGrid,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { Card, EmptyState } from "../components/shared";
import { cn } from "../lib/cn";
import { prettyDateShort, ratio } from "../lib/format";
import {
  PACE_GAMES,
  TREND_SPAN,
  TREND_WINDOW,
  careerFkdr,
  fitTrend,
  recentSeries,
  verdict,
  type Verdict,
} from "../lib/trends";
import { api } from "../api/client";
import { useData } from "../state/DataContext";

const HEADLINE: Record<Verdict["state"], { text: string; tone: string }> = {
  improving: { text: "You're improving", tone: "text-success" },
  sliding: { text: "You're sliding", tone: "text-danger" },
  steady: { text: "Holding steady", tone: "text-foreground" },
  insufficient: { text: "Not enough games yet", tone: "text-muted-foreground" },
};

/** The whole page's job, in a sentence. */
function VerdictCard({ v }: { v: Verdict }) {
  const { text, tone } = HEADLINE[v.state];

  if (v.state === "insufficient") {
    return (
      <Card className="p-5">
        <div className={cn("text-2xl font-bold", tone)}>{text}</div>
        <p className="mt-1.5 text-sm text-muted-foreground">
          A trend needs {v.window * 2} games to compare {v.window} against the{" "}
          {v.window} before them — you have {v.games}
          {v.games > 0 && (
            <>
              , at <span className="font-mono">{ratio(v.current)}</span> FKDR
            </>
          )}
          .
        </p>
      </Card>
    );
  }

  const up = (v.delta ?? 0) >= 0;
  return (
    <Card className="p-5">
      <div className={cn("text-2xl font-bold", tone)}>{text}</div>
      <div className="mt-2 flex flex-wrap items-baseline gap-x-2 gap-y-1">
        <span className="font-mono text-3xl font-semibold tabular-nums">
          {ratio(v.current)}
        </span>
        <span className="text-sm text-muted-foreground">
          FKDR over your last {v.window} games
        </span>
      </div>
      <div className="mt-1 text-sm text-muted-foreground">
        {up ? "up from" : "down from"}{" "}
        <span className="font-mono text-foreground">{ratio(v.previous ?? 0)}</span>{" "}
        over the {v.window} before
        <span className={cn("ml-2 font-medium", up ? "text-success" : "text-danger")}>
          {up ? "▲ +" : "▼ "}
          {ratio(v.delta ?? 0)}
        </span>
      </div>
    </Card>
  );
}

export function TrendsPage() {
  const { data, loading } = useData();
  const [mode, setMode] = useState<string>("");
  const [focusTag, setFocusTag] = useState<string>("");
  // Settings owns the smoothing constant now; the page just reads it.
  const [window, setWindow] = useState<number>(TREND_WINDOW);

  useEffect(() => {
    let live = true;
    api
      .settings()
      .then((cfg) => {
        if (!live) return;
        if (cfg.trend_window) setWindow(cfg.trend_window);
        setFocusTag(cfg.trend_focus_tag ?? "");
      })
      .catch(() => undefined);
    return () => {
      live = false;
    };
  }, []);

  const games = data?.games ?? [];

  // Offer a mode chip once there are enough games to draw a line at all — one
  // full window. Offering "Trios" on 17 games is a dead end dressed up as a
  // control, but requiring both halves of the comparison (2x window) hid Solos
  // at 176 real games, which is worse: the chart is still worth seeing, and
  // the verdict card says plainly when it can't compare yet.
  const modeChips = useMemo(() => {
    const counts = new Map<string, number>();
    for (const g of games) {
      if (g.mode) counts.set(g.mode, (counts.get(g.mode) ?? 0) + 1);
    }
    return (data?.modes ?? []).filter((m) => (counts.get(m) ?? 0) >= window);
  }, [games, data?.modes, window]);

  const modeGames = useMemo(
    () => (mode ? games.filter((g) => g.mode === mode) : games),
    [games, mode],
  );

  const v = useMemo(() => verdict(modeGames, window), [modeGames, window]);
  const career = useMemo(() => careerFkdr(modeGames), [modeGames]);
  const series = useMemo(
    () => recentSeries(modeGames, window, TREND_SPAN),
    [modeGames, window],
  );
  // Fitted over the recent stretch only, so its direction can't contradict the
  // verdict above it — see lib/trends.ts for why that matters.
  const fitted = useMemo(() => fitTrend(series, window, window), [series, window]);
  const focusSeries = useMemo(
    () => (focusTag ? recentSeries(modeGames, window, TREND_SPAN, focusTag) : []),
    [modeGames, window, focusTag],
  );

  // The chart draws the fitted series when there is one (it carries the same
  // points plus `fit`), so the two lines never fall out of step.
  const chartData = fitted?.data ?? series;

  // Ticks are game numbers; labelling them with the date they happened keeps
  // the axis readable without making time the axis again.
  const dateAt = useMemo(() => {
    const m = new Map<number, string>();
    for (const p of series) m.set(p.played, p.date);
    return m;
  }, [series]);

  const spanDays = useMemo(() => {
    if (series.length < 2) return null;
    const a = new Date(series[0].date).getTime();
    const b = new Date(series[series.length - 1].date).getTime();
    if (Number.isNaN(a) || Number.isNaN(b)) return null;
    const days = Math.round((b - a) / 86_400_000);
    // days across the span, scaled down to what ONE window covers
    return Math.max(1, Math.round((days * window) / series.length));
  }, [series, window]);

  if (loading && !data) return <div className="text-sm text-muted-foreground">Loading…</div>;
  if (!data?.games.length)
    return <EmptyState>No games yet — trends need history to draw.</EmptyState>;

  return (
    <div className="space-y-6 pb-24">
      <h1 className="text-3xl font-bold">Trends</h1>

      <VerdictCard v={v} />

      <Card className="p-5">
        <div className="h-72 w-full min-w-0">
          {series.length ? (
            <ResponsiveContainer width="100%" height="100%" minWidth={1} minHeight={1}>
              <LineChart data={chartData}>
                <CartesianGrid strokeDasharray="3 3" stroke="#27272a" vertical={false} />
                <XAxis
                  dataKey="played"
                  type="number"
                  domain={["dataMin", "dataMax"]}
                  tickFormatter={(g) => {
                    const d = dateAt.get(Number(g));
                    return d ? prettyDateShort(d) : "";
                  }}
                  stroke="#a1a1aa"
                  fontSize={11}
                  tickLine={false}
                  axisLine={false}
                  dy={8}
                />
                <YAxis
                  stroke="#a1a1aa"
                  fontSize={11}
                  tickLine={false}
                  axisLine={false}
                  dx={-6}
                  width={34}
                />
                <Tooltip
                  contentStyle={{
                    backgroundColor: "#18181b",
                    border: "1px solid #27272a",
                    borderRadius: "6px",
                    fontSize: 12,
                  }}
                  labelFormatter={(g) => {
                    const d = dateAt.get(Number(g));
                    return `game ${g}${d ? ` · ${prettyDateShort(d)}` : ""}`;
                  }}
                  formatter={(val, name) => {
                    const n = Number(val);
                    if (name === "fit") return [ratio(n), "trend"];
                    if (name === "focus") return [ratio(n), focusTag];
                    return [ratio(n), "FKDR"];
                  }}
                />
                {/* Career FKDR: the line to beat. */}
                <ReferenceLine
                  y={career}
                  stroke="#a1a1aa"
                  strokeDasharray="4 4"
                  strokeWidth={1.5}
                  label={{
                    value: `career ${ratio(career)}`,
                    position: "insideTopRight",
                    fill: "#a1a1aa",
                    fontSize: 11,
                  }}
                />
                <Line
                  type="monotone"
                  dataKey="fkdr"
                  stroke="#fafafa"
                  strokeWidth={2.5}
                  dot={false}
                  activeDot={{ r: 5, fill: "#fafafa" }}
                  isAnimationActive={false}
                />
                {/* The line of best fit — the straight one. Its slope IS the
                    rate of improvement quoted in the caption below. */}
                {fitted && (
                  <Line
                    type="linear"
                    dataKey="fit"
                    stroke={fitted.slopePer100 >= 0 ? "#22c55e" : "#ef4444"}
                    strokeWidth={2}
                    strokeDasharray="6 4"
                    dot={false}
                    activeDot={false}
                    connectNulls={false}
                    isAnimationActive={false}
                  />
                )}
                {focusTag && focusSeries.length > 0 && (
                  <Line
                    type="monotone"
                    data={focusSeries}
                    dataKey="fkdr"
                    name="focus"
                    stroke="#60a5fa"
                    strokeWidth={2}
                    dot={false}
                    activeDot={{ r: 4, fill: "#60a5fa" }}
                    isAnimationActive={false}
                  />
                )}
              </LineChart>
            </ResponsiveContainer>
          ) : (
            <div className="flex h-full items-center justify-center text-sm text-muted-foreground">
              No games in this mode yet.
            </div>
          )}
        </div>

        <p className="mt-3 text-xs text-muted-foreground">
          Last {Math.min(series.length, TREND_SPAN)} games · each point averages the
          previous {window}
          {spanDays !== null && <> — about {spanDays} day{spanDays === 1 ? "" : "s"} at your pace</>}
          .{" "}
          {fitted ? (
            <>
              The dashed{" "}
              <span className={fitted.slopePer100 >= 0 ? "text-success" : "text-danger"}>
                trend line
              </span>{" "}
              is the best fit through your last {fitted.coveredGames} games —
              you're {fitted.slopePer100 >= 0 ? "gaining" : "losing"}{" "}
              <span className="font-mono text-foreground">
                {ratio(Math.abs(fitted.slopePer100))}
              </span>{" "}
              FKDR per {PACE_GAMES} games at that rate.
            </>
          ) : (
            <>Not enough points yet to fit a trend line.</>
          )}
        </p>
      </Card>

      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex flex-wrap gap-1.5">
          {["", ...modeChips].map((m) => (
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

        {/* Focused sessions, folded onto the chart above rather than given a
            second one: the point is to compare the two shapes, which is hard
            across two panels and trivial on one axis. */}
        <label className="flex items-center gap-2 text-xs text-muted-foreground">
          overlay tag
          <select
            value={focusTag}
            onChange={(e) => {
              const next = e.target.value;
              setFocusTag(next);
              void api.saveSettings({ trend_focus_tag: next }).catch(() => undefined);
            }}
            aria-label="Tag marking a focused session"
            className="rounded-md border border-border bg-card px-2 py-1 text-sm text-foreground outline-none hover:bg-muted/50"
          >
            <option value="">— none —</option>
            {(data?.tags ?? []).map((t) => (
              <option key={t.name} value={t.name}>
                {t.name}
              </option>
            ))}
          </select>
        </label>
      </div>

      {focusTag && focusSeries.length === 0 && (
        <p className="text-xs text-muted-foreground">
          No games tagged <span className="text-foreground">{focusTag}</span> in the
          last {TREND_SPAN} games.
        </p>
      )}
    </div>
  );
}
