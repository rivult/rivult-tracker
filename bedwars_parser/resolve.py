"""Resolver: events → games with terminal states.

Reference §4 outcome model — every game resolves to one of:

    WIN         saw a "(Win)" reward
    FINAL_DEATH you were final-killed (there is no "you lost" message in
                Hypixel; a loss is the *absence* of a win)
    UNRESOLVED  the log ended mid-game with neither marker (the crash case)

Beyond slicing, ``resolve`` runs one linear context pass over the whole event
stream, tracking three things no single slice can know:

* the most recent ``/locraw`` payload → exact gametype/mode/map per game
* replay state — Hypixel replays run on dedicated servers
  (``"gametype":"REPLAY"``); every chat line seen while watching one is marked
  ``e.replay`` so replayed kill feeds can never pollute stats or fabricate games
* current party membership → teammates even in games you lost (the summary
  line only prints on wins)
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

from .events import Event, Game, Kind, Outcome

# "You purchased X" or "<name> purchased X" (team upgrades are broadcast to all;
# "You" matches the IGN charset too)
_PURCHASE = re.compile(r"^[A-Za-z0-9_]{1,16} purchased (.+)$")

# locraw "mode" → display name, using the names players actually say. Note the
# Hypixel codes: FOUR_FOUR is 4 teams of 4 ("Fours"), FOUR_THREE is 4 teams of 3
# ("Trios"), and TWO_FOUR is the separate 2-teams-of-4 "4v4" mode. Unknown
# suffixes fall back to a prettified form so a new mode shows honestly.
_LOCRAW_BASE = {
    "EIGHT_ONE": "Solos",
    "EIGHT_TWO": "Doubles",
    "FOUR_THREE": "Trios",
    "FOUR_FOUR": "Fours",
    "TWO_FOUR": "4v4",
    "PRACTICE": "Practice",
    "CASTLE": "Castle",
    "TWO_ONE_DUELS": "Duels",
}


def _mode_name(locraw_mode: str) -> str:
    m = locraw_mode.removeprefix("BEDWARS_")
    if m in _LOCRAW_BASE:
        return _LOCRAW_BASE[m]
    for base, name in _LOCRAW_BASE.items():
        if m.startswith(base + "_"):
            extra = m[len(base) + 1:].replace("_", " ").title()
            return f"{name} ({extra})"
    return m.replace("_", " ").title()


def resolve(events: list[Event], you: str) -> list[Game]:
    """Segment the event stream into games at each ``GAME_START``.

    A game owns every event from its start up to (but not including) the next
    start — which includes its own post-game summary and win reward, since
    those print before the next game begins.
    """
    starts: list[int] = []
    meta: dict[int, tuple] = {}   # start idx -> (locraw, in_replay, party, cap)
    last_locraw: Optional[dict] = None
    in_replay = False
    party: set[str] = set()
    pending_cap: Optional[int] = None   # lobby size from the queue's join lines

    for i, e in enumerate(events):
        if e.kind is Kind.LOCRAW and e.data:
            gt = e.data.get("gametype")
            in_replay = gt == "REPLAY"
            if gt == "BEDWARS" and e.data.get("mode"):
                last_locraw = e.data
        elif "Attempting to load replay" in e.msg:
            in_replay = True
        elif in_replay and e.kind in (Kind.REWARD, Kind.WIN, Kind.RESPAWN,
                                      Kind.RESPAWNED, Kind.JOIN):
            # Replays can't produce personal reward/respawn lines or lobby
            # joins — seeing one proves the replay is over. Without this, logs
            # from clients that never print locraw would stay "in replay"
            # forever after one watched replay, silently eating every real
            # game that followed (16 real games, 7 wins, in this corpus).
            in_replay = False
        elif e.kind is Kind.PARTY:
            action = (e.data or {}).get("action")
            if action == "join" and e.ign:
                party.add(e.ign)
            elif action == "leave" and e.ign:
                party.discard(e.ign)
            elif action == "clear":
                party.clear()
            elif action == "members" and e.players:
                party.update(e.players)
        elif (e.kind is Kind.CHAT and e.data
              and e.data.get("channel") == "party" and e.ign):
            party.add(e.ign)          # someone talking in party chat is in it

        if e.kind is Kind.JOIN and e.lobby_cap and not in_replay:
            # "x has joined (n/16)!" — the queue for the NEXT game. The cap is
            # the mode's lobby size (8=Solos, 12=Trios, 16=Doubles/Fours) and
            # doesn't shrink when a game starts a player or two short.
            pending_cap = e.lobby_cap

        e.replay = in_replay
        if e.kind is Kind.GAME_START:
            starts.append(i)
            meta[i] = (last_locraw, in_replay, frozenset(party) - {you},
                       pending_cap)
            last_locraw = None        # consumed — the next game presents its own
            pending_cap = None

    games: list[Game] = []
    for gi, start in enumerate(starts):
        end = starts[gi + 1] if gi + 1 < len(starts) else len(events)
        locraw, replay_flag, party_snap, cap = meta[start]
        games.append(_resolve_slice(
            gi + 1, events[start:end], you, locraw, replay_flag, party_snap,
            cap))
    return games


_TEAM_SIZE = {"Solos": 1, "Doubles": 2, "Trios": 3, "Fours": 4, "4v4": 4}

# English words that leak out of party sentences ("You left the party", invites)
# and must never be taken as a player name, as a last line of defence on top of
# the seen-in-game check below.
_NOT_NAMES = {"you", "to", "the", "their", "a", "and", "party", "your", "has",
              "summoned", "server", "leader",
              "was", "for", "this", "all", "join", "left", "leader", "members"}


def _teammates(mode: str, summary_players: list, party: frozenset,
               who_players: set, seen_players: set, you: str) -> list:
    """Your team for this game, robust to mode.

    - Solos (team size 1): nobody is your teammate, even in a party.
    - The summary line names your real team (a win) — trusted outright, its
      parse is anchored so junk can't get in.
    - Party members fill the remaining slots up to team size. When the game
      has a /who, a party member must be in it (a mate who missed the queue
      isn't a teammate); without a /who they're trusted — a party member who
      never got a kill used to vanish here, which under-reported teammates.
    - A party larger than your team splits across teams, so never take more
      than fit; the stoplist blocks stray English words as a last defence.
    """
    base = mode.split(" ")[0]           # "Doubles (Armed)" -> "Doubles"
    size = _TEAM_SIZE.get(base)
    if size == 1:
        return []
    from_party = [p for p in party
                  if p not in summary_players
                  and (p in who_players or p in seen_players or not who_players)]
    ranked = list(dict.fromkeys(list(summary_players) + from_party))
    ranked = [p for p in ranked if p != you and p.lower() not in _NOT_NAMES]
    if size is not None:
        ranked = ranked[:size - 1]
    return ranked


# Colours that only exist in 8-team modes (Solos/Doubles); 4-team modes
# (Trios/Fours) use exactly Red/Blue/Green/Yellow.
_EIGHT_TEAM_COLORS = {"Aqua", "White", "Pink", "Gray", "Grey"}


def _game_mode_heuristic(cap: Optional[int], colors: set, who_max: int,
                         n_elims: int, summary_size: int) -> str:
    """Fallback for logs without a locraw line (no /locraw-printing mod).

    Primary signal: the queue lobby size from "has joined (n/CAP)!" —
    8 = Solos, 12 = Trios, 16 = Doubles or Fours. The cap is the mode's
    capacity, so a game starting one or two players short still shows the
    right cap. A 16-lobby is split by team evidence: Aqua/White/Pink/Gray
    (bed/elim/shout-chat colours) or 4+ eliminations prove 8 teams = Doubles;
    a winning team of 3-4 (summary) proves Fours. /who size is only a
    last resort — people run it mid-game after players have left.
    """
    eight_team = bool(colors & _EIGHT_TEAM_COLORS) or len(colors) >= 5 \
        or n_elims >= 4
    if cap == 8:
        # a /8 lobby is Solos (8x1) — except the rare 2-team 4v4 (2x4), which
        # a winning summary reveals via a team of 3-4
        return "4v4" if summary_size >= 2 else "Solos"
    if cap == 12:
        return "Trios"
    if cap == 16:
        if summary_size == 1:            # your winning team was a duo
            return "Doubles"
        if summary_size >= 2:            # team of 3-4
            return "Fours"
        if eight_team:
            return "Doubles"
        if n_elims >= 2 or len(colors) >= 3:
            return "Fours"               # sustained play, strictly R/B/G/Y
        return "Doubles"                 # short game, no evidence: majority mode
    # No cap seen — happens when you insta-load into a game (no queue lobby,
    # so no "(n/16)" join lines print) or the log starts mid-session. Fall
    # back to /who size and colours, with the short-start tolerance.
    if who_max >= 13:
        return "Doubles" if eight_team else \
            ("Fours" if summary_size >= 2 or len(colors) >= 3 else "Doubles")
    if who_max >= 9:
        # 9-12 alive is Trios territory, unless 8-team colours prove a
        # Doubles game whose /who was simply run after players left
        return "Doubles" if eight_team else "Trios"
    if who_max >= 2:
        return "Doubles" if eight_team else "Solos"
    if eight_team:
        return "Doubles"
    return "Unknown"


_PERSONAL = {Kind.REWARD, Kind.WIN, Kind.RESPAWN, Kind.RESPAWNED}


# Armed-mode fingerprints (evidence: real game 2026-07-19 00:07 — a 16-cap
# Armed lobby the cap heuristic called plain Doubles). Guns exist only in
# Armed, so any of these proves the modifier; normal games can't print them.
_ARMED_LINES = ("This weapon is out of ammo!", "You just landed a HEADSHOT!")
_ARMED_BUYS = ("Rifle", "Shotgun", "Machine Gun Bow", "Devastator Bow")


def _is_armed_signal(msg: str) -> bool:
    if msg in _ARMED_LINES:
        return True
    if msg.startswith("You purchased "):
        item = msg[len("You purchased "):]
        return any(item.startswith(b) for b in _ARMED_BUYS)
    return False


def _resolve_slice(index: int, slice_: list[Event], you: str,
                   locraw: Optional[dict], replay_game: bool,
                   party: frozenset, lobby_cap: Optional[int] = None) -> Game:
    # The decisive replay invariant: watching a replay can never produce
    # personal reward/respawn lines. If a slice flagged as replay contains
    # them, the flag is a false positive (replay ended without a marker) —
    # unflag the game and its events so a real game is never eaten.
    if replay_game and any(e.kind in _PERSONAL for e in slice_):
        replay_game = False
        for e in slice_:
            e.replay = False

    start_ev = slice_[0]
    win_ts = None
    final_death_ts = None
    your_bed_lost = False
    bed_lost_ts = None
    first_bed_by: Optional[str] = None
    death_cause: Optional[str] = None
    summary_players: list[str] = []
    who_players: set[str] = set()
    seen_players: set[str] = set()   # everyone who actually appeared this game
    who_max = 0
    colors: set[str] = set()
    n_elims = 0
    last_action_ts = None
    resolution_idx: Optional[int] = None
    armed = False                       # Armed dream-mode chat fingerprints
    final_dead: set[str] = set()        # everyone final-killed this game
    final_kills: list[tuple] = []       # (ts, victim) in order

    _ACTION = {Kind.KILL, Kind.BED, Kind.TEAM_ELIM, Kind.WIN,
               Kind.RESPAWN, Kind.RESPAWNED}

    for i, e in enumerate(slice_):
        if e.replay and not replay_game:
            continue   # replay chatter inside a real game's slice: not signal
        if e.kind in _ACTION:
            last_action_ts = e.ts
        if not armed and _is_armed_signal(e.msg):
            armed = True
        if e.kind is Kind.KILL and e.final and e.victim:
            final_dead.add(e.victim)
            final_kills.append((e.ts, e.victim))
        if e.kind is Kind.WIN and win_ts is None:
            win_ts = e.ts
            if resolution_idx is None:
                resolution_idx = i
        elif (e.kind is Kind.KILL and e.victim == you and e.final
              and final_death_ts is None):     # first only — replays re-show it
            final_death_ts = e.ts
            death_cause = _death_cause(e.msg, e.environmental)
            if resolution_idx is None:
                resolution_idx = i
        elif e.kind is Kind.BED and e.your_bed:
            your_bed_lost = True
            if bed_lost_ts is None:
                bed_lost_ts = e.ts
        if e.kind is Kind.BED and first_bed_by is None and not e.your_bed:
            # first bed to fall in the game, and who took it
            first_bed_by = e.killer or ""
        elif e.kind is Kind.WHO and e.players:
            who_players.update(e.players)
            seen_players.update(e.players)
            who_max = max(who_max, len(e.players))
        elif (e.kind is Kind.SUMMARY and e.players and you in e.players
              and not summary_players):
            summary_players = [p for p in e.players if p != you]
        if e.kind is Kind.KILL:            # kill-feed participants really played
            if e.victim:
                seen_players.add(e.victim)
            if e.killer:
                seen_players.add(e.killer)
        if e.kind is Kind.TEAM_ELIM:
            n_elims += 1
        if e.color:
            colors.add(e.color)

    if locraw:
        mode = _mode_name(locraw.get("mode", ""))
        game_map = locraw.get("map")
    else:
        mode = _game_mode_heuristic(lobby_cap, colors, who_max, n_elims,
                                    len(summary_players))
        game_map = None
        # Dream-mode rescue: with no locraw, an Armed game is indistinguishable
        # by lobby cap (16, same as Doubles/Fours) — but its guns leave
        # unmistakable chat ("This weapon is out of ammo!", HEADSHOT!, Rifle
        # buys; observed 2026-07-19). The suffix keeps dream games out of real
        # stats (the viewer excludes any "(...)" dream-suffixed mode).
        if armed:
            mode = f"{mode} (Armed)"

    # A dream mode announces itself by name in place of the normal banner (see
    # classify._DREAM_START). That is stronger evidence than any heuristic, and
    # it works without /locraw — so it is applied last and to both branches.
    # Only when nothing already suffixed the mode, so locraw's own
    # "Fours (Ultimate)" isn't doubled up.
    dream = slice_[0].data.get("dream") if slice_ and slice_[0].data else None
    if dream and "(" not in mode:
        mode = f"{mode} ({dream})"

    teammates = _teammates(mode, summary_players, party, who_players,
                           seen_players, you)

    if win_ts is not None:
        outcome = Outcome.WIN
        end_ts = win_ts
    elif final_death_ts is not None:
        outcome = Outcome.FINAL_DEATH
        end_ts = final_death_ts       # you leave when you die; spectator kills
    else:                             # after that would otherwise inflate length
        outcome = Outcome.UNRESOLVED
        end_ts = last_action_ts or slice_[-1].ts
        # Outcome fallback: a full enemy wipe proves the win even when the log
        # cut off before the VICTORY line. Requires a /who roster (a
        # well-defined opponent set), every opponent final-dead, and you or a
        # teammate still alive. (The mirror-image loss rule needs no fallback:
        # your own final death already resolves a loss unless a later Win
        # shows the teammate clutched it.)
        team = {you} | set(teammates)
        opponents = (who_players - team) if who_players else set()
        if opponents and opponents <= final_dead and (team - final_dead):
            outcome = Outcome.WIN
            opp_ts = [ts for ts, victim in final_kills if victim in opponents]
            if opp_ts:
                end_ts = opp_ts[-1]

    return Game(
        index=index,
        start_line=start_ev.line_no,
        start_ts=start_ev.ts,
        end_ts=end_ts,
        outcome=outcome,
        events=slice_,
        your_bed_lost=your_bed_lost,
        bed_lost_ts=bed_lost_ts,
        win_ts=win_ts,
        final_death_ts=final_death_ts,
        date=start_ev.date,
        teammates=teammates,
        # PREMADE, not "had a teammate": at least one of them was in your party
        # before the game started. See Game.party.
        party=bool(set(teammates) & set(party)),
        first_bed=bool(first_bed_by) and first_bed_by == you,
        death_cause=death_cause,
        mode=mode,
        map=game_map,
        replay=replay_game,
        resolution_idx=resolution_idx,
    )


@dataclass
class GameStats:
    """Per-game counts, taken from the stats window (see game_stats)."""

    your_kills: int
    your_final_kills: int
    your_deaths: int
    your_final_deaths: int
    beds_broken: int
    bed_lost: bool
    prot_level: int = 0        # highest Reinforced Armor tier bought (0-4)
    upgrades: int = 0          # team upgrades purchased
    est_diamonds: int = 0      # estimated diamonds spent (documented table)
    items: dict = field(default_factory=dict)  # misc-item buys, category -> n
    # WHICH team upgrades were bought, not just how many. `upgrades` is a
    # count, which can't answer "does Haste actually win games" — the question
    # the Upgrades breakdown exists for.
    upgrade_names: list = field(default_factory=list)
    # Final kills by you OR a teammate, so "how much of the team's work was
    # mine" is answerable. Your own share alone can't distinguish carrying a
    # duo from being carried by one.
    team_final_kills: int = 0
    # Seconds from the game starting to your team's FIRST upgrade purchase,
    # or None if nobody bought one. A proxy for how fast the team got its
    # economy going.
    first_upgrade_s: Optional[int] = None
    # EVERY death you took this game, by cause — not just the final one.
    # Final deaths are how you lose; all deaths are how you play. Measured on
    # the real corpus the two look nothing alike: 84% of final deaths are
    # direct player kills, but across all deaths ~23% are self-inflicted void
    # falls, which is the actually coachable number.
    death_causes: dict = field(default_factory=dict)
    # Diamond generator pickups you made, and how long the first one took.
    # Diamonds gate every team upgrade, so this is the upstream cause of the
    # upgrade timings above.
    diamond_pickups: int = 0
    first_diamond_s: Optional[int] = None


# Team upgrades and their (approximate, current-era) diamond costs. Estimates —
# Hypixel has rebalanced these over the years; used only for the experimental
# upgrades panel, never for core stats.
_UPGRADE_COSTS = {
    "Sharpened Swords": 8,
    "Reinforced Armor I": 5, "Reinforced Armor II": 10,
    "Reinforced Armor III": 20, "Reinforced Armor IV": 30,
    "Maniac Miner I": 4, "Maniac Miner II": 6,
    "Iron Forge": 4, "Golden Forge": 8, "Emerald Forge": 12, "Molten Forge": 16,
    "Heal Pool": 3, "Dragon Buff": 5,
    "It's a trap!": 1, "Counter-Offensive Trap": 2,
    "Alarm Trap": 2, "Miner Fatigue Trap": 2,
}
_PROT = {"Reinforced Armor I": 1, "Reinforced Armor II": 2,
         "Reinforced Armor III": 3, "Reinforced Armor IV": 4}

# Misc-item tracking ("do potions/pearls/... actually help win games?").
# Matchers are anchored to the EXACT shop strings observed in 19 months of
# real logs (e.g. "Jump V Potion (45 seconds)", "Stick (Knockback I)",
# "Permanent Diamond Armor", "Bow (Power I, Punch I)", "Water Bucket").
# The seasonal "(+1 Silver Coin [500])" suffix is stripped before matching.
_COIN_SUFFIX = re.compile(r"\s*\(\+\d+ Silver Coin \[\d+\]\)$")
# Order matters: FIRST match wins, so specific patterns precede general ones
# (the three potions before any generic potion rule).
#
# Expanded 2026-08-01 after surveying every "You purchased" line in 19 months
# of real logs. The previous list tracked 7 categories and missed the two most
# bought items outright: Fireball (4,451 purchases) and Golden Apple (4,259).
# Potions were also lumped into one bucket, which made "do potions win games"
# unanswerable — jump, invis and speed are completely different decisions.
# Anything under ~50 purchases in the whole corpus is deliberately left out:
# a row with no sample is worse than no row.
_ITEM_CATEGORIES = (
    # potions, split — checked before any generic rule
    ("jump_potion",  lambda n: n.startswith("Jump ") and " Potion" in n),
    ("invis_potion", lambda n: n.startswith("Invisibility Potion")),
    ("speed_potion", lambda n: n.startswith("Speed ") and " Potion" in n),
    ("fireball",  lambda n: n == "Fireball"),
    ("gapple",    lambda n: n.startswith("Golden Apple")),
    ("bridge_egg", lambda n: n.startswith("Bridge Egg")),
    ("obsidian",  lambda n: n.startswith("Obsidian")),
    ("tnt",       lambda n: n == "TNT"),
    ("magic_milk", lambda n: n.startswith("Magic Milk")),
    # defensive gadgets, one bucket — individually too rare to read
    ("utility",   lambda n: n.startswith(("Bedbug", "Dream Defender",
                                          "Compact Pop-up Tower"))),
    ("kb_stick",  lambda n: n.startswith("Stick (Knockback")),
    ("pearl",     lambda n: n.startswith("Ender Pearl")),
    ("chain_armor", lambda n: n.startswith("Permanent Chainmail Armor")),
    ("iron_armor", lambda n: n.startswith("Permanent Iron Armor")),
    ("dia_armor", lambda n: n.startswith("Permanent Diamond Armor")),
    ("dia_sword", lambda n: n.startswith("Diamond Sword")),
    ("bow",       lambda n: n == "Bow" or n.startswith("Bow (") or n.endswith(" Bow")),
    ("water",     lambda n: n.startswith("Water Bucket")),
)


def categorize_item(item: str) -> Optional[str]:
    """Map a personal shop purchase to a tracked category, or None."""
    name = _COIN_SUFFIX.sub("", item).strip()
    for cat, match in _ITEM_CATEGORIES:
        if match(name):
            return cat
    return None


# Diamond pickups: Hypixel pays XP per pickup, one line each.
_DIAMOND_PICKUP = re.compile(r"^\+\d+ Bed Wars XP \(Diamonds\)$")


def _death_cause(msg: str, environmental: bool) -> str:
    """How you died, from the two signals that DON'T rot.

    Death messages are cosmetics and Hypixel keeps adding them: measured on a
    real 9,000-death corpus there are 961 distinct verb phrases, 832 of them
    seen exactly once, and 10% of recent deaths used a phrase that had never
    appeared before. So this deliberately reads only:

      * the literal word "void" — Hypixel's name for the MECHANIC, not flavour
        text, and it survives new cosmetics
      * whether the line named a killer — pure structure, straight out of the
        roster invariant (see classify), no verb parsing at all

    That classifies 98.2% of real deaths. A finer split (melee vs projectile vs
    fire) is NOT attempted and should not be added: 18% of deaths are the bare
    "was killed by X" default, which carries no cause information, and cosmetic
    flavour doesn't map to mechanics ("glazed in BBQ sauce" — fireball? lava?).
    Guessing there would print speculation as a statistic.
    """
    if "void" in msg.lower():
        return "void_self" if environmental else "void_knocked"
    if not environmental:
        return "player"
    return "other"


def _seconds_between(a: Optional[str], b: Optional[str]) -> Optional[int]:
    """Seconds from time-of-day ``a`` to ``b``, wrapping once past midnight."""
    if not a or not b:
        return None
    try:
        ha, ma, sa = (int(x) for x in a.split(":"))
        hb, mb, sb = (int(x) for x in b.split(":"))
    except ValueError:
        return None
    d = (hb * 3600 + mb * 60 + sb) - (ha * 3600 + ma * 60 + sa)
    return d + 86400 if d < 0 else d


def game_stats(game: Game, you: str) -> GameStats:
    """Counts over the *stats window*: events up to the game's resolution
    (win / your final death), excluding anything marked as replay chatter.
    Kill-feed lines after you win or die (spectating, replays, the next lobby)
    are not yours — this is what made a 38-final-kill game possible before."""
    idx = game.resolution_idx
    window = game.events if idx is None else game.events[:idx + 1]
    ev = [e for e in window if not e.replay or game.replay]

    def kills(pred):
        return sum(1 for e in ev if e.kind is Kind.KILL and pred(e))

    # Final kills the whole team got. Teammate detection is mode-gated and
    # already excludes Solos, where this is just your own count.
    diamond_ts = [e.ts for e in ev if _DIAMOND_PICKUP.match(e.msg.strip())]

    causes: dict = {}
    for e in ev:
        if e.kind is Kind.KILL and e.victim == you:
            c = _death_cause(e.msg, e.environmental)
            causes[c] = causes.get(c, 0) + 1

    team = set(game.teammates) | {you}
    team_finals = sum(1 for e in ev
                      if e.kind is Kind.KILL and e.final and e.killer in team)

    # Beds you broke, counted from the BED DESTRUCTION feed rather than from a
    # reward line — same reasoning as the kill invariant, and for a concrete
    # reason: the payout for a bed comes as tokens + Slumber Tickets + Bed Wars
    # XP, and Hypixel drops the ticket line when your pouch is full (or just
    # doesn't send it — 2026-07-21 has a bed with tokens and XP but no ticket).
    # Anchoring on tickets recorded 0 beds for a whole alt account and undercounted
    # the main; the feed line is always there. Counting all three currencies
    # instead would treble the number, which is why they aren't counted at all.
    def beds_you_broke() -> int:
        return sum(1 for e in ev
                   if e.kind is Kind.BED and e.killer == you and not e.your_bed)

    # Team upgrades are broadcast to the whole team as "<name> purchased <up>"
    # (a teammate buying Reinforced Armor upgrades everyone), so match the
    # purchase from anyone — prot/forge are team-wide. Personal item buys
    # ("You purchased Wool") aren't in the cost table, so they're ignored.
    prot = 0
    upgrades = 0
    diamonds = 0
    items: dict = {}
    upgrade_names: list = []
    first_upgrade_ts: Optional[str] = None
    seen_once = set()   # a team upgrade is announced once; dedupe re-broadcasts
    for e in ev:
        m = _PURCHASE.match(e.msg)
        if not m:
            continue
        item = m.group(1).strip()
        if item in _UPGRADE_COSTS and item not in seen_once:
            seen_once.add(item)
            upgrades += 1
            diamonds += _UPGRADE_COSTS[item]
            upgrade_names.append(item)
            if first_upgrade_ts is None:
                first_upgrade_ts = e.ts
            prot = max(prot, _PROT.get(item, 0))
        # Personal misc-item buys are only ever announced as "You purchased".
        if e.msg.startswith("You purchased "):
            cat = categorize_item(item)
            if cat:
                items[cat] = items.get(cat, 0) + 1

    return GameStats(
        your_kills=kills(lambda e: e.killer == you and not e.final),
        your_final_kills=kills(lambda e: e.killer == you and e.final),
        your_deaths=kills(lambda e: e.victim == you and not e.final),
        your_final_deaths=kills(lambda e: e.victim == you and e.final),
        beds_broken=beds_you_broke(),
        bed_lost=game.your_bed_lost,
        prot_level=prot,
        upgrades=upgrades,
        est_diamonds=diamonds,
        items=items,
        upgrade_names=sorted(upgrade_names),
        team_final_kills=team_finals,
        first_upgrade_s=_seconds_between(game.start_ts, first_upgrade_ts),
        death_causes=causes,
        diamond_pickups=len(diamond_ts),
        first_diamond_s=_seconds_between(game.start_ts,
                                         diamond_ts[0] if diamond_ts else None),
    )


def game_roster(game: Game, you: str) -> list[tuple[str, bool, bool]]:
    """(ign, is_you, is_teammate) for the players in this game.

    ``/who`` is authoritative — it lists exactly this game's players. Lobby
    ``JOIN`` lines are *not* used when a /who exists, because the joins for the
    next game print in the lobby *after* this game starts and therefore land in
    this game's slice. Joins are only a fallback for a game with no /who.
    """
    mates = set(game.teammates)
    names: dict[str, bool] = {}
    for e in game.events:
        if e.kind is Kind.WHO and e.players and not e.replay:
            for ign in e.players:
                names.setdefault(ign, ign == you)
    if not names:
        for e in game.events:
            if e.kind is Kind.JOIN and e.ign:
                names.setdefault(e.ign, e.ign == you)
    return [(ign, is_you, ign in mates) for ign, is_you in names.items()]


@dataclass
class Stats:
    """Session roll-up. Reward-based and roster-based counts are computed by
    independent code paths so they cross-check each other (reference §3)."""

    you: str
    games: int
    wins: int
    final_deaths: int
    unresolved: int
    # roster-parsed (from the kill invariant)
    your_final_kills: int
    your_final_deaths: int
    your_kills: int
    your_regular_deaths: int
    # reward-line based (literal "(...)" tags — a separate signal)
    reward_final_kills: int
    reward_kills: int
    reward_beds: int
    respawn_deaths: int
    your_beds_lost: int
    unparsed: int
    span: str


def summarize(events: list[Event], games: list[Game], you: str) -> Stats:
    def kills(pred) -> int:
        return sum(1 for e in events if e.kind is Kind.KILL and pred(e))

    times = [e.ts for e in events]
    span = f"{times[0]} → {times[-1]}" if times else "-"

    return Stats(
        you=you,
        games=len(games),
        wins=sum(1 for g in games if g.outcome is Outcome.WIN),
        final_deaths=sum(1 for g in games if g.outcome is Outcome.FINAL_DEATH),
        unresolved=sum(1 for g in games if g.outcome is Outcome.UNRESOLVED),
        your_final_kills=kills(lambda e: e.killer == you and e.final),
        your_final_deaths=kills(lambda e: e.victim == you and e.final),
        your_kills=kills(lambda e: e.killer == you and not e.final),
        your_regular_deaths=kills(lambda e: e.victim == you and not e.final),
        reward_final_kills=sum(1 for e in events if e.reward == "final_kill"),
        reward_kills=sum(1 for e in events if e.reward == "kill"),
        reward_beds=sum(1 for e in events if e.reward == "bed"),
        # respawn countdown fires once per second — dedupe on the "5"
        respawn_deaths=sum(1 for e in events if e.kind is Kind.RESPAWN and e.respawn_secs == 5),
        your_beds_lost=sum(1 for e in events if e.kind is Kind.BED and e.your_bed),
        unparsed=sum(1 for e in events if e.kind is Kind.UNPARSED),
        span=span,
    )
