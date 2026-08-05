/** Dimension groupers for the Breakdowns hub — every section detail page is
 * the same shape: rows of {name, games, fkdr, wins, losses, beds} produced by
 * slicing the games array a different way. Adding a breakdown = adding a
 * grouper + a card entry, no restructuring (design handoff, Breakdowns).
 */
import type { Game } from "../api/types";
import { aggregate, type Aggregate } from "./stats";

export interface BreakdownRow {
  name: string;
  agg: Aggregate;
}

/** Display names for game.items categories (parser: resolve.categorize_item). */
export const ITEM_LABELS: Record<string, string> = {
  fireball: "Fireball",
  gapple: "Golden Apple",
  jump_potion: "Jump Potion",
  invis_potion: "Invis Potion",
  speed_potion: "Speed Potion",
  kb_stick: "KB Stick",
  pearl: "Ender Pearl",
  bridge_egg: "Bridge Egg",
  obsidian: "Obsidian",
  tnt: "TNT",
  magic_milk: "Magic Milk",
  utility: "Defensive gadget",
  chain_armor: "Chainmail Armor",
  iron_armor: "Iron Armor",
  dia_armor: "Diamond Armor",
  dia_sword: "Diamond Sword",
  bow: "Bow",
  water: "Water Bucket",
};

/** Shop upgrades, shortened for a table row. Anything not listed falls back to
 * the raw Hypixel string, so a new upgrade shows up rather than vanishing. */
export const UPGRADE_LABELS: Record<string, string> = {
  "Sharpened Swords": "Sharpness",
  "Reinforced Armor I": "Prot I",
  "Reinforced Armor II": "Prot II",
  "Reinforced Armor III": "Prot III",
  "Reinforced Armor IV": "Prot IV",
  "Maniac Miner I": "Haste I",
  "Maniac Miner II": "Haste II",
  "Iron Forge": "Iron Forge",
  "Golden Forge": "Golden Forge",
  "Emerald Forge": "Emerald Forge",
  "Molten Forge": "Molten Forge",
  "Heal Pool": "Heal Pool",
  "Dragon Buff": "Dragon Buff",
  "It's a trap!": "Trap: It's a trap!",
  "Counter-Offensive Trap": "Trap: Counter-Offensive",
  "Alarm Trap": "Trap: Alarm",
  "Miner Fatigue Trap": "Trap: Miner Fatigue",
};

export type Grouper = (g: Game) => string | string[] | null;

export function groupBy(games: Game[], key: Grouper): BreakdownRow[] {
  const by = new Map<string, Game[]>();
  for (const g of games) {
    const k = key(g);
    if (k == null) continue;
    for (const name of Array.isArray(k) ? k : [k]) {
      if (!name) continue;
      const list = by.get(name) ?? [];
      list.push(g);
      by.set(name, list);
    }
  }
  return [...by.entries()]
    .map(([name, gs]) => ({ name, agg: aggregate(gs) }))
    .sort((a, b) => b.agg.games - a.agg.games);
}

const WEEKDAYS = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"];

function weekday(iso: string | null): string | null {
  if (!iso) return null;
  const [y, m, d] = iso.split("-").map(Number);
  if (!y || !m || !d) return null;
  return WEEKDAYS[new Date(y, m - 1, d).getDay()];
}

function hourBucket(startTs: string | null): string | null {
  if (!startTs) return null;
  const h = Number(startTs.split(":")[0]);
  if (Number.isNaN(h)) return null;
  const label = (x: number) => `${String(x).padStart(2, "0")}:00`;
  return `${label(h)}–${label((h + 1) % 24)}`;
}

function lengthBucket(s: number | null): string | null {
  if (s == null) return null;
  if (s < 180) return "Rush (<3m)";
  if (s < 360) return "Fast (3–6m)";
  if (s < 600) return "Medium (6–10m)";
  return "Grind (10m+)";
}

/** Seconds from the game starting to YOUR bed falling, or null if it held.
 * Both timestamps are time-of-day strings; the wrap handles a game that
 * crosses midnight. */
function bedLostAt(g: Game): number | null {
  if (!g.your_bed_lost || !g.start_ts || !g.bed_lost_ts) return null;
  const secs = (hms: string) => {
    const [h, m, s] = hms.split(":").map(Number);
    return h * 3600 + m * 60 + s;
  };
  const d = secs(g.bed_lost_ts) - secs(g.start_ts);
  return d < 0 ? d + 86400 : d;
}

