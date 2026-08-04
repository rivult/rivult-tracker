"""Line classifier.

Turns raw log lines into typed :class:`Event`s.  The load-bearing idea
(reference §2) is that kill messages are *cosmetics* — there is no stable
verb or sentence shape — so we never regex the kill text.  Instead:

    victim = the first roster name in the line, killer = the last.

Everything hangs off a roster of player names, built primarily from the
``/who`` response and folded together from several sources (see
:func:`build_roster`).
"""

from __future__ import annotations

import json
import re
from typing import Iterable, Optional

from .events import Event, Kind

# --- line shape -------------------------------------------------------------

# Full prefix, not just "[CHAT]": other threads (mod updaters, netty) also emit
# [CHAT] lines and must be filtered out (reference §1).
_PREFIX = re.compile(r"^\[(\d\d:\d\d:\d\d)\] \[Client thread/INFO\]: \[CHAT\] (.*)$")

# Minecraft colour codes are the byte 0xA7 ('§') + one char. Read the file as
# latin-1 so 0xA7 survives as '\xa7', then strip "§x" before reasoning.
_COLOR = re.compile("\xa7.", re.DOTALL)

# Self-identity: "[HH:MM:SS] [Client thread/INFO]: Setting user: <ign>"
_SETTING_USER = re.compile(r"Setting user: ([A-Za-z0-9_]{1,16})")

_IGN = r"[A-Za-z0-9_]{1,16}"

# --- event anchors (checked in priority order) ------------------------------

_JOIN = re.compile(rf"^({_IGN}) has joined \((\d+)/(\d+)\)!")
_QUIT = re.compile(rf"^({_IGN}) has quit!")
# Bed verbs are cosmetics like kill verbs (reference §3): anchor on the
# "BED DESTRUCTION > <X> Bed" frame only. The strict " by <name>" variant is
# kept for roster harvesting (never guess a name into the roster); the event
# itself must match even for by-less cosmetics ("...had to raise the white
# flag to X!"), or your_bed goes undetected and clutch stats drift.
_BED = re.compile(r"^BED DESTRUCTION > (.+? Bed)\b(.*)$")
_BED_STRICT = re.compile(r"^BED DESTRUCTION > .+? Bed was .* by (" + _IGN + r")[.!]?$")
_TRAILING_NAME = re.compile(rf"({_IGN})[.!]*$")
_ELIM = re.compile(r"^TEAM ELIMINATED > (\w+) Team has been eliminated!")
_RESPAWN = re.compile(r"^You will respawn in (\d+) seconds?!")

# --- extra roster-harvest frames (reliable player-name slots only) ----------
# Joins alone miss anyone already in the lobby when you arrive (Hypixel only
# announces players who join *after* you). So we also harvest names from the
# kill feed — but only from slots that are always a player IGN, never a generic
# word: the killstreak victim/killer, and the leading victim + trailing killer
# of a "... by <ign>." line. We deliberately do NOT harvest the last word of
# preposition-less deaths ("X fell into the void.") — that would poison the
# roster with words like "void".
_STREAK = re.compile(rf"^({_IGN}) was ({_IGN})'s final #")
_BY_KILL = re.compile(rf"^({_IGN}) .* by ({_IGN})\.(?: FINAL KILL!)?$")
_PODIUM = re.compile(rf"^\d+(?:st|nd|rd|th) Killer - ({_IGN}) -")

# `/who` response: "ONLINE: a, b, c, ...". The single most reliable roster
# source — it lists *every* player in the game, including anyone already
# seated before you joined (whom "has joined" never announces). Because the
# roster is built in a whole-session first pass, it does not matter whether
# /who was run at the start or the middle of a game.
_WHO = re.compile(r"^ONLINE: (.+)$")
_WHO_NAME = re.compile(rf"\b({_IGN})\b")

# A player chat line (reference §5): optional [SHOUT], optional Party/Guild
# routing, any number of [rank]/[team]/[star] tags, then IGN, then a colon.
# The colon right after the name prefix is the reliable tell.
_CHAT = re.compile(
    r"^(?:\[SHOUT\]\s*)?"
    r"(?:(?:Party|Guild|Co-op)\s*>\s*)?"
    r"(?:\[[^\]]*\]\s*)*"
    rf"{_IGN}\s*:\s"
)

