import { describe, expect, it } from "vitest";
import type { InputEvent } from "../../api/types";
import {
  GOD_BRIDGE_BPS,
  activeMs,
  bridgingSegments,
  holds,
  metrics,
  sneakCycles,
} from "../bridging";

function ev(t_ms: number, key: InputEvent["key"], action: InputEvent["action"]): InputEvent {
  return { t_ms, key, action };
}

/**
 * `n` sneak cycles of `periodMs`, each a `pulseMs` shift hold followed by
 * `clicksPerBlock` right-clicks — the shape of real speed bridging.
 */
function cycles(
  n: number,
  periodMs = 300,
  { pulseMs = 120, clicksPerBlock = 1, from = 500 } = {},
): InputEvent[] {
  const out: InputEvent[] = [];
  for (let i = 0; i < n; i++) {
    const t = from + i * periodMs;
    out.push(ev(t, "SHIFT", "down"), ev(t + pulseMs, "SHIFT", "up"));
    for (let c = 0; c < clicksPerBlock; c++) {
      out.push(ev(t + pulseMs + 20 + c * 25, "RMB", "down"), ev(t + pulseMs + 30 + c * 25, "RMB", "up"));
    }
  }
  return out;
}

/** Wrap inner events in an S-hold (no W) so a bridging segment exists around
 * them — metrics only count events inside detected bridging spans. */
function bridge(inner: InputEvent[], durMs = 8000): InputEvent[] {
  return [ev(0, "S", "down"), ...inner, ev(durMs, "S", "up")];
}

describe("speed from sneak cycles", () => {
  it("one sneak cycle is one block, so 300ms cycles are 3.33 blocks/sec", () => {
    const m = metrics(bridge(cycles(20, 300)));
    expect(m.speed?.rhythmBps).toBeCloseTo(1000 / 300, 5);
    expect(m.speed?.blocks).toBe(20);
  });

  it("REGRESSION: double-clicking no longer doubles the reported speed", () => {
    // Measured on real recordings: 1.97 RMB downs per sneak cycle made the old
    // click-based bps read 5.5-5.8 blocks/sec — faster than sprinting, which is
    // impossible while sneaking. Speed must not move when only clicks change.
    const single = metrics(bridge(cycles(20, 300, { clicksPerBlock: 1 })));
    const double = metrics(bridge(cycles(20, 300, { clicksPerBlock: 2 })));
    expect(double.speed?.rhythmBps).toBeCloseTo(single.speed?.rhythmBps ?? 0, 5);
    expect(double.speed?.blocks).toBe(single.speed?.blocks);
    // the click count still differs — it's reported, just not used for speed
    expect(double.placements).toBe(2 * single.placements);
    expect(double.speed?.clicksPerBlock).toBeCloseTo(2, 1);
  });

  it("holding right-click through a run doesn't collapse the speed either", () => {
    // one RMB down for the whole run; the old metric read ~0.05 blocks/sec
    const held = [...cycles(20, 300, { clicksPerBlock: 0 }), ev(600, "RMB", "down"), ev(6500, "RMB", "up")];
    const m = metrics(bridge(held));
    expect(m.speed?.rhythmBps).toBeCloseTo(1000 / 300, 5);
    expect(m.speed?.blocks).toBe(20);
  });

  it("compares against god bridge pace", () => {
    const m = metrics(bridge(cycles(20, 1000 / GOD_BRIDGE_BPS)));
    expect(m.speed?.pctOfGodBridge).toBeCloseTo(1, 2);
  });

  it("a pause lowers overall speed but not rhythm speed", () => {
    // 10 quick cycles, a 1.9s stall, then 10 more: the rhythm is unchanged,
    // but you lost real time — the gap between the two numbers IS the message
    const withStall = [...cycles(10, 300), ...cycles(10, 300, { from: 500 + 10 * 300 + 1900 })];
    const m = metrics(bridge(withStall, 12000));
    expect(m.speed?.rhythmBps).toBeCloseTo(1000 / 300, 5);
    expect(m.speed?.overallBps).toBeLessThan(m.speed?.rhythmBps ?? 0);
  });

  it("flags sneaks that placed nothing as likely holes", () => {
    const withMisses = [
      ...cycles(5, 300),
      ...cycles(3, 300, { from: 2000, clicksPerBlock: 0 }),
      ...cycles(5, 300, { from: 2900 }),
    ];
    expect(metrics(bridge(withMisses)).speed?.emptyCycles).toBeGreaterThanOrEqual(3);
  });

  it("a metronome is 100% consistent and a ragged rhythm is not", () => {
    const steady = metrics(bridge(cycles(20, 300))).speed?.consistency ?? 0;
    const ragged = [
      ...cycles(1, 300, { from: 500 }),
      ...cycles(1, 300, { from: 1400 }),
      ...cycles(1, 300, { from: 1700 }),
      ...cycles(1, 300, { from: 3000 }),
      ...cycles(1, 300, { from: 3200 }),
      ...cycles(1, 300, { from: 4400 }),
    ];
    expect(steady).toBeCloseTo(1, 5);
    expect(metrics(bridge(ragged)).speed?.consistency ?? 1).toBeLessThan(steady);
  });

  it("reports no speed at all when there is no sneak rhythm", () => {
    // session 3 of the real recordings: strafing and clicking, barely any
    // shift. A speed figure here would be fiction, so there mustn't be one.
    const noSneak = bridge([ev(1000, "RMB", "down"), ev(1030, "RMB", "up"), ev(2000, "RMB", "down")]);
    expect(metrics(noSneak).speed).toBeNull();
  });

  it("a shift re-grip is one sneak, not two blocks", () => {
    // REAL DATA: 10% of raw cycles in the author's recordings were ~22ms —
    // 45 blocks/sec, physically impossible. Left in, they dragged consistency
    // from ~90% down to 37% while barely moving the median.
    const clean = metrics(bridge(cycles(12, 300)));
    const withRegrips: InputEvent[] = [];
    for (let i = 0; i < 12; i++) {
      const t = 500 + i * 300;
      withRegrips.push(
        ev(t, "SHIFT", "down"),
        ev(t + 50, "SHIFT", "up"),      // grip slips...
        ev(t + 72, "SHIFT", "down"),    // ...and comes back 22ms later
        ev(t + 120, "SHIFT", "up"),
        ev(t + 140, "RMB", "down"),
        ev(t + 160, "RMB", "up"),
      );
    }
    const m = metrics(bridge(withRegrips));
    expect(m.speed?.blocks).toBe(clean.speed?.blocks);
    expect(m.speed?.rhythmBps).toBeCloseTo(clean.speed?.rhythmBps ?? 0, 5);
    expect(m.speed?.consistency).toBeCloseTo(1, 2);
  });

  it("ignores gaps too long to be a bridging rhythm", () => {
    const paused = [...cycles(2, 300), ...cycles(2, 300, { from: 6000 })];
    const cs = sneakCycles(paused, bridgingSegments(bridge(paused, 9000)));
    expect(cs.filter((c) => c.periodMs !== null).map((c) => c.periodMs)).toEqual([300, 300]);
  });
});