/** A share computed over fewer than this many team finals is noise: 1-of-2
 * lands in a different bucket than 2-of-4 while meaning the same thing.
 * Measured on the real corpus, the 0% and 100% rows were dominated by games
 * with ~3 team finals and both showed ~22% win rates — an artefact of short
 * lost games, not evidence about carrying. */
/** Default minimum games for a row to be shown, used by BOTH the detail table
 * and the hub card's group count.
 *
 * It was 5, which let the page open full of noise: Maps produced 152 rows with
 * 126 under 20 games, Teammates 365 rows with 359 under 20. A row like
 * "n=20, 95% WR, 21.00 FKDR" was rendered with exactly the same authority as
 * one built on 379 games. The hub card counted raw rows too, so "152 groups"
 * implied 152 findings when about 26 were usable. */
export const DEFAULT_MIN_GAMES = 20;

/**
 * Sections that group on something you can only DO if the game lasted are
 * restricted to games of at least this length.
 *
 * Long games are won far more often than short ones, and buying an item,
 * collecting a diamond or taking a death all require surviving. Ungated, those
 * sections measured game length wearing a costume — and two of them reversed
 * once length was held constant:
 *
 *   fireball   raw +24.1 overall, but -6.3 within 7-10m and -14.8 within 10m+
 *   diamonds   raw +23.8 overall, but ~0 inside a matched length band
 *
 * Restricting the pool doesn't remove the effect entirely (the 6min+ pool wins
 * 67.3% against a 54.8% overall), but it makes the ROWS comparable to each
 * other, which is what the table asks you to do. Every affected section says
 * so in its description.
 */
const MIN_COMPARABLE_LENGTH_S = 360;

/**
 * Your share of the team's final kills. Solos has no team, so it is skipped
 * rather than reported as a meaningless 100%.
 *
 * THE GATE IS THE WHOLE PROBLEM WITH THIS SECTION. It used to admit only games
 * with 4+ team final kills, and that single condition decided the answer:
 *
 *     team finals >= 4 : 84.3% WR (n=999)
 *     team finals <  4 : 12.4% WR (n=693)
 *
 * a 71.9-point swing before any bucketing. Getting four team finals essentially
 * IS winning, so every bucket landed near 85% and the section reported the
 * outcome it had conditioned on — the same circularity that got the old
 * "Bed held" row (99.6% win rate) removed.
 *
 * Gating on game LENGTH instead keeps the question answerable without letting
 * the outcome in through the back door. Long games are still won more often
 * (+12.5 points against the overall average, stated in the section text), but
 * that is a property of the pool rather than of the buckets, and the buckets
 * now actually separate:
 *
 *     0%    mate did all of it   22.8%
 *     1-33% supporting           77.0%
 *     34-66% even split          78.3%
 *     67-99% carrying            84.8%
 *     100%  all of them          47.7%
 *
 * The shape is a genuine finding rather than an artefact: doing none of the
 * finals is bad, and doing literally ALL of them is nearly as bad, because it
 * usually means your team stopped contributing.
 */
function killParticipation(g: Game): string | null {
  const team = g.team_final_kills ?? 0;
  if (!team || !g.teammates.length) return null;   // solos / no data
  if ((g.duration_s ?? 0) < MIN_COMPARABLE_LENGTH_S) return null;
  const share = (g.your_final_kills ?? 0) / team;
  if (share === 0) return "0% — mate did all of it";
  if (share < 0.34) return "1–33% — supporting";
  if (share < 0.67) return "34–66% — even split";
  if (share < 1) return "67–99% — carrying";
  return "100% — all of them";
}

/** How fast the team got its economy going. */
function firstUpgradeBucket(g: Game): string | null {
  const s = g.first_upgrade_s;
  if (s == null) return "No upgrades bought";
  if (s < 60) return "First upgrade <1m";
  if (s < 120) return "First upgrade 1–2m";
  if (s < 240) return "First upgrade 2–4m";
  return "First upgrade 4m+";
}

/** Coarse part of the day — 24 hourly rows crossed with 7 weekdays would be
 * 168 buckets, most of them empty. Four parts keeps it readable. */
function dayPart(startTs: string | null): string | null {
  if (!startTs) return null;
  const h = Number(startTs.split(":")[0]);
  if (Number.isNaN(h)) return null;
  if (h < 6) return "night";
  if (h < 12) return "morning";
  if (h < 18) return "afternoon";
  return "evening";
}

