import type { Game } from "../../api/types";

/** Build a Game with sensible defaults; override only what a test cares about.
 * Ids auto-increment (reset per test file — vitest isolates modules). */
let nextId = 1;

export function mkGame(p: Partial<Game> = {}): Game {
  const id = p.id ?? nextId++;
  return {
    id,
    game_key: p.game_key ?? `key-${id}`,
    session_id: p.session_id ?? "s1",
    idx: p.idx ?? 0,
    start_ts: p.start_ts ?? "12:00:00",
    end_ts: p.end_ts ?? "12:05:00",
    mode: p.mode ?? "Doubles",
    result: p.result ?? "WIN",
    your_bed_lost: p.your_bed_lost ?? 0,
    bed_lost_ts: p.bed_lost_ts ?? null,
    win_ts: p.win_ts ?? null,
    final_death_ts: p.final_death_ts ?? null,
    date: p.date === undefined ? "2026-07-01" : p.date,
    teammates: p.teammates ?? [],
    party: p.party ?? 0,
    map: p.map === undefined ? "Lighthouse" : p.map,
    replay: p.replay ?? 0,
    your_kills: p.your_kills ?? 0,
    your_final_kills: p.your_final_kills ?? 0,
    your_deaths: p.your_deaths ?? 0,
    your_final_deaths: p.your_final_deaths ?? 0,
    beds_broken: p.beds_broken ?? 0,
    prot_level: p.prot_level ?? 0,
    upgrades: p.upgrades ?? 0,
    est_diamonds: p.est_diamonds ?? 0,
    items: p.items ?? {},
    tags: p.tags ?? [],
    duration_s: p.duration_s === undefined ? 300 : p.duration_s,
    // NOTE: this builder lists every field explicitly, so anything missing
    // here is silently dropped from overrides. Add new Game fields to it.
    counted: p.counted,
    uncounted_reason: p.uncounted_reason,
  };
}