describe("click style", () => {
  it("recognises single and double clicking without changing speed", () => {
    expect(metrics(bridge(cycles(20, 300, { clicksPerBlock: 1 }))).clicks.style).toBe("single");
    expect(metrics(bridge(cycles(20, 300, { clicksPerBlock: 2 }))).clicks.style).toBe("double");
  });

  it("recognises holding right-click through the run", () => {
    const held = [...cycles(20, 300, { clicksPerBlock: 0 }), ev(600, "RMB", "down"), ev(6500, "RMB", "up")];
    expect(metrics(bridge(held)).clicks.style).toBe("held");
  });

  it("flags a drag clicker's rate as a floor, not a count", () => {
    // sub-poll bursts: many very short clicks per block. The 250Hz sampler
    // can detect these but cannot count them (see inputrec.py).
    const drag: InputEvent[] = [];
    for (let i = 0; i < 20; i++) {
      const t = 500 + i * 300;
      drag.push(ev(t, "SHIFT", "down"), ev(t + 120, "SHIFT", "up"));
      for (let c = 0; c < 4; c++) {
        drag.push(ev(t + 140 + c * 8, "RMB", "down"), ev(t + 144 + c * 8, "RMB", "up"));
      }
    }
    const m = metrics(bridge(drag));
    expect(m.clicks.style).toBe("drag");
    expect(m.clicks.rateIsFloor).toBe(true);
    expect(m.speed?.blocks).toBe(20); // still one block per sneak
  });
});

