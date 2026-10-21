"""Scenario flags (RULES §10). Flags never change EV or stake (P5).

Rest and travel flags come from a schedule of recent games (The Odds API
scores cover the last three days, enough for B2B and 3IN4); calendar flags
come from cfg:season. Flags that need inputs this pipeline does not collect
yet (trades, standings, the participation policy's star list, referee crews)
are set only when the caller passes those inputs.

CUP_GROUP is date-based: on group-play Cup Nights every scheduled game has
been a Cup game in past editions; RULES Appendix A lists it as assumed for
2026. Knockout games are not date-based, because teams that miss the
knockouts play their two extra games around the same dates.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from .teams import team

EASTERN = ZoneInfo("America/New_York")


@dataclass(frozen=True)
class PlayedGame:
    tip: datetime
    home: str          # tricodes
    away: str


def _et(moment: datetime) -> date:
    return moment.astimezone(EASTERN).date()


def _team_games(schedule: list[PlayedGame], tricode: str, before: datetime) -> list[PlayedGame]:
    return sorted((g for g in schedule if tricode in (g.home, g.away) and g.tip < before),
                  key=lambda g: g.tip)


def rest_days(schedule: list[PlayedGame], tricode: str, tip: datetime, horizon_days: int = 3) -> int | None:
    """Full days off since the team's previous game, or None if none within the horizon."""
    previous = _team_games(schedule, tricode, tip)
    if not previous:
        return None
    gap = (_et(tip) - _et(previous[-1].tip)).days - 1
    return gap if gap < horizon_days else None


def _offset_hours(tricode: str, at: datetime) -> float:
    return at.astimezone(ZoneInfo(team(tricode).tz)).utcoffset().total_seconds() / 3600


def flags_for(home: str, away: str, tip: datetime, schedule: list[PlayedGame], cfg, *,
              season_games_played: dict[str, int] | None = None,
              traded_recently: set[str] = frozenset(),   # within cfg:scenario.post_deadline_window_days
              lottery_range: set[str] = frozenset(),
              stars_out: set[str] = frozenset(),
              referee_crew: list[str] | None = None,
              knockout: bool = False) -> list[str]:
    flags: list[str] = []
    day = _et(tip)
    for tricode in (home, away):
        previous = _team_games(schedule, tricode, tip)
        dates = {_et(g.tip) for g in previous}
        if day - timedelta(days=1) in dates:
            flags.append(f"B2B:{tricode}")
        if len({d for d in dates if day - timedelta(days=3) <= d < day}) >= 2:
            flags.append(f"3IN4:{tricode}")
        if previous:
            last_arena = previous[-1].home
            if abs(_offset_hours(last_arena, tip) - _offset_hours(home, tip)) >= 2:
                flags.append(f"TRAVEL_TZ:{tricode}")
    rest = {t: rest_days(schedule, t, tip) for t in (home, away)}
    if None not in rest.values() and abs(rest[home] - rest[away]) >= 2:
        flags.append("REST_DIFF")
    if home in cfg.get("scenario.altitude_teams"):
        flags.append("ALTITUDE")
    if day in cfg.get("season.cup_group_play_dates"):
        flags.append("CUP_GROUP")
    if day == cfg.get("season.cup_final")["date"]:
        flags.append("NEUTRAL_SITE")
    elif knockout:
        flags.append("CUP_KNOCKOUT")
    if season_games_played is not None:
        early = cfg.get("scenario.early_season_games")
        if any(season_games_played.get(t, 0) < early for t in (home, away)):
            flags.append("EARLY_SEASON")
    if traded_recently & {home, away}:     # teams with a rotation trade inside the window
        flags.append("POST_DEADLINE_ROSTER")
    if lottery_range & {home, away}:
        flags.append("LATE_SEASON_LOTTERY")
    if stars_out & {home, away}:
        flags.append("STAR_ABSENT")
    if referee_crew:
        flags.append("REF_CREW")
    return flags


def material(flags: list[str], cfg) -> list[str]:
    """Flags that cap confidence (RULES R-10.2); team-specific flags count by their base name."""
    names = set(cfg.get("scenario.material_flags"))
    return [f for f in flags if f.split(":")[0] in names]