# Shout chat carries the speaker's team tag ("[SHOUT] [WHITE] [MVP+] x: hi") —
# free team-colour evidence (reference §5). 8-team modes (Solos/Doubles) use
# all eight colours; 4-team modes (Trios/Fours) only Red/Blue/Green/Yellow, so
# seeing Aqua/White/Pink/Gray proves an 8-team mode.
_CHAT_TEAM = re.compile(
    r"^(?:\[SHOUT\]\s*)?\[(RED|BLUE|GREEN|YELLOW|AQUA|WHITE|PINK|GR[AE]Y)\]")

_GAME_START = "Protect your bed and destroy the enemy beds"

# Dream modes (Ultimate, Swappage, Lucky Blocks, ...) replace that banner with
# their own name on a bare line, in the same slot right after the countdown:
#
#     The game starts in 1 second!
#     ────────────────────────────
#     Bed Wars Ultimate                 <- here
#     Select an ultimate in the store!
#
# Without this they produce no game at all, so keybinds and auto-commands have
# nothing to act on during one. The mode name is captured and carried on the
# event so `resolve` can suffix the mode "Fours (Ultimate)" — the viewer
# excludes any parenthesised mode, so a dream game is visible and taggable but
# never counted as a normal game.
#
# Measured against all 921 local logs: this matches 2 lines, both real dream
# starts ("Bed Wars Ultimate"). The 3,628 bare "Bed Wars" header lines need a
# following word so they don't match, and "Bed Wars Duels" (25) is a Duels
# gametype, not Bed Wars, hence the negative lookahead.
_DREAM_START = re.compile(
    r"^Bed Wars (?!Duels\b)([A-Z][A-Za-z]*(?: [A-Z][A-Za-z]*)*)$")

# --- personal reward lines: "+N <currency> (<tag>)" -------------------------
# Every one of these is addressed to YOU, which is what makes them usable for
# identity detection. Hypixel pays the same action out in several currencies
# and WHICH ones it prints depends on account state — a full Slumber pouch
# replaces "+2 Slumber Tickets (Kill)" with "+0 Slumber Tickets! (Full)",
# leaving a plain kill with no ticket line at all. That is why the currency is
# not part of the match: an alt with a full pouch used to produce zero personal
# signals, so nobody could be identified, its games were unscoreable, and its
# losses were invisible.
_REWARD_LINE = re.compile(
    r"^\+\d+ (?:Slumber Tickets!?|tokens!|Bed Wars XP) \((.+)\)$")


def self_signal(msg: str) -> Optional[str]:
    """Which of *your* actions a personal reward line paid out for.

    ``'final_kill'`` / ``'kill'`` / ``'bed'``, else None. Identity detection
    only (:func:`parse.detect_self`) — never counted, because one action pays
    out in up to three currencies and counting them all would treble the
    reward cross-check. The COUNTED rewards stay Slumber-anchored in
    :func:`_classify_one`.
    """
    m = _REWARD_LINE.match(msg)
    if not m:
        return None
    tag = m.group(1)
    # order matters: "First Kill + Final Kill" is a final kill
    if "Final Kill" in tag:
        return "final_kill"
    if "Bed Destroyed" in tag or "Bed Break" in tag:
        return "bed"
    if "Kill" in tag:            # "Kill", "First Kill"
        return "kill"
    return None

# The /locraw response — Hypixel prints exactly where you are as JSON:
#   {"server":"mini36CK","gametype":"BEDWARS","mode":"BEDWARS_EIGHT_TWO","map":"Dragon Light"}
# This is the authoritative gametype/mode/map signal, and `"gametype":"REPLAY"`
# is how we know the following chat is a replay being watched, not a real game.
_LOCRAW = re.compile(r'^\{"server":.*\}$')

