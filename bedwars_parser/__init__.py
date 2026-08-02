"""A Hypixel BedWars log parser built on the roster-invariant approach.

See ``bedwars-log-parsing-reference.md``. Public API:

    from bedwars_parser import parse_log
    result = parse_log("latest.log")
    print(result.stats.games, result.stats.wins, result.stats.final_deaths)
"""

from .events import Event, Game, Kind, Outcome
from .parse import ParseResult, format_report, parse_log
from .resolve import Stats

__all__ = [
    "parse_log",
    "format_report",
    "ParseResult",
    "Stats",
    "Event",
    "Game",
    "Kind",
    "Outcome",
]
