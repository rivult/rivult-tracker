"""Event and game types produced by the parser.

The classifier turns every ``[CHAT]`` line into exactly one :class:`Event`
(``UNPARSED`` if nothing else matched — we never silently drop a chat line).
The resolver folds those events into :class:`Game` rows with a terminal
:class:`Outcome`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

# Bumped whenever the classifier/resolver changes in a way that alters results.
# On startup the tracker compares this to the value stored in the DB and, if it
# differs, re-resolves every game from its stored raw lines (Phase 3).
PARSER_VERSION = 10  # v10: dream modes (Ultimate, Swappage, ...) start a game
                     # from their own banner and get a "(Name)" mode suffix.
                     # Adds games that never parsed before, so it needs a FULL
                     # REFRESH — re-resolving stored lines is not enough when
                     # the change is which lines open a game.
                     # v9: per-death causes (all deaths, not just
                     # the final one).
                     # v8: death_cause + diamond economy.
                     # Needs a FULL REFRESH.
                     # v7: team_final_kills + first_upgrade_s (new
                     # breakdowns). Needs a FULL REFRESH.
                     # v6: premade-party flag (was "had any teammate"),
                     # first-bed flag, per-upgrade names, and a much wider
                     # misc-item list (fireball/gapple/potion split/...).
                     # Needs a FULL REFRESH to backfill across history.
                     # v5: currency-agnostic self signals, so identity is
                     # detected on accounts whose Slumber pouch is full
                     # (needs a FULL REFRESH — reprocess can't rewrite
                     # games.played_as).
                     # v4: enemy-wipe WIN fallback for UNRESOLVED games +
                     # Armed-mode chat fingerprints (mode fix needs full
                     # refresh; outcome/stats repair via auto-reprocess).
                     # v3: misc-item tracking (game_stats.items) — bump makes
                     # reprocess backfill items across stored history.
                     # v2: locraw mode/map, replay exclusion, stats window,
                     # party-based teammates


class Kind(str, Enum):
    """Every classified chat line is exactly one of these."""

    GAME_START = "game_start"   # "Protect your bed and destroy the enemy beds."
    WIN = "win"                 # any reward line tagged "(Win)"
    KILL = "kill"               # roster-parsed: victim/killer (+ final flag)
    BED = "bed"                 # "BED DESTRUCTION > ..."
    TEAM_ELIM = "team_elim"     # "TEAM ELIMINATED > <Color> Team ..."
    JOIN = "join"              # "<ign> has joined (n/N)!"
    QUIT = "quit"              # "<ign> has quit!"
    WHO = "who"                 # "/who" response: "ONLINE: a, b, c, ..."
    REWARD = "reward"           # your Slumber-ticket reward lines (kill/final/bed)
    RESPAWN = "respawn"         # "You will respawn in N seconds!"
    RESPAWNED = "respawned"     # "You have respawned!"
    SUMMARY = "summary"         # end-game team line "<Color> - [rank] a, [rank] b"
    LOCRAW = "locraw"           # {"server":...,"gametype":"BEDWARS","mode":...,"map":...}
    PARTY = "party"             # party join/leave/list/disband system lines
    CHAT = "chat"               # a player chat line — excluded from roster scan
    NOISE = "noise"             # recognised non-event chatter (shop, rewards, MOTD)
    UNPARSED = "unparsed"       # a chat line we recognised as nothing above


class Outcome(str, Enum):
    """Terminal state of a game (reference §4)."""

    WIN = "WIN"                 # saw a "(Win)" reward
    FINAL_DEATH = "FINAL_DEATH"  # you were final-killed, then left
    UNRESOLVED = "UNRESOLVED"   # log ended mid-game — neither marker (crash case)


@dataclass
class Event:
    """One classified chat line.

    ``raw`` keeps the original line verbatim (colour codes and all) so history
    can be re-resolved when Hypixel ships a new cosmetic (reference §9).
    ``msg`` is the colour-stripped chat payload the classifier reasoned over.
    """

    line_no: int
    ts: str                     # "HH:MM:SS" (time only; date reconstructed later)
    kind: Kind
    raw: str
    msg: str
    # kind-specific payload (all optional)
    victim: Optional[str] = None
    killer: Optional[str] = None
    final: bool = False          # KILL: suffix "FINAL KILL!"
    environmental: bool = False  # KILL: only one name (void/fall, no killer)
    ign: Optional[str] = None    # JOIN/QUIT: the player
    lobby_count: Optional[int] = None
    lobby_cap: Optional[int] = None
    color: Optional[str] = None  # BED/TEAM_ELIM: team colour
    your_bed: bool = False       # BED: it was *your* bed
    reward: Optional[str] = None  # REWARD/WIN subtype: kill|final_kill|bed|win
    # Which of YOUR actions a personal reward line paid out for
    # (kill|final_kill|bed), in whatever currency Hypixel happened to use.
    # Identity detection ONLY (classify.self_signal / parse.detect_self) —
    # never counted, because one action pays out in up to three currencies.
    self_signal: Optional[str] = None
    respawn_secs: Optional[int] = None
    players: Optional[list] = None  # WHO: the "ONLINE: ..." roster / SUMMARY team
    date: Optional[str] = None      # ISO date, reconstructed (timestamps roll at midnight)
    data: Optional[dict] = None     # LOCRAW payload / PARTY action / chat channel
    replay: bool = False            # set by the resolver: line happened inside a replay


@dataclass
class Game:
    """One game: a slice of events between two ``GAME_START`` markers."""

    index: int                   # 1-based
    start_line: int
    start_ts: str
    end_ts: str
    outcome: Outcome
    events: list = field(default_factory=list, repr=False)
    your_bed_lost: bool = False
    bed_lost_ts: Optional[str] = None
    win_ts: Optional[str] = None
    final_death_ts: Optional[str] = None
    date: Optional[str] = None            # ISO date of the game (start event)
    teammates: list = field(default_factory=list)  # party members + summary team
    # You PREMADE with someone: at least one teammate was in your party, as
    # opposed to a random the matchmaker handed you. This used to be
    # `bool(teammates)`, which in Doubles is true for almost every game
    # (a random duo mate is still a teammate) — so the "Partied vs Solo-queue"
    # breakdown put ~85% of games in "Partied" and answered nothing.
    party: bool = False
    # The FIRST bed destroyed in the game was destroyed by you. Cheap to
    # capture here and impossible to reconstruct later from the stored slice
    # alone; feeds the "did drawing first blood win it" breakdown.
    first_bed: bool = False
    # How your final death happened: void_self | void_knocked | player | other.
    # None when you didn't die (a win, or the log cut off). See
    # resolve._death_cause for why only these four exist.
    death_cause: Optional[str] = None
    mode: str = "Unknown"                 # Solos/Doubles/Trios/4v4/Practice/...
    map: Optional[str] = None             # from locraw, when available
    replay: bool = False                  # game slice started inside a replay
    resolution_idx: Optional[int] = None  # index (into events) of the win/death;
                                          # stats only count up to here — kills
                                          # seen while spectating or in a replay
                                          # after this point are not yours