# Party system lines (confirmed against real logs):
#   You have joined [MVP+] j7zltYogM's party!
#   [MVP+] j7zltYogM joined the party.
#   [VIP] q9moKcHmCqse left the party.
#   You left the party.  /  ... has disbanded the party!
#   Party Members: [VIP] rivult ● [MVP+] j7zltYogM ●
_P_JOIN_YOU = re.compile(rf"^You have joined (?:\[[^\]]*\]\s*)?({_IGN})'s party!")
_P_JOIN = re.compile(rf"^(?:\[[^\]]*\]\s*)?({_IGN}) joined the party\.")
_P_LEAVE = re.compile(rf"^(?:\[[^\]]*\]\s*)?({_IGN}) (?:left the party|has left the party|has been removed from the party)")
_P_CLEAR = re.compile(r"^(You left the party|The party was disbanded"
                      r"|.*has disbanded the party!|You are not currently in a party)")
# Colon REQUIRED: the summon line ("Party Leader, [MVP+] X, summoned you to
# their server.") is comma-form and used to match here, leaking "summoned"
# and "server" into party members (found in the 2026-07-18 capture sweep).
_P_MEMBERS = re.compile(r"^Party (?:Members|Leader|Moderators)(?: \(\d+\))?: ?(.*)$")
_P_SUMMON = re.compile(rf"^Party Leader, (?:\[[^\]]*\]\s*)?({_IGN}), summoned you")
_P_CHAT = re.compile(rf"^Party > (?:\[[^\]]*\]\s*)*({_IGN})\s*:\s")

# End-game placement line: "<Color> - [rank] name, [rank] name". The 1st-place
# line is the winning team; the one containing you gives your teammates (party
# detection — reference §7). Colours are the 8 BedWars team colours.
_COLORS = "Red|Blue|Green|Yellow|Aqua|White|Pink|Gray|Grey"
_SUMMARY = re.compile(rf"^({_COLORS}) - (.+)$")
# One roster entry: an optional "[rank]" tag then the IGN, anchored to the whole
# comma-separated part. Anchoring is what stops a *bare* trailing rank (the line
# truncates in 4v4, ending "…, [MVP+]") from yielding "MVP" as a fake name — the
# part has no IGN after the tag, so it simply doesn't match.
_SUMMARY_PART = re.compile(rf"^\s*(?:\[[^\]]*\]\s*)?({_IGN})\s*$")


def _summary_names(rest: str) -> list:
    names = []
    for part in rest.split(","):
        m = _SUMMARY_PART.match(part)
        if m:
            names.append(m.group(1))
    return names


def strip_colors(s: str) -> str:
    return _COLOR.sub("", s)


def detect_you(raw_lines: Iterable[str]) -> Optional[str]:
    """Find the local player's IGN from the client's "Setting user:" line."""
    for line in raw_lines:
        if "[CHAT]" in line:
            continue
        m = _SETTING_USER.search(line)
        if m:
            return m.group(1)
    return None


def build_roster(raw_lines: Iterable[str], you: Optional[str] = None) -> set[str]:
    """First pass: collect every player IGN seen this session.

    Accumulated across the whole session — a name only appears in a kill line
    for a game it was actually in, so a session-wide roster never fabricates a
    cross-game match, and every player is known before any line is classified
    (so a mid-game /who works just as well as one at the start).

    Sources, in rough order of completeness, all of which are *always* a player
    IGN and never a generic word:

    * ``/who`` — "ONLINE: a, b, c" lists the whole game (the reliable one)
    * "<ign> has joined" / "<ign> has quit"
    * the killstreak frame "<victim> was <killer>'s final #"
    * the "... by <killer>." kill frame (leading victim + trailing killer)
    * bed-destruction "... by <ign>" and the killer podium
    """
    roster: set[str] = set()
    if you:
        roster.add(you)
    for line in raw_lines:
        m = _PREFIX.match(line)
        if not m:
            continue
        msg = strip_colors(m.group(2)).strip()

        w = _WHO.match(msg)
        if w:
            roster.update(_WHO_NAME.findall(w.group(1)))
            continue

        for rx in (_JOIN, _QUIT, _PODIUM):
            hit = rx.match(msg)
            if hit:
                roster.add(hit.group(1))
        for rx in (_STREAK, _BY_KILL):
            hit = rx.match(msg)
            if hit:
                roster.add(hit.group(1))
                roster.add(hit.group(2))
        b = _BED_STRICT.match(msg)
        if b:
            roster.add(b.group(1))
    return roster


