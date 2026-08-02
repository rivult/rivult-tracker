/** Bridging — speed-bridging analyzer over recorded WASD/Shift/Space/mouse
 * input (bedwars_parser/inputrec.py). Windows-only, off unless the player
 * hits Start; the tag filter doesn't apply here (not in App.tsx's
 * FILTERED_PAGES), records aren't scoped by tags. All metrics are computed
 * client-side in lib/bridging.ts, same pattern as the stats pages.
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { ArrowLeft, Play, Square } from "lucide-react";
import { Bar, BarChart, ResponsiveContainer, Tooltip, XAxis } from "recharts";
import { api } from "../api/client";
import type {
  BridgingSessionReason,
  BridgingStatus,
  InputEvent,
  InputKey,
  InputSessionSummary,
} from "../api/types";
import { Card, CardLabel, EmptyState } from "../components/shared";
import { cn } from "../lib/cn";
import { mmss } from "../lib/format";
import { GOD_BRIDGE_BPS, holds, metrics } from "../lib/bridging";
import { useNav } from "../state/NavContext";

const POLL_MS = 1000;

const REASON_LABEL: Record<BridgingSessionReason, string> = {
  user_stop: "Stopped",
  focus_lost: "Focus lost",
  time_cap: "10 min cap",
};

function fmtStarted(iso: string): string {
  return iso.slice(0, 16).replace("T", " ");
}

export function BridgingPage() {
  const [status, setStatus] = useState<BridgingStatus | null>(null);
  const [sessions, setSessions] = useState<InputSessionSummary[] | null>(null);
  // in nav state (not local) so the sidebar entry and back button can leave a
  // session detail — same reason as Breakdowns
  const { current, openDetail, back } = useNav();
  const selectedId = current.detail != null ? Number(current.detail) : null;
  const [startError, setStartError] = useState<string | null>(null);

  const loadStatus = useCallback(() => {
    api.bridgingStatus().then(setStatus).catch(() => undefined);
  }, []);

  const loadSessions = useCallback(() => {
    api
      .bridgingSessions()
      .then((r) => setSessions(r.sessions))
      .catch(() => setSessions([]));
  }, []);

  useEffect(() => {
    loadStatus();
    loadSessions();
  }, [loadStatus, loadSessions]);

  // Poll status every second ONLY while recording — clears the moment it stops.
  useEffect(() => {
    if (!status?.recording) return;
    const id = window.setInterval(loadStatus, POLL_MS);
    return () => window.clearInterval(id);
  }, [status?.recording, loadStatus]);

  // A session that just ended (stop button, focus-lost, or the 10-min cap)
  // needs the sessions list refreshed once — catch the recording:true -> false edge.
  const wasRecording = useRef(false);
  useEffect(() => {
    if (wasRecording.current && status && !status.recording) loadSessions();
    if (status) wasRecording.current = status.recording;
  }, [status, loadSessions]);

  const start = async () => {
    setStartError(null);
    const r = await api.bridgingStart();
    if (r.error) setStartError(r.error);
    else loadStatus();
  };

  const stop = async () => {
    await api.bridgingStop();
    loadStatus();
  };

  if (selectedId != null && Number.isFinite(selectedId)) {
    return <SessionDetail id={selectedId} onBack={back} />;
  }

  return (
    <div className="space-y-6 pb-24">
      <h1 className="text-3xl font-bold">Bridging</h1>

      <Card className="space-y-3 p-5">
        <CardLabel>Record</CardLabel>
        <div className="flex items-center gap-3">
          {status?.recording ? (
            <button
              onClick={() => void stop()}
              className="flex items-center gap-2 rounded-md bg-danger px-4 py-2 text-sm font-medium text-white hover:bg-danger/80"
            >
              <Square className="h-4 w-4" /> Stop
            </button>
          ) : (
            <button
              onClick={() => void start()}
              disabled={!status}
              className="flex items-center gap-2 rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/80 disabled:opacity-50"
            >
              <Play className="h-4 w-4" /> Start
            </button>
          )}
          {status?.recording && (
            <div className="flex items-center gap-4 text-sm text-muted-foreground">
              <span>{status.elapsed_s.toFixed(0)}s</span>
              <span>{status.events_captured} events</span>
              <span className={status.focused ? "text-success" : "text-warn"}>
                {status.focused ? "focused" : "not focused"}
              </span>
            </div>
          )}
        </div>
        {startError && <div className="text-sm text-danger">{startError}</div>}
        <p className="text-xs text-muted-foreground">
          Records only W A S D, Shift, Space and mouse buttons, only while Minecraft is focused.
          Auto-stops after 10 minutes or 30 s unfocused.
        </p>
      </Card>

      <Card className="overflow-hidden">
        <div className="border-b border-border px-4 py-3">
          <CardLabel>Sessions</CardLabel>
          {sessions && sessions.length > 0 && (
            <div className="mt-1 text-[11px] text-muted-foreground">
              Click counts here are raw (whole recording) — open a session to see clicks scoped to
              detected bridging only.
            </div>
          )}
        </div>
        {!sessions ? (
          <div className="p-5 text-sm text-muted-foreground">Loading…</div>
        ) : sessions.length === 0 ? (
          <div className="p-6">
            <EmptyState>Start a recording to see it here.</EmptyState>
          </div>
        ) : (
          <div className="divide-y divide-border/70">
            {sessions.map((s) => (
              <button
                key={s.id}
                onClick={() => openDetail(String(s.id))}
                className="grid w-full grid-cols-[1.4fr_0.8fr_0.8fr_1fr] items-center gap-x-4 px-4 py-2.5 text-left text-sm hover:bg-muted/30"
              >
                <span>{fmtStarted(s.started_at)}</span>
                <span className="font-mono tabular-nums text-muted-foreground">
                  {mmss(Math.round(s.span_ms / 1000))}
                </span>
                <span
                  className="font-mono tabular-nums text-muted-foreground"
                  title="Raw click count for the whole recording — open the session for the bridging-scoped count"
                >
                  {s.placements} clicks (raw)
                </span>
                <span
                  className={cn(
                    "w-fit rounded px-2 py-0.5 text-xs",
                    s.reason ? "bg-muted text-muted-foreground" : "bg-success/15 text-success",
                  )}
                >
                  {s.reason ? REASON_LABEL[s.reason] : "Recording…"}
                </span>
              </button>
            ))}
          </div>
        )}
      </Card>
    </div>
  );
}

function SessionDetail({ id, onBack }: { id: number; onBack: () => void }) {
  const [events, setEvents] = useState<InputEvent[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    api
      .bridgingSession(id)
      .then((d) => live && setEvents(d.events))
      .catch((e) => live && setError(String(e)));
    return () => {
      live = false;
    };
  }, [id]);

  const back = (
    <button
      onClick={onBack}
      className="flex items-center gap-1.5 text-sm text-muted-foreground transition-colors hover:text-foreground"
    >
      <ArrowLeft className="h-4 w-4" /> All sessions
    </button>
  );

  if (error) {
    return (
      <div className="space-y-4 pb-24">
        {back}
        <div className="text-sm text-danger">Failed to load session: {error}</div>
      </div>
    );
  }
  if (!events) {
    return (
      <div className="space-y-4 pb-24">
        {back}
        <div className="text-sm text-muted-foreground">Loading…</div>
      </div>
    );
  }

  const m = metrics(events);
  if (m.segments.length === 0) {
    return (
      <div className="space-y-4 pb-24">
        {back}
        <EmptyState>
          No speed bridging detected — hold S (with A or D), without W. Movement without the S
          strafe isn&apos;t counted.
        </EmptyState>
      </div>
    );
  }
  if (m.placements < 2) {
    return (
      <div className="space-y-4 pb-24">
        {back}
        <EmptyState>Bridge a little longer — not enough clicks to analyse.</EmptyState>
      </div>
    );
  }

  const spanMs = events.length ? Math.max(...events.map((e) => e.t_ms)) : 0;

  return (
    <div className="space-y-6 pb-24">
      {back}
      <h1 className="text-3xl font-bold">Session detail</h1>
      {m.speed === null && (
        <Card className="p-4">
          <div className="text-sm text-warn">No sneak rhythm found in this run.</div>
          <p className="mt-1 text-xs text-muted-foreground">
            Speed is measured from your sneak cycle — one sneak places one block, so
            cycles per second is blocks per second. You were strafing but barely
            sneaking here, so there&apos;s no rhythm to measure and a speed number
            would be made up. The timing stats below still apply.
          </p>
        </Card>
      )}
      <ClickStyleNote m={m} />
      <MetricTiles m={m} />
      <CostingYouCard findings={m.findings} />
      <TimelineCard events={events} spanMs={spanMs} segments={m.segments} />
      <ClickHistogramCard values={m.clickIntervals.values} />
    </div>
  );
}

const STYLE_COPY: Record<string, string> = {
  single: "You single-click — one click per block.",
  double: "You double-click — two clicks per block.",
  drag: "You drag-click — bursts of very short clicks.",
  held: "You hold right-click rather than tapping it.",
  unknown: "Not enough clicks to tell how you click.",
};

function ClickStyleNote({ m }: { m: ReturnType<typeof metrics> }) {
  const c = m.clicks;
  if (c.style === "unknown") return null;
  return (
    <Card className="p-4">
      <div className="text-sm">
        {STYLE_COPY[c.style]}{" "}
        <span className="text-muted-foreground">
          {c.clicksPerBlock.toFixed(1)} clicks per block, {Math.round(c.medianHoldMs)}ms each.
        </span>
      </div>
      <p className="mt-1 text-xs text-muted-foreground">
        Speed and block count come from your sneak rhythm, not your clicks, so this
        doesn&apos;t affect them.
        {c.rateIsFloor &&
          " Your click rate is too fast to count exactly — treat the click numbers as a minimum."}
      </p>
    </Card>
  );
}

function CostingYouCard({ findings }: { findings: ReturnType<typeof metrics>["findings"] }) {
  return (
    <Card className="p-5">
      <CardLabel>What&apos;s costing you</CardLabel>
      {findings.length === 0 ? (
        <p className="mt-2 text-sm text-muted-foreground">
          Nothing stands out in this run — your timing is even and your blocks landed.
        </p>
      ) : (
        <ul className="mt-3 space-y-3">
          {findings.map((f) => (
            <li key={f.id} className="border-l-2 border-warn/60 pl-3">
              <div className="text-sm font-semibold">{f.title}</div>
              <div className="mt-0.5 text-xs leading-relaxed text-muted-foreground">{f.detail}</div>
            </li>
          ))}
        </ul>
      )}
      <p className="mt-4 text-[11px] leading-snug text-muted-foreground">
        Worked out from your key timing. The tracker reads your inputs, not the game —
        it can&apos;t see the bridge or a fall, so this points at the block where the
        timing went wrong, not at the moment you came off.
      </p>
    </Card>
  );
}

function MetricTiles({ m }: { m: ReturnType<typeof metrics> }) {
  const s = m.speed;
  const tiles: { label: string; value: string; hint: string; big?: boolean }[] = [];

  if (s) {
    tiles.push(
      {
        label: "Bridging speed",
        value: `${s.rhythmBps.toFixed(2)}`,
        hint: `blocks/sec — ${Math.round(s.pctOfGodBridge * 100)}% of god bridge pace (${GOD_BRIDGE_BPS.toFixed(1)})`,
        big: true,
      },
      {
        label: "Including pauses",
        value: `${s.overallBps.toFixed(2)}`,
        hint:
          s.overallBps < s.rhythmBps * 0.9
            ? "slower than your rhythm — you're stopping mid-run"
            : "close to your rhythm — few pauses",
      },
      {
        label: "Blocks placed",
        value: String(s.blocks),
        hint: `one per sneak, not per click (you click ${s.clicksPerBlock.toFixed(1)}× per block)`,
      },
      {
        label: "Consistency",
        value: `${Math.round(s.consistency * 100)}%`,
        hint: "how even your rhythm is — uneven spacing is what drops you",
      },
      {
        label: "Time per block",
        value: `${Math.round(s.medianCycleMs)}ms`,
        hint: "shave this to go faster",
      },
    );
    if (s.emptyCycles > 0) {
      tiles.push({
        label: "Missed blocks",
        value: String(s.emptyCycles),
        hint: "sneaks with no click — likely holes in the bridge",
      });
    }
  }

  tiles.push(
    { label: "Bridge runs", value: String(m.runCount), hint: "separate stretches of bridging" },
    { label: "Bridging time", value: mmss(Math.round(m.bridgingMs / 1000)), hint: "total time spent bridging" },
    { label: "Longest run", value: mmss(Math.round(m.longestRunMs / 1000)), hint: "your longest unbroken stretch" },
    { label: "Sneak length", value: `${Math.round(m.shiftPulses.avgMs)}ms`, hint: "how long you hold shift each block" },
    { label: "Place delay", value: `${Math.round(m.releaseToPlaceMs.avgMs)}ms`, hint: "gap between unsneaking and placing" },
    { label: "Time sneaking", value: `${(m.shiftDuty * 100).toFixed(0)}%`, hint: "share of bridging spent held down" },
  );

  return (
    <div className="grid grid-cols-2 gap-4 md:grid-cols-3 xl:grid-cols-4">
      {tiles.map((t) => (
        <Card key={t.label} className="p-4">
          <div className="text-xs text-muted-foreground">{t.label}</div>
          <div className={cn("mt-1 font-bold tabular-nums", t.big ? "text-3xl" : "text-2xl")}>
            {t.value}
          </div>
          <div className="mt-1 text-[11px] leading-snug text-muted-foreground">{t.hint}</div>
        </Card>
      ))}
    </div>
  );
}

const TIMELINE_KEYS: InputKey[] = ["W", "A", "S", "D", "SHIFT", "SPACE", "LMB", "RMB"];
const PX_PER_SEC = 30;
const ROW_H = 22;
const LABEL_W = 44;

function timelineColor(key: InputKey): string {
  if (key === "RMB") return "#22c55e";
  if (key === "SHIFT") return "#eab308";
  if (key === "LMB") return "#ef4444";
  return "#58a6ff";
}

function TimelineCard({
  events,
  spanMs,
  segments,
}: {
  events: InputEvent[];
  spanMs: number;
  segments: { startMs: number; endMs: number }[];
}) {
  const width = LABEL_W + Math.max(260, (spanMs / 1000) * PX_PER_SEC);
  const height = TIMELINE_KEYS.length * ROW_H;
  return (
    <Card className="p-5">
      <CardLabel>Input timeline</CardLabel>
      <div className="mt-4 overflow-x-auto">
        <svg width={width} height={height} className="block">
          {/* shaded bands = detected bridging segments (behind the key rows) */}
          {segments.map((s, i) => (
            <rect
              key={`seg-${i}`}
              x={LABEL_W + (s.startMs / 1000) * PX_PER_SEC}
              y={0}
              width={Math.max(1, ((s.endMs - s.startMs) / 1000) * PX_PER_SEC)}
              height={height}
              fill="#22c55e"
              opacity={0.12}
            />
          ))}
          {TIMELINE_KEYS.map((key, i) => (
            <g key={key}>
              <text
                x={0}
                y={i * ROW_H + ROW_H / 2 + 4}
                fill="#a1a1aa"
                fontSize={10}
                fontFamily="ui-monospace, monospace"
              >
                {key}
              </text>
              {holds(events, key).map((s, j) => (
                <rect
                  key={j}
                  x={LABEL_W + (s.startMs / 1000) * PX_PER_SEC}
                  y={i * ROW_H + 3}
                  width={Math.max(1, ((s.endMs - s.startMs) / 1000) * PX_PER_SEC)}
                  height={ROW_H - 6}
                  rx={2}
                  fill={timelineColor(key)}
                />
              ))}
            </g>
          ))}
        </svg>
      </div>
      <div className="mt-2 text-[11px] text-muted-foreground">
        Green bands = detected speed bridging (S held, no W). All metrics above are measured
        inside these bands only. If they don&apos;t match what you did, the thresholds need a nudge.
      </div>
    </Card>
  );
}

