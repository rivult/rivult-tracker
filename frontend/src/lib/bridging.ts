/** Pure speed-bridging metrics over a recorded input session
 * (bedwars_parser/inputrec.py events: fixed 8-key allowlist, millisecond
 * timestamps). Nothing here touches the network — it's derived entirely
 * from InputEvent[], same pattern as lib/stats.ts over Game[].
 */
import type { InputEvent, InputKey } from "../api/types";

/** Gaps longer than this are idle time (tabbed out mid-session, thinking at
 * spawn) and don't count toward the active window BPS is measured against. */
const IDLE_GAP_MS = 2000;
/** A shift-release only counts as a bridging "pulse->place" if the next
 * placement follows within this window — otherwise it's an unrelated shift
 * tap (sneaking to look over an edge, etc.). */
const RELEASE_TO_PLACE_WINDOW_MS = 500;
/** Consecutive placements further apart than this aren't the same bridging
 * rhythm — the player paused (fighting, looting, watching for enemies). */
const CLICK_INTERVAL_MAX_MS = 2000;

// -- Speed-bridging segment detection ---------------------------------------
// A "bridging segment" = a span where S is held and W is NOT held. That gate
// literally covers the three speed-bridging combos the player named — A+S,
// S+D, and S-only — since A/D are optional companions and W disqualifies
// (running/rotating/walking mid isn't bridging). Metrics are computed inside
// these segments only, so movement elsewhere in the recording can't pollute
// them.

// -- Speed, derived from the sneak rhythm rather than from clicks -----------
//
// In sneak-based speed bridging one sneak cycle places one block and carries
// you one block forward, so cycles-per-second IS blocks-per-second. Counting
// right-clicks instead is unreliable in both directions: a player who HOLDS
// right-click registers one event for a whole run, and one who double-clicks
// registers two events per block. Measured on real recordings, double-clicking
// produced 1.97 RMB downs per sneak cycle and made the old blocks/sec read
// 5.5-5.8 — faster than sprinting, which is impossible while sneaking.
//
// The sneak cycle is immune to all of that: it doesn't care how you click.

/** Minecraft ground speeds in blocks/sec, used ONLY as reference marks. The
 * recorder reads keys, not the world — it cannot measure your real velocity,
 * so these calibrate the scale rather than being measured. */
export const SNEAK_BPS = 1.295;
export const WALK_BPS = 4.317;
export const SPRINT_BPS = 5.612;
/** God bridging is done at walking pace — you never sneak, so you never slow
 * down. That makes it the natural ceiling to measure speed bridging against. */
export const GOD_BRIDGE_BPS = WALK_BPS;

/** A gap between sneak pulses longer than this is a pause (looking around,
 * fighting), not part of a bridging rhythm. */
const MAX_CYCLE_MS = 2000;
/** Two shift presses this close together are ONE sneak that briefly lost
 * grip, not two blocks. Real cycles run ~250-350ms, so this can't swallow a
 * genuine one — but the author's own recordings had 10% of raw "cycles" down
 * at 22ms, which would be 45 blocks/sec. Left in, they wrecked the
 * consistency score while changing the median barely at all. */
const SNEAK_MERGE_GAP_MS = 60;
/** Below this a "cycle" is a re-grip or a stutter, not a placed block —
 * 80ms is 12.5 blocks/sec, already far past what a human bridges at. */
const MIN_CYCLE_MS = 80;

/** Gate-key blips shorter than this (a brief S re-grip, or a brief accidental
 * W tap) merge across rather than splitting one run into two. */
const SEGMENT_MERGE_GAP_MS = 750;
/** Sub-3s strafes (rounding a corner, backing off a ledge) aren't a bridge
 * run — discard them so they don't skew the averages. */
const MIN_SEGMENT_MS = 3000;

export interface HoldSpan {
  startMs: number;
  endMs: number;
}

/** Pair down/up events for one key into hold spans, sorted by start time.
 * A hold still open when the recording ends closes at the last event's
 * timestamp (the game/session end is the natural release point). */