def _roster_regex(roster: set[str]) -> Optional[re.Pattern]:
    if not roster:
        return None
    # Longest name first so "rivult2" wins over "rivult" at the same position
    # (IGN substring collisions are real — reference §2). Word boundaries use
    # the IGN charset, not \b, because '_' and digits are name characters.
    names = sorted(roster, key=len, reverse=True)
    alt = "|".join(re.escape(n) for n in names)
    return re.compile(rf"(?<![A-Za-z0-9_])({alt})(?![A-Za-z0-9_])")


def classify_lines(raw_lines: list[str], you: str) -> list[Event]:
    """Second pass: every ``[CHAT]`` line → one typed :class:`Event`."""
    roster = build_roster(raw_lines, you)
    roster_re = _roster_regex(roster)
    events: list[Event] = []

    for i, raw in enumerate(raw_lines, start=1):
        pm = _PREFIX.match(raw)
        if not pm:
            continue  # not a game chat line (mod spam, non-CHAT log output)
        ts, payload = pm.group(1), pm.group(2)
        msg = strip_colors(payload).strip()
        ev = _classify_one(i, ts, raw, msg, you, roster_re)
        events.append(ev)
    return events


def _classify_one(
    line_no: int, ts: str, raw: str, msg: str, you: str, roster_re
) -> Event:
    def mk(kind: Kind, **kw) -> Event:
        return Event(line_no=line_no, ts=ts, kind=kind, raw=raw, msg=msg, **kw)

    # --- structural anchors first -----------------------------------------
    m = _JOIN.match(msg)
    if m:
        return mk(Kind.JOIN, ign=m.group(1),
                  lobby_count=int(m.group(2)), lobby_cap=int(m.group(3)))

    m = _QUIT.match(msg)
    if m:
        return mk(Kind.QUIT, ign=m.group(1))

    if _GAME_START in msg:
        return mk(Kind.GAME_START)

    m = _DREAM_START.match(msg)
    if m:
        return mk(Kind.GAME_START, data={"dream": m.group(1)})

    if _LOCRAW.match(msg):
        try:
            return mk(Kind.LOCRAW, data=json.loads(msg))
        except ValueError:
            return mk(Kind.UNPARSED)

    # party membership (checked before chat exclusion; these have no colon-chat shape)
    m = _P_JOIN_YOU.match(msg)
    if m:
        return mk(Kind.PARTY, ign=m.group(1), data={"action": "join"})
    m = _P_JOIN.match(msg)
    if m:
        return mk(Kind.PARTY, ign=m.group(1), data={"action": "join"})
    # clear BEFORE leave: "You left the party." is a clear, but would otherwise
    # match _P_LEAVE as player "You" leaving (and never clear the party)
    if _P_CLEAR.match(msg):
        return mk(Kind.PARTY, data={"action": "clear"})
    m = _P_LEAVE.match(msg)
    if m:
        return mk(Kind.PARTY, ign=m.group(1), data={"action": "leave"})
    m = _P_SUMMON.match(msg)
    if m:    # being summoned proves the leader is in your party
        return mk(Kind.PARTY, ign=m.group(1), data={"action": "join"})
    m = _P_MEMBERS.match(msg)
    if m:
        names = [n for _, n in
                 (p.groups() for p in re.finditer(rf"(\[[^\]]*\]\s*)?({_IGN})", m.group(1)))]
        if names:
            return mk(Kind.PARTY, players=names, data={"action": "members"})

    w = _WHO.match(msg)
    if w:
        return mk(Kind.WHO, players=_WHO_NAME.findall(w.group(1)))

    m = _BED.match(msg)
    if m:
        subject = m.group(1)
        t = _TRAILING_NAME.search(m.group(2))
        return mk(Kind.BED, killer=t.group(1) if t else None,
                  your_bed=(subject == "Your Bed"),
                  color=None if subject == "Your Bed" else subject[:-4])

    m = _ELIM.match(msg)
    if m:
        return mk(Kind.TEAM_ELIM, color=m.group(1))

    m = _SUMMARY.match(msg)
    if m:
        return mk(Kind.SUMMARY, color=m.group(1),
                  players=_summary_names(m.group(2)))

    # --- your reward lines (independent cross-check on the roster parse) ---
    # A win is tagged "(Win)" on several reward lines; any one is enough (the
    # resolver dedupes per game). The COUNTED kill/final/bed rewards must stay
    # anchored on "Slumber Tickets" — the same tags also appear on "+N tokens!"
    # and "+N Bed Wars XP" breakdown lines, which would otherwise double-count.
    # `self_signal` carries the same information WITHOUT being counted, so
    # identity detection can use every currency (see self_signal()).
    sig = self_signal(msg)
    if "(Win)" in msg:
        return mk(Kind.WIN, reward="win")
    if "Slumber Tickets" in msg:
        if "(Final Kill)" in msg:
            return mk(Kind.REWARD, reward="final_kill", self_signal=sig)
        if "(Bed Destroyed)" in msg:
            return mk(Kind.REWARD, reward="bed", self_signal=sig)
        if "(Kill)" in msg:
            return mk(Kind.REWARD, reward="kill", self_signal=sig)

    m = _RESPAWN.match(msg)
    if m:
        return mk(Kind.RESPAWN, respawn_secs=int(m.group(1)))
    if msg.startswith("You have respawned!"):
        return mk(Kind.RESPAWNED)

    # --- exclude player chat BEFORE scanning for names (reference §5) ------
    if _CHAT.match(msg):
        # a "Party > name:" speaker is a live party member — capture for the
        # teammate tracker (guild/co-op chat is deliberately not captured)
        pm = _P_CHAT.match(msg)
        if pm:
            return mk(Kind.CHAT, ign=pm.group(1), data={"channel": "party"})
        tm = _CHAT_TEAM.match(msg)
        return mk(Kind.CHAT, color=tm.group(1).title() if tm else None)

    # --- roster scan: the kill invariant ----------------------------------
    # Two structural gates keep this from firing on non-kills that happen to
    # start with a player name:
    #   1. victim leads — a roster name at position 0 (kill feed lines open
    #      with the victim; summaries open with a colour, podiums with "Nth").
    #   2. death frame — the line ends "." or "FINAL KILL!". This rejects
    #      self-action spam like "rivult purchased Reinforced Armor I", which
    #      starts with your name but has no terminal period.
    is_death_frame = msg.endswith(".") or msg.endswith("FINAL KILL!")
    if is_death_frame and roster_re is not None and roster_re.match(msg):
        names = [mm.group(1) for mm in roster_re.finditer(msg)]
        killer = names[-1] if len(names) >= 2 else None
        return mk(
            Kind.KILL,
            victim=names[0],
            killer=killer,
            environmental=killer is None,
            final=msg.endswith("FINAL KILL!"),
        )

    # Kills are already handled above, so anything matching here is genuinely
    # non-combat chatter. Typing it as NOISE keeps UNPARSED meaningful: an
    # UNPARSED line is now something the parser has *never seen* — the tripwire
    # for a new kill cosmetic (reference §9 / plan Phase 4).
    if _is_noise(msg):
        # A reward breakdown line is noise for counting purposes but still
        # proves who acted, so it keeps its self_signal.
        return mk(Kind.NOISE, self_signal=sig)
    return mk(Kind.UNPARSED)


def _is_noise(msg: str) -> bool:
    if not msg:
        return True
    if msg.startswith(("You ", "Deposited ", "Rewards:")):
        return True                                   # shop / pickup / guild / status
    if msg[0] == "+" and msg[1:2].isdigit():
        return True                                   # "+17 Bed Wars XP", reward breakdown
    if "purchased" in msg or "picked up" in msg or "Cross-teaming" in msg:
        return True
    if len(msg) >= 4 and not any(c.isalnum() for c in msg):
        return True                                   # separators / box-art
    return False