describe("what's costing you", () => {
  it("says nothing about a clean run", () => {
    expect(metrics(bridge(cycles(20, 300))).findings).toEqual([]);
  });

  it("catches placing long after the sneak ends", () => {
    const late: InputEvent[] = [];
    for (let i = 0; i < 20; i++) {
      const t = 500 + i * 400;
      late.push(
        ev(t, "SHIFT", "down"),
        ev(t + 100, "SHIFT", "up"),
        ev(t + 350, "RMB", "down"),   // 250ms after unsneaking
        ev(t + 370, "RMB", "up"),
      );
    }
    const ids = metrics(bridge(late, 9000)).findings.map((f) => f.id);
    expect(ids).toContain("late-place");
  });

  it("catches sneaking through most of each block", () => {
    // 250ms sneak in a 420ms cycle = 60%, leaving a 170ms un-sneak. That gap
    // has to stay realistic: at walking pace a block takes ~230ms to cross,
    // and real recordings show ~180ms. A fixture with a 50ms gap would be
    // merged as a lost grip, correctly — you cannot cross a block that fast.
    const slow = cycles(20, 420, { pulseMs: 250 });
    expect(metrics(bridge(slow, 10000)).findings.map((f) => f.id)).toContain("long-sneak");
  });

  it("catches a rhythm with stalls in it", () => {
    const ragged: InputEvent[] = [];
    let t = 500;
    for (let i = 0; i < 20; i++) {
      ragged.push(ev(t, "SHIFT", "down"), ev(t + 120, "SHIFT", "up"), ev(t + 150, "RMB", "down"), ev(t + 170, "RMB", "up"));
      t += i % 4 === 3 ? 900 : 300;     // every fourth block stalls
    }
    expect(metrics(bridge(ragged, 12000)).findings.map((f) => f.id)).toContain("broken-rhythm");
  });

  it("ranks the worst problem first", () => {
    const bad = cycles(20, 420, { pulseMs: 250, clicksPerBlock: 0 });
    const fs = metrics(bridge(bad, 10000)).findings;
    expect(fs.length).toBeGreaterThan(1);
    expect(fs[0].severity).toBeGreaterThanOrEqual(fs[fs.length - 1].severity);
  });

  it("stays silent when there is no sneak rhythm to judge", () => {
    const noSneak = bridge([ev(1000, "RMB", "down"), ev(1030, "RMB", "up")]);
    expect(metrics(noSneak).findings).toEqual([]);
  });
});

describe("holds", () => {
  it("pairs down/up into spans and ignores other keys", () => {
    const events = [
      ev(0, "W", "down"),
      ev(100, "SHIFT", "down"),
      ev(150, "SHIFT", "up"),
      ev(500, "W", "up"),
    ];
    expect(holds(events, "SHIFT")).toEqual([{ startMs: 100, endMs: 150 }]);
    expect(holds(events, "W")).toEqual([{ startMs: 0, endMs: 500 }]);
  });

  it("closes an unclosed hold at the last event's timestamp", () => {
    const events = [ev(0, "SHIFT", "down"), ev(1000, "RMB", "down")];
    expect(holds(events, "SHIFT")).toEqual([{ startMs: 0, endMs: 1000 }]);
  });
});

describe("activeMs", () => {
  it("subtracts gaps longer than the idle threshold", () => {
    // 0 -> 1000 active, 1000 -> 6000 idle (5s gap), 6000 -> 7000 active
    const events = [ev(0, "W", "down"), ev(1000, "W", "up"), ev(6000, "W", "down"), ev(7000, "W", "up")];
    expect(activeMs(events)).toBe(2000); // 7000 span - 5000 idle
  });

  it("keeps short gaps inside the active window", () => {
    const events = [ev(0, "W", "down"), ev(500, "W", "up"), ev(1000, "RMB", "down")];
    expect(activeMs(events)).toBe(1000);
  });
});