export function holds(events: InputEvent[], key: InputKey): HoldSpan[] {
  const keyEvents = events.filter((e) => e.key === key).sort((a, b) => a.t_ms - b.t_ms);
  const lastT = events.length ? Math.max(...events.map((e) => e.t_ms)) : 0;
  const spans: HoldSpan[] = [];
  let openStart: number | null = null;
  for (const e of keyEvents) {
    if (e.action === "down") {
      if (openStart == null) openStart = e.t_ms;
    } else if (openStart != null) {
      spans.push({ startMs: openStart, endMs: e.t_ms });
      openStart = null;
    }
  }
  if (openStart != null) spans.push({ startMs: openStart, endMs: lastT });
  return spans;
}

/** Total session span minus any gap between consecutive events longer than
 * IDLE_GAP_MS — the denominator for a rate like blocks-per-second. */
export function activeMs(events: InputEvent[]): number {
  if (events.length < 2) return 0;
  const sorted = [...events].sort((a, b) => a.t_ms - b.t_ms);
  const span = sorted[sorted.length - 1].t_ms - sorted[0].t_ms;
  let idle = 0;
  for (let i = 1; i < sorted.length; i++) {
    const gap = sorted[i].t_ms - sorted[i - 1].t_ms;
    if (gap > IDLE_GAP_MS) idle += gap;
  }
  return Math.max(0, span - idle);
}

/** Remove any part of `spans` that overlaps a `hole` (S-held minus W-held).
 * Both inputs are already non-overlapping per key (holds() guarantees it). */
function subtractSpans(spans: HoldSpan[], holes: HoldSpan[]): HoldSpan[] {
  const out: HoldSpan[] = [];
  for (const span of spans) {
    let pieces: HoldSpan[] = [{ startMs: span.startMs, endMs: span.endMs }];
    for (const hole of holes) {
      const next: HoldSpan[] = [];
      for (const p of pieces) {
        if (hole.endMs <= p.startMs || hole.startMs >= p.endMs) {
          next.push(p);
        } else {
          if (hole.startMs > p.startMs) next.push({ startMs: p.startMs, endMs: hole.startMs });
          if (hole.endMs < p.endMs) next.push({ startMs: hole.endMs, endMs: p.endMs });
        }
      }
      pieces = next;
    }
    out.push(...pieces);
  }
  return out.filter((s) => s.endMs > s.startMs);
}

/** Merge spans separated by a gap no larger than `gapMs`. */
function mergeSpans(spans: HoldSpan[], gapMs: number): HoldSpan[] {
  if (!spans.length) return [];
  const sorted = [...spans].sort((a, b) => a.startMs - b.startMs);
  const out: HoldSpan[] = [{ ...sorted[0] }];
  for (let i = 1; i < sorted.length; i++) {
    const last = out[out.length - 1];
    if (sorted[i].startMs - last.endMs <= gapMs) {
      last.endMs = Math.max(last.endMs, sorted[i].endMs);
    } else {
      out.push({ ...sorted[i] });
    }
  }
  return out;
}

/** The spans of actual speed bridging: S held, W not held, blips merged,
 * sub-minimum strafes discarded. */
export function bridgingSegments(events: InputEvent[]): HoldSpan[] {
  const raw = subtractSpans(holds(events, "S"), holds(events, "W"));
  const merged = mergeSpans(raw, SEGMENT_MERGE_GAP_MS);
  return merged.filter((s) => s.endMs - s.startMs >= MIN_SEGMENT_MS);
}

/** One sneak pulse and the gap to the next — the unit of speed bridging.
 * `periodMs` is null for the final pulse, which has no successor to measure
 * against, and for any gap long enough to be a pause. */
export interface SneakCycle {
  startMs: number;
  /** How long shift was held — the sneak itself. */
  pulseMs: number;
  /** Start-to-start distance to the next pulse, or null. */
  periodMs: number | null;
  /** RMB downs from this pulse up to the next. ~2 means double-clicking. */
  clicks: number;
}