const DEATH_CAUSE_LABELS: Record<string, string> = {
  void_self: "Void — you fell in",
  void_knocked: "Void — knocked in by a player",
  player: "Killed by a player",
  other: "Other / unclassified",
};

/** Diamonds gate every upgrade, so how fast you got your first is upstream of
 * the whole economy. */
function firstDiamondBucket(g: Game): string | null {
  const s = g.first_diamond_s;
  // No diamond means no TIMING to report. It used to return its own label
  // here, which duplicated diamondVolume's "0 diamonds" row exactly - the
  // same games appeared twice under two names, both reading n=48.
  if (s == null) return null;
  if (s < 60) return "First diamond <1m";
  if (s < 120) return "First diamond 1–2m";
  if (s < 180) return "First diamond 2–3m";
  return "First diamond 3m+";
}

function diamondVolume(g: Game): string | null {
  const n = g.diamond_pickups;
  if (n == null) return null;
  if (n === 0) return "0 diamonds";
  if (n <= 3) return "1–3 diamonds";
  if (n <= 6) return "4–6 diamonds";
  return "7+ diamonds";
}

function sessionPosition(pos: number | null): string | null {
  if (pos == null) return null;
  if (pos < 3) return "Warmup (games 1–3)";
  if (pos < 10) return "Mid-session (4–10)";
  if (pos < 15) return "Peak (11–15)";
  return "Fatigue (16+)";
}

/** Position of each game within its DAY.
 *
 * This used to read `g.idx`, the index within a `session_id` — and a session
 * id resets whenever the client restarts or the log rotates, so one evening's
 * play was split across several "sessions". That put only 65 games in the
 * late bucket and flattened the effect to almost nothing. Measured both ways
 * on the same 1,756 games:
 *
 *     per day   1-3 51.5%  4-10 56.0%  11-15 61.9%  16+ 50.4%   spread 11.6
 *     by idx    1-3 52.3%  4-10 56.1%  11-15 55.7%  16+ 53.8%   spread  3.8
 *
 * The warm-up climb and the late-session drop are both real and both invisible
 * under `idx`. A day is also what a player actually means by "my session".
 */
export function withDayPosition(games: Game[]): Game[] {
  const byDay = new Map<string, Game[]>();
  for (const g of games) {
    if (!g.date) continue;
    const list = byDay.get(g.date) ?? [];
    list.push(g);
    byDay.set(g.date, list);
  }
  const pos = new Map<number, number>();
  for (const list of byDay.values()) {
    [...list]
      .sort((a, b) => `${a.start_ts ?? ""}`.localeCompare(`${b.start_ts ?? ""}`))
      .forEach((g, i) => pos.set(g.id, i));
  }
  return games.map((g) => ({ ...g, _dayPos: pos.get(g.id) ?? null }));
}

/** Streak bucket for every game, based on the games BEFORE it in its session.
 *
 * Streak is the one dimension that isn't a pure function of a single row, so it
 * is computed up front and stashed on a copy rather than being derived inside
 * the grouper (which only ever sees one game).
 */
export function withStreakState(games: Game[]): Game[] {
  const bySession = new Map<string, Game[]>();
  for (const g of games) {
    const list = bySession.get(g.session_id) ?? [];
    list.push(g);
    bySession.set(g.session_id, list);
  }
  const label = new Map<number, string>();
  for (const list of bySession.values()) {
    const ordered = [...list].sort((a, b) => (a.idx ?? 0) - (b.idx ?? 0));
    let run = 0;                 // + for wins, − for losses
    for (const g of ordered) {
      label.set(
        g.id,
        run === 0 ? "First of session"
          : run >= 2 ? "On a 2+ win streak"
          : run === 1 ? "After a win"
          : run <= -2 ? "After 2+ losses"
          : "After a loss",
      );
      if (g.result === "WIN") run = run > 0 ? run + 1 : 1;
      else if (g.result === "FINAL_DEATH") run = run < 0 ? run - 1 : -1;
      // UNRESOLVED leaves the run untouched — it isn't a result either way
    }
  }
  return games.map((g) => ({ ...g, _streak: label.get(g.id) ?? null }));
}