describe("bridgingSegments", () => {
  it("detects an S-hold without W as one segment", () => {
    expect(bridgingSegments([ev(0, "S", "down"), ev(5000, "S", "up")])).toEqual([
      { startMs: 0, endMs: 5000 },
    ]);
  });

  it("a long W press cuts a segment in two", () => {
    const segs = bridgingSegments([
      ev(0, "S", "down"),
      ev(3500, "W", "down"),
      ev(4500, "W", "up"), // 1000ms > merge gap -> cuts
      ev(8000, "S", "up"),
    ]);
    expect(segs).toEqual([
      { startMs: 0, endMs: 3500 },
      { startMs: 4500, endMs: 8000 },
    ]);
  });

  it("merges a brief S re-grip blip", () => {
    const segs = bridgingSegments([
      ev(0, "S", "down"),
      ev(4000, "S", "up"),
      ev(4300, "S", "down"), // 300ms release < merge gap -> merges
      ev(8000, "S", "up"),
    ]);
    expect(segs).toEqual([{ startMs: 0, endMs: 8000 }]);
  });

  it("discards a segment shorter than the minimum", () => {
    expect(bridgingSegments([ev(0, "S", "down"), ev(2000, "S", "up")])).toEqual([]);
  });

  describe.each([
    ["A+S", ["A"]],
    ["S+D", ["D"]],
    ["S-only", []],
  ] as const)("%s produces one segment", (_label, companions) => {
    it("detects the run", () => {
      const events: InputEvent[] = [
        ev(0, "S", "down"),
        ...companions.map((k) => ev(0, k, "down")),
        ...companions.map((k) => ev(5000, k, "up")),
        ev(5000, "S", "up"),
      ];
      expect(bridgingSegments(events)).toEqual([{ startMs: 0, endMs: 5000 }]);
    });
  });

  it("A+D held together while W is down produces no segment (S never held)", () => {
    const events = [
      ev(0, "W", "down"),
      ev(0, "A", "down"),
      ev(0, "D", "down"),
      ev(5000, "W", "up"),
      ev(5000, "A", "up"),
      ev(5000, "D", "up"),
    ];
    expect(bridgingSegments(events)).toEqual([]);
  });

  it("keeps a segment exactly at the minimum length", () => {
    expect(bridgingSegments([ev(0, "S", "down"), ev(3000, "S", "up")])).toEqual([
      { startMs: 0, endMs: 3000 },
    ]);
  });

  it("discards a segment one millisecond under the minimum length", () => {
    expect(bridgingSegments([ev(0, "S", "down"), ev(2999, "S", "up")])).toEqual([]);
  });
});

describe("metrics", () => {
  it("counts only in-segment placements (RMB downs)", () => {
    const events = [
      ev(0, "S", "down"),
      ev(6000, "S", "up"),
      ev(2000, "RMB", "down"),
      ev(2300, "RMB", "down"), // both in-segment
      ev(7000, "RMB", "down"),
      ev(7300, "RMB", "down"), // both after the segment ends -> ignored
    ];
    expect(metrics(events).placements).toBe(2);
  });

  it("pairs a shift release with the next placement inside the 500ms window", () => {
    const events = bridge([
      ev(1000, "SHIFT", "down"),
      ev(1100, "SHIFT", "up"),
      ev(1250, "RMB", "down"), // 150ms after release -> counted
      ev(1300, "RMB", "up"),
      ev(3000, "SHIFT", "down"),
      ev(3100, "SHIFT", "up"),
      ev(4000, "RMB", "down"), // 900ms after release -> NOT counted
    ]);
    const m = metrics(events);
    expect(m.releaseToPlaceMs.values).toEqual([150]);
    expect(m.shiftPulses.durations).toEqual([100, 100]);
  });

  it("excludes long pauses from click-interval rhythm and gives cv=0 for a steady rhythm", () => {
    const events = bridge([
      ev(1000, "RMB", "down"),
      ev(1300, "RMB", "down"),
      ev(1600, "RMB", "down"), // steady 300ms rhythm
      ev(6000, "RMB", "down"), // 4400ms gap -> excluded from clickIntervals
    ]);
    const m = metrics(events);
    expect(m.clickIntervals.values).toEqual([300, 300]);
    expect(m.clickIntervals.cv).toBe(0);
  });

  it("shift duty is 1 when shift is held across the whole bridging segment", () => {
    const events = [
      ev(0, "S", "down"),
      ev(0, "SHIFT", "down"),
      ev(2000, "RMB", "down"),
      ev(4000, "SHIFT", "up"),
      ev(4000, "S", "up"),
    ];
    expect(metrics(events).shiftDuty).toBe(1);
  });

  it("reports run count, bridging time and longest run across segments", () => {
    const events = [
      ev(0, "S", "down"),
      ev(4000, "S", "up"), // run 1: 4000ms
      ev(10000, "S", "down"),
      ev(15000, "S", "up"), // run 2: 5000ms
    ];
    const m = metrics(events);
    expect(m.runCount).toBe(2);
    expect(m.bridgingMs).toBe(9000);
    expect(m.longestRunMs).toBe(5000);
  });

  it("returns zeroed metrics for a session with no bridging", () => {
    const m = metrics([ev(0, "W", "down"), ev(5000, "W", "up"), ev(2000, "RMB", "down")]);
    expect(m.segments).toEqual([]);
    expect(m.placements).toBe(0);
    // no bridging => no speed at all, rather than a confident 0.00 blocks/sec
    expect(m.speed).toBeNull();
    expect(m.shiftDuty).toBe(0);
    expect(m.clickIntervals.cv).toBe(0);
  });
});