/** Sneak pulses that begin inside a bridging segment, paired with the gap to
 * the next one. Each pulse is one block placed. */
export function sneakCycles(events: InputEvent[], segments: HoldSpan[]): SneakCycle[] {
  const inSeg = (t: number) => segments.some((s) => t >= s.startMs && t <= s.endMs);
  const pulses = mergeSpans(holds(events, "SHIFT"), SNEAK_MERGE_GAP_MS).filter((s) =>
    inSeg(s.startMs),
  );
  const clicks = events
    .filter((e) => e.key === "RMB" && e.action === "down")
    .map((e) => e.t_ms);
  return pulses.map((p, i) => {
    const next = pulses[i + 1];
    const gap = next ? next.startMs - p.startMs : null;
    // The click usually lands AFTER the sneak ends — real recordings place
    // ~110ms past release. Ending the final pulse's window at its own release
    // therefore made the last block of every run look missed.
    const until = next ? next.startMs : p.endMs + RELEASE_TO_PLACE_WINDOW_MS;
    const real = gap !== null && gap >= MIN_CYCLE_MS && gap <= MAX_CYCLE_MS;
    return {
      startMs: p.startMs,
      pulseMs: p.endMs - p.startMs,
      periodMs: real ? gap : null,
      clicks: clicks.filter((t) => t >= p.startMs && t < until).length,
    };
  });
}

function mean(xs: number[]): number {
  return xs.length ? xs.reduce((a, b) => a + b, 0) / xs.length : 0;
}

function median(xs: number[]): number {
  if (!xs.length) return 0;
  const s = [...xs].sort((a, b) => a - b);
  const mid = Math.floor(s.length / 2);
  return s.length % 2 ? s[mid] : (s[mid - 1] + s[mid]) / 2;
}

function stddev(xs: number[]): number {
  if (xs.length < 2) return 0;
  const m = mean(xs);
  return Math.sqrt(mean(xs.map((x) => (x - m) ** 2)));
}

export interface BridgingSpeed {
  /** Blocks/sec while the rhythm is actually going — your bridging speed.
   * From the MEDIAN cycle, so one long pause can't drag it down. */
  rhythmBps: number;
  /** Blocks/sec across the whole run including hesitation. The gap between
   * this and rhythmBps is time lost to stopping, not to being slow. */
  overallBps: number;
  /** rhythmBps as a fraction of god-bridge pace (0..1+). */
  pctOfGodBridge: number;
  /** Blocks placed = sneak pulses. NOT the click count. */
  blocks: number;
  /** Cycles that had a measurable period (excludes pauses and the last one). */
  cycles: number;
  /** Cycles where no click landed — a likely hole in the bridge. */
  emptyCycles: number;
  /** RMB downs per block: ~1 single-clicking, ~2 double-clicking. */
  clicksPerBlock: number;
  /** How even the rhythm is, 0..1 (1 = metronome). Inverted CV, so it reads
   * the right way round for a player. */
  consistency: number;
  /** Median cycle length — the number to shave to get faster. */
  medianCycleMs: number;
}

export type ClickStyle = "single" | "double" | "drag" | "held" | "unknown";

export interface ClickProfile {
  style: ClickStyle;
  clicksPerBlock: number;
  /** Typical click hold time. Very short holds are the drag-click tell. */
  medianHoldMs: number;
  /** True when the sampler can't count the rate honestly — see inputrec.py:
   * a 250 Hz poll can DETECT clicks faster than ~60 CPS but not count them. */
  rateIsFloor: boolean;
}

/** One thing the timing says is hurting you. `severity` orders the panel. */
export interface Finding {
  id: "late-place" | "long-sneak" | "broken-rhythm" | "missed-blocks" | "short-runs";
  title: string;
  detail: string;
  severity: number;
}