function ClickHistogramCard({ values }: { values: number[] }) {
  const buckets = new Map<number, number>();
  for (const v of values) {
    const bucket = Math.floor(v / 50) * 50;
    buckets.set(bucket, (buckets.get(bucket) ?? 0) + 1);
  }
  const data = [...buckets.entries()]
    .sort((a, b) => a[0] - b[0])
    .map(([bucket, count]) => ({ bucket, count }));

  return (
    <Card className="p-5">
      <CardLabel>Click interval distribution</CardLabel>
      <div className="mt-4 h-48 w-full min-w-0">
        {data.length ? (
          <ResponsiveContainer width="100%" height="100%" minWidth={1} minHeight={1}>
            <BarChart data={data}>
              <XAxis
                dataKey="bucket"
                tickFormatter={(v) => `${v}ms`}
                tick={{ fill: "#a1a1aa", fontSize: 11 }}
                axisLine={false}
                tickLine={false}
              />
              <Tooltip
                cursor={{ fill: "#27272a" }}
                contentStyle={{
                  backgroundColor: "#18181b",
                  border: "1px solid #27272a",
                  borderRadius: "6px",
                  fontSize: 12,
                }}
                formatter={(v) => [`${v} clicks`, ""]}
                labelFormatter={(v) => `${v}–${Number(v) + 50}ms`}
              />
              <Bar dataKey="count" fill="#58a6ff" radius={[3, 3, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        ) : (
          <div className="flex h-full items-center justify-center text-sm text-muted-foreground">
            Not enough clicks yet.
          </div>
        )}
      </div>
    </Card>
  );
}