export interface BreakdownSection {
  key: string;
  title: string;
  desc: string;
  /** [log] auto-derived vs [tag] requires tagging */
  source: "log" | "tag";
  grouper: Grouper;
  /** Optional pass over the whole list before grouping, for dimensions that
   * depend on a game's NEIGHBOURS rather than only on itself. */
  prepare?: (games: Game[]) => Game[];
}

export const SECTIONS: BreakdownSection[] = [
  {
    key: "maps",
    title: "Maps",
    desc: "Performance by map",
    source: "log",
    grouper: (g) => g.map,
  },
  {
    key: "teammates",
    title: "Teammates",
    desc: "Synergy and win rates with specific players",
    source: "log",
    grouper: (g) => (g.teammates.length ? g.teammates : "solo-queue"),
  },
  {
    key: "modes",
    title: "Modes",
    desc: "Solos, Doubles, Trios, Fours",
    source: "log",
    grouper: (g) => g.mode ?? "Unknown",
  },
  // REMOVED 2026-08-01: "Partied vs Solo-queue".
  //
  // It grouped on `teammates.length`, which in Doubles is true for a random duo
  // mate too — so it compared "had anyone" against "had nobody" and called that
  // premade-vs-solo. Recording real party membership (Game.party) was tried and
  // the result is WORSE, because the data can't support the question at all:
  // a WIN prints a summary line naming your real team, so a random mate is
  // detected; a LOSS prints nothing, so a random mate is invisible. Measured
  // over the real corpus, the buckets split by OUTCOME rather than by party:
  //
  //     premade        198W /176L   53%   (plausible)
  //     random mate     17W /  0L  100%   (artifact)
  //     no mate found    1W / 14L    7%   (the mirror artifact)
  //
  // Any version of this section reports "did you win" dressed up as "did you
  // premade". `Game.party` is still recorded (and is now correct) for the games
  // list; it just can't carry a breakdown.
  {
    key: "time",
    title: "Time of Day",
    desc: "Stats sliced by hour you queued",
    source: "log",
    grouper: (g) => hourBucket(g.start_ts),
  },
  {
    key: "weekday",
    title: "Day of Week",
    desc: "Weekday vs weekend form",
    source: "log",
    grouper: (g) => weekday(g.date),
  },
  {
    key: "flow",
    title: "Game Flow",
    desc: "How the game went — who broke the first bed, and whether yours fell early or late",
    source: "log",
    // Reworked 2026-08-01. The old version's headline row was "Bed held" vs
    // "Own bed lost", which is circular: holding your bed and winning are
    // nearly the same event, so it reported ~100% and taught nothing. These
    // rows all ask something the outcome doesn't already answer.
    grouper: (g) => {
      const out: string[] = [];
      // Did drawing first blood matter? Unbiased — the kill feed prints for
      // wins and losses alike.
      out.push(g.first_bed ? "You broke the first bed" : "Someone else did");
      // WHEN your bed fell, not whether. An early loss and a last-minute one
      // are completely different games.
      const lost = bedLostAt(g);
      if (lost !== null) out.push(lost < 300 ? "Bed lost early (<5m)" : "Bed lost late (5m+)");
      return out;
    },
  },
  {
    key: "length",
    title: "Game Length",
    desc: "How long games ran. This is CONTEXT, not a lever — a game is long because it was close, so the win rate here mostly restates that. It is here because game length drives several other sections and it helps to see its shape directly.",
    source: "log",
    // Split out of Game Flow 2026-08-04. Mixed in there it was compared against
    // one overall average alongside first-bed and bed-timing rows, and the
    // length rows were near-circular on their own: "Medium (6-10m)" won 68.3%
    // against "Fast (3-6m)" at 44.5%, which says little more than "games that
    // lasted are games you were still in".
    grouper: (g) => lengthBucket(g.duration_s),
  },
  {
    key: "participation",
    title: "Kill Participation",
    desc: "Your share of the team's final kills — carrying vs being carried. Only games that ran 6+ minutes, so the split isn't decided by a game ending before anyone got going. Those games are won more often than average, so read the rows against each other rather than against your overall win rate.",
    source: "log",
    grouper: killParticipation,
  },
  {
    key: "streak",
    title: "Streak State",
    desc: "Do you tilt? Form after a win vs after a loss",
    source: "log",
    prepare: withStreakState,
    grouper: (g) => (g as Game & { _streak?: string | null })._streak ?? null,
  },
  {
    key: "daypart",
    title: "Day & Time",
    desc: "Weekday crossed with time of day — is Friday night your worst slot?",
    source: "log",
    grouper: (g) => {
      const d = weekday(g.date);
      const p = dayPart(g.start_ts);
      return d && p ? `${d} ${p}` : null;
    },
  },
  {
    key: "economy",
    title: "Early Economy",
    desc: "How fast your team bought its first upgrade",
    source: "log",
    grouper: firstUpgradeBucket,
  },
  {
    key: "deaths",
    title: "How You Die",
    desc: "Every death, not just the one that ended the game. Void vs players is all the log can tell you — death messages are cosmetics that change constantly, so a finer split would be guesswork.",
    source: "log",
    // A game lands in a row for EACH cause it contained, and separately in a
    // void-exposure bucket. Grouping by "dominant cause" alone would hide the
    // games where one bad fall decided it.
    grouper: (g) => {
      const causes = g.death_causes ?? {};
      const out = Object.keys(causes)
        .filter((c) => causes[c] > 0)
        .map((c) => DEATH_CAUSE_LABELS[c] ?? c);
      // Void exposure as a RATE, not a count. Counting them made a long game
      // land in "2+ void deaths" automatically, so the row measured length:
      // raw, having a void death looked GOOD for you (+5.0 win rate), and
      // controlled for length it was bad in every band (-11.5, -4.5, -6.2).
      // Per 10 minutes it behaves: 71.1% at under 1.5, 47.6% at 3+.
      const voids = (causes.void_self ?? 0) + (causes.void_knocked ?? 0);
      const mins = (g.duration_s ?? 0) / 600;
      if (mins > 0.2) {
        const rate = voids / mins;
        out.push(
          voids === 0 ? "No void deaths"
            : rate < 1.5 ? "Under 1.5 void deaths / 10m"
            : rate < 3 ? "1.5–3 void deaths / 10m"
            : "3+ void deaths / 10m",
        );
      }
      return out;
    },
  },
  {
    key: "diamonds",
    title: "Diamond Economy",
    desc: "How fast and how many — diamonds gate every team upgrade. Only games that ran 6+ minutes. Across all games more diamonds looks strongly better, but that is mostly game length: a game you lost in three minutes never reached mid. Inside a comparable pool the volume rows point the other way, because farming diamonds means the game dragged.",
    source: "log",
    grouper: (g) => {
      if ((g.duration_s ?? 0) < MIN_COMPARABLE_LENGTH_S) return null;
      const out: string[] = [];
      const first = firstDiamondBucket(g);
      const vol = diamondVolume(g);
      if (first) out.push(first);
      if (vol) out.push(vol);
      return out;
    },
  },
  {
    key: "position",
    title: "Session Position",
    desc: "Warmup vs fatigue — where in the day's session a game fell",
    source: "log",
    prepare: withDayPosition,
    grouper: (g) =>
      sessionPosition((g as Game & { _dayPos?: number | null })._dayPos ?? null),
  },
  {
    key: "upgrades",
    title: "Upgrades",
    desc: "Every team upgrade — prot tiers, Haste, forges, traps",
    source: "log",
    // Was prot tier alone, which couldn't answer "does Haste win games". Every
    // upgrade your team bought is now its own row, and a game with none lands
    // in its own row so the with/without comparison is visible.
    grouper: (g) => {
      const names = (g.upgrade_names ?? []).map((n) => UPGRADE_LABELS[n] ?? n);
      return names.length ? names : "No upgrades";
    },
  },
  {
    key: "items",
    title: "Misc Items",
    desc: "Do potions, pearls, KB stick, water… actually win games? Only games that ran 6+ minutes: ungated, this measured whether you survived long enough to reach the shop, and every item looked like a winner. Compare the rows against each other, not against your overall win rate.",
    source: "log",
    grouper: (g) => {
      if ((g.duration_s ?? 0) < MIN_COMPARABLE_LENGTH_S) return null;
      const bought = Object.keys(g.items ?? {}).map(
        (k) => ITEM_LABELS[k] ?? k,
      );
      // every game lands in a row, so the with/without comparison is visible
      return bought.length ? bought : "No tracked items";
    },
  },
  {
    key: "tags",
    title: "Tags",
    desc: "Every tag as its own row — new tags appear automatically",
    source: "tag",
    grouper: (g) => (g.tags.length ? g.tags : null),
  },
];

export function sectionByKey(key: string): BreakdownSection | undefined {
  return SECTIONS.find((s) => s.key === key);
}