export interface BridgingMetrics {
  /** Detected bridging spans — exposed so the UI can shade the timeline. */
  segments: HoldSpan[];
  runCount: number;
  bridgingMs: number;
  longestRunMs: number;
  /** In-segment placements only (RMB downs while bridging). This is a CLICK
   * count, not a block count — see `speed.blocks` for blocks. */
  placements: number;
  /** Speed derived from the sneak rhythm. Null when no sneak cycles were
   * found at all, which means this recording isn't sneak-based speed bridging
   * and a speed figure would be fiction. */
  speed: BridgingSpeed | null;
  shiftPulses: { durations: number[]; avgMs: number; medianMs: number };
  /** shift-release -> next placement latency — the core bridging tell. */
  releaseToPlaceMs: { values: number[]; avgMs: number; medianMs: number };
  clickIntervals: {
    values: number[];
    avgMs: number;
    stddevMs: number;
    /** coefficient of variation (stddev/avg) — lower = steadier rhythm. */
    cv: number;
  };
  /** Shift hold time within bridging / bridgingMs, 0..1. */
  shiftDuty: number;
  /** How you click. Affects which numbers are click-derived. */
  clicks: ClickProfile;
  /** What the timing says is costing you, worst first. Empty when nothing
   * crosses a threshold. NOTE: the recorder sees keys, not the world — these
   * name the cycle that broke, never the fall itself. */
  findings: Finding[];
}

/** Clicks this close together are one double-tap on a single block. */
const DOUBLE_TAP_MS = 80;
/** Holds this short are drag/butterfly clicking, not deliberate presses. */
const DRAG_HOLD_MS = 12;
/** Above this many clicks per block, no normal clicking style fits. */
const DRAG_CLICKS_PER_BLOCK = 2.8;
/** Beyond ~60 CPS a 250 Hz poll can detect but not count — see inputrec.py. */
const COUNTABLE_CPS = 60;

export function clickProfile(
  events: InputEvent[],
  segments: HoldSpan[],
  speed: BridgingSpeed | null,
): ClickProfile {
  const inSeg = (t: number) => segments.some((s) => t >= s.startMs && t <= s.endMs);
  const spans = holds(events, "RMB").filter((s) => inSeg(s.startMs));
  const durations = spans.map((s) => s.endMs - s.startMs);
  const medianHoldMs = durations.length ? median(durations) : 0;
  const cpb = speed?.clicksPerBlock ?? 0;
  const downs = spans.map((s) => s.startMs).sort((a, b) => a - b);
  const gaps = downs.slice(1).map((t, i) => t - downs[i]);
  const cps = gaps.length ? 1000 / median(gaps) : 0;
  // Double-clicking shows up as PAIRED clicks — two close together, then a
  // gap to the next block. Two evenly-spaced clicks per block is something
  // else, so the ratio alone isn't enough. Real recordings: 48% tight.
  const pairRatio = gaps.length
    ? gaps.filter((g) => g <= DOUBLE_TAP_MS).length / gaps.length
    : 0;

  let style: ClickStyle = "unknown";
  if (!spans.length) style = "unknown";
  // one press covering most of the run: holding right-click down
  else if (spans.length <= 2 && durations.some((d) => d > 1000)) style = "held";
  else if (cpb >= DRAG_CLICKS_PER_BLOCK && medianHoldMs <= DRAG_HOLD_MS) style = "drag";
  else if (cpb >= 1.5 && pairRatio > 0.25) style = "double";
  else if (cpb > 0) style = "single";

  return {
    style,
    clicksPerBlock: cpb,
    medianHoldMs,
    rateIsFloor: style === "drag" || cps > COUNTABLE_CPS,
  };
}

// Thresholds for "what's costing you". Calibrated against real recordings
// (median cycle ~309ms, sneak ~128ms, place delay ~111ms) so a clean run
// reports nothing — a panel that always fires is a panel nobody reads.

/** Placing this long after unsneaking means you've already started moving. */
const LATE_PLACE_MS = 180;
/** Sneaking more than this share of each cycle is the speed ceiling. */
const LONG_SNEAK_RATIO = 0.55;
/** A cycle this many times the median is a break in the rhythm. */
const OUTLIER_CYCLE_FACTOR = 2;
/** Below this consistency the spacing is genuinely ragged. */
const RAGGED_CONSISTENCY = 0.75;
/** A run shorter than this share of your median run ended early. */
const SHORT_RUN_RATIO = 0.4;

export function findings(
  segments: HoldSpan[],
  cycles: SneakCycle[],
  speed: BridgingSpeed | null,
  releaseToPlaceMs: number,
): Finding[] {
  const out: Finding[] = [];
  if (!speed) return out;
  const periods = cycles.map((c) => c.periodMs).filter((p): p is number => p !== null);

  if (releaseToPlaceMs > LATE_PLACE_MS) {
    out.push({
      id: "late-place",
      title: "You're placing late",
      detail:
        `You place ${Math.round(releaseToPlaceMs)}ms after coming out of the sneak. ` +
        `By then you've already moved, so the block lands behind you and leaves a gap. ` +
        `Click while you're still sneaking.`,
      severity: releaseToPlaceMs / LATE_PLACE_MS,
    });
  }

  const sneakRatio = speed.medianCycleMs > 0
    ? median(cycles.map((c) => c.pulseMs)) / speed.medianCycleMs
    : 0;
  if (sneakRatio > LONG_SNEAK_RATIO) {
    out.push({
      id: "long-sneak",
      title: "You're sneaking too long",
      detail:
        `${Math.round(sneakRatio * 100)}% of every block is spent sneaking. Sneaking is ` +
        `slow on purpose — it's safe, but it's what's capping you at ` +
        `${speed.rhythmBps.toFixed(2)} blocks/sec. Shorten the hold, don't rush the click.`,
      severity: sneakRatio / LONG_SNEAK_RATIO,
    });
  }

  const outliers = periods.filter((p) => p > speed.medianCycleMs * OUTLIER_CYCLE_FACTOR).length;
  if (speed.consistency < RAGGED_CONSISTENCY || outliers > periods.length * 0.1) {
    out.push({
      id: "broken-rhythm",
      title: "Your rhythm breaks up",
      detail:
        `${outliers} of ${periods.length} blocks took more than twice your usual ` +
        `${Math.round(speed.medianCycleMs)}ms. Uneven spacing is what drops people — ` +
        `a steady slower rhythm beats a fast one with stalls in it.`,
      severity: 1 + outliers / Math.max(1, periods.length),
    });
  }

  if (speed.emptyCycles > 0) {
    out.push({
      id: "missed-blocks",
      title: "Sneaks with no block",
      detail:
        `${speed.emptyCycles} sneak${speed.emptyCycles === 1 ? "" : "s"} had no click at ` +
        `all — most likely holes in the bridge, or a click that didn't land on anything.`,
      severity: 1 + speed.emptyCycles / Math.max(1, speed.blocks),
    });
  }

  const runs = segments.map((s) => s.endMs - s.startMs);
  if (runs.length >= 3) {
    const medRun = median(runs);
    const short = runs.filter((r) => r < medRun * SHORT_RUN_RATIO).length;
    if (short > 0) {
      out.push({
        id: "short-runs",
        title: "Runs ending early",
        detail:
          `${short} of your ${runs.length} runs ended well before the others. ` +
          `That's where you stopped — or came off the bridge.`,
        severity: 1 + short / runs.length,
      });
    }
  }

  return out.sort((a, b) => b.severity - a.severity);
}

function computeSpeed(
  cycles: SneakCycle[],
  periods: number[],
  clickCount: number,
  bridgingMs: number,
): BridgingSpeed | null {
  // No sneak rhythm at all => this isn't sneak-based speed bridging. Report
  // nothing rather than a confident 0.00 blocks/sec.
  if (!cycles.length || !periods.length) return null;
  const med = median(periods);
  if (med <= 0) return null;
  const rhythmBps = 1000 / med;
  // Consistency uses median absolute deviation, NOT standard deviation. A
  // single 1.5s hesitation among 300ms cycles swamps an SD-based score — it
  // read 50% on a run that was visibly steady. Hesitation is already the
  // rhythm-vs-overall gap; this number is about how EVEN the rhythm is.
  // 1.4826 rescales MAD to be comparable with SD on normal data.
  const mad = median(periods.map((p) => Math.abs(p - med)));
  const cv = med > 0 ? (1.4826 * mad) / med : 0;
  return {
    rhythmBps,
    overallBps: bridgingMs > 0 ? cycles.length / (bridgingMs / 1000) : 0,
    pctOfGodBridge: rhythmBps / GOD_BRIDGE_BPS,
    blocks: cycles.length,
    cycles: periods.length,
    emptyCycles: cycles.filter((c) => c.clicks === 0).length,
    clicksPerBlock: cycles.length ? clickCount / cycles.length : 0,
    consistency: Math.max(0, Math.min(1, 1 - cv)),
    medianCycleMs: med,
  };
}

export function metrics(events: InputEvent[]): BridgingMetrics {
  const segments = bridgingSegments(events);
  const bridgingMs = segments.reduce((sum, s) => sum + (s.endMs - s.startMs), 0);
  const inSeg = (t: number) => segments.some((s) => t >= s.startMs && t <= s.endMs);

  const placementDowns = events
    .filter((e) => e.key === "RMB" && e.action === "down" && inSeg(e.t_ms))
    .sort((a, b) => a.t_ms - b.t_ms);

  const cycles = sneakCycles(events, segments);
  const periods = cycles.map((c) => c.periodMs).filter((p): p is number => p !== null);
  const speed = computeSpeed(cycles, periods, placementDowns.length, bridgingMs);

  // Shift pulses that started while bridging.
  const shiftSpans = holds(events, "SHIFT").filter((s) => inSeg(s.startMs));
  const shiftDurations = shiftSpans.map((s) => s.endMs - s.startMs);

  const releaseToPlace: number[] = [];
  for (const span of shiftSpans) {
    const next = placementDowns.find(
      (p) => p.t_ms >= span.endMs && p.t_ms - span.endMs <= RELEASE_TO_PLACE_WINDOW_MS,
    );
    if (next) releaseToPlace.push(next.t_ms - span.endMs);
  }

  // Click rhythm is measured WITHIN a run — placements in different runs have
  // a genuine pause between them and mustn't be treated as one interval.
  const clickDeltas: number[] = [];
  for (const seg of segments) {
    const inThis = placementDowns.filter((p) => p.t_ms >= seg.startMs && p.t_ms <= seg.endMs);
    for (let i = 1; i < inThis.length; i++) {
      const d = inThis[i].t_ms - inThis[i - 1].t_ms;
      if (d <= CLICK_INTERVAL_MAX_MS) clickDeltas.push(d);
    }
  }
  const clickAvg = mean(clickDeltas);
  const clickStd = stddev(clickDeltas);

  // Shift hold time that actually overlaps bridging (intersection).
  let shiftInSeg = 0;
  for (const sh of holds(events, "SHIFT")) {
    for (const seg of segments) {
      const lo = Math.max(sh.startMs, seg.startMs);
      const hi = Math.min(sh.endMs, seg.endMs);
      if (hi > lo) shiftInSeg += hi - lo;
    }
  }

  return {
    segments,
    runCount: segments.length,
    bridgingMs,
    longestRunMs: segments.reduce((m, s) => Math.max(m, s.endMs - s.startMs), 0),
    placements: placementDowns.length,
    speed,
    shiftPulses: {
      durations: shiftDurations,
      avgMs: mean(shiftDurations),
      medianMs: median(shiftDurations),
    },
    releaseToPlaceMs: {
      values: releaseToPlace,
      avgMs: mean(releaseToPlace),
      medianMs: median(releaseToPlace),
    },
    clickIntervals: {
      values: clickDeltas,
      avgMs: clickAvg,
      stddevMs: clickStd,
      cv: clickAvg > 0 ? clickStd / clickAvg : 0,
    },
    shiftDuty: bridgingMs > 0 ? shiftInSeg / bridgingMs : 0,
    clicks: clickProfile(events, segments, speed),
    findings: findings(segments, cycles, speed, median(releaseToPlace)),
  };
}
