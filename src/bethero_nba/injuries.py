"""Official injury report -> per-player status timeline, and the status gates (RULES §9, R-4.5).

Reporting rules (official.nba.com, 2025-26 page; RULES Appendix A): each team
sets every player's status by 5 p.m. local the day before (second game of a
back-to-back: 1 p.m. local on game day), and files a game-day update between
11 a.m. and 1 p.m. local (8-10 a.m. for tips at 5 p.m. or earlier), except for
the second game of a back-to-back.

`parse_rows` turns the report's table rows into records; the report prints a
game and a team only on their first row, so blank leading cells carry the
value from the row above. Fetching and PDF text extraction are not
implemented: official.nba.com is blocked from the cloud environment and no real
report has been seen yet, so the first real report becomes the parser's test
fixture before the gate relies on it. Until then the report enters as Eric's
transcription (README); without one, `blocking` is None in the pass and every
game ends at NB-STATUS (RULES R-9.2), which is the intended fail-safe.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time
from zoneinfo import ZoneInfo

from .teams import team

STATUSES = ("Out", "Doubtful", "Questionable", "Probable", "Available")
COLUMNS = ("Game Date", "Game Time", "Matchup", "Team", "Player Name", "Current Status", "Reason")


class ReportFormatError(ValueError):
    """The rows do not look like the official report; refuse rather than guess."""


@dataclass(frozen=True)
class StatusRecord:
    report_time: datetime
    team: str          # tricode
    player: str
    status: str
    reason: str


def parse_rows(rows: list[list[str]], report_time: datetime) -> list[StatusRecord]:
    """Rows of the official table (header first), blank leading cells carried down."""
    if not rows or [c.strip() for c in rows[0]] != list(COLUMNS):
        raise ReportFormatError(f"header is not {COLUMNS}")
    carried = [""] * len(COLUMNS)
    records = []
    for number, row in enumerate(rows[1:], start=2):
        if len(row) != len(COLUMNS):
            raise ReportFormatError(f"row {number} has {len(row)} cells")
        cells = [c.strip() for c in row]
        for i in range(4):                         # game date, time, matchup, team
            if cells[i]:
                carried[i] = cells[i]
        player, status, reason = cells[4], cells[5], cells[6]
        if not player:
            continue
        if status not in STATUSES:
            raise ReportFormatError(f"row {number}: unknown status {status!r}")
        try:
            tricode = team(carried[3]).tricode
        except KeyError:
            raise ReportFormatError(f"row {number}: unknown team {carried[3]!r}") from None
        records.append(StatusRecord(report_time, tricode, player, status, reason))
    return records


class Timeline:
    def __init__(self, records: list[StatusRecord] | None = None):
        self.records: list[StatusRecord] = sorted(records or [], key=lambda r: r.report_time)

    def add(self, records: list[StatusRecord]) -> None:
        self.records = sorted(self.records + list(records), key=lambda r: r.report_time)

    def latest_report_time(self) -> datetime | None:
        return self.records[-1].report_time if self.records else None

    def status_at(self, tricode: str, player: str, at: datetime) -> StatusRecord | None:
        found = None
        for r in self.records:
            if r.report_time > at:
                break
            if r.team == tricode and r.player == player:
                found = r
        return found

    def players(self, tricode: str) -> set[str]:
        return {r.player for r in self.records if r.team == tricode}


def key_players(minutes: dict[str, list[float]], cfg) -> set[str]:
    """Players averaging at least key_player_min_minutes over their last
    key_player_window_games games (RULES R-9.3)."""
    window = cfg.get("injuries.key_player_window_games")
    threshold = cfg.get("injuries.key_player_min_minutes")
    return {p for p, mins in minutes.items() if mins and sum(mins[-window:]) / len(mins[-window:]) >= threshold}


def blocking_players(timeline: Timeline, tricodes: tuple[str, str],
                     minutes: dict[str, dict[str, list[float]]] | None, cfg, at: datetime) -> list[str]:
    """Players currently listed with a blocking status who are key (RULES R-9.3).

    A listed player whose recent minutes are not supplied counts as key: missing
    data can only block. So minutes are needed only to clear a bench player."""
    blocking = set(cfg.get("injuries.blocking_statuses"))
    found = []
    for tricode in tricodes:
        known = (minutes or {}).get(tricode, {})
        keys = key_players(known, cfg)
        for player in sorted(timeline.players(tricode)):
            record = timeline.status_at(tricode, player, at)
            if record is None or record.status not in blocking:
                continue
            if player not in known or player in keys:
                found.append(f"{player}（{record.status}）")
    return found


def gameday_window_start(tricode: str, tip: datetime) -> datetime:
    """When a team's game-day update window opens, in its own local time."""
    tz = ZoneInfo(team(tricode).tz)
    local_tip = tip.astimezone(tz)
    opens = time(8, 0) if local_tip.time() <= time(17, 0) else time(11, 0)
    return datetime.combine(local_tip.date(), opens, tz)


def final_eligible(tip: datetime, tricodes: tuple[str, str], submissions: dict[str, datetime],
                   referee_posted_at: datetime | None, at: datetime,
                   back_to_back_second: set[str] = frozenset()) -> bool:
    """RULES R-4.5: both teams' game-day submissions are in and referees are posted.

    `submissions` maps a team to the report time at which its game-day status
    first appeared. For the second game of a back-to-back the 1 p.m. local
    game-day status counts instead.
    """
    if referee_posted_at is None or referee_posted_at > at:
        return False
    for tricode in tricodes:
        submitted = submissions.get(tricode)
        if submitted is None or submitted > at:
            return False
        if tricode in back_to_back_second:
            tz = ZoneInfo(team(tricode).tz)
            if submitted < datetime.combine(tip.astimezone(tz).date(), time(0, 0), tz):
                return False                       # status is due by 1 p.m. local on game day
        elif submitted < gameday_window_start(tricode, tip):
            return False
    return True


def report_date_et(moment: datetime) -> date:
    return moment.astimezone(ZoneInfo("America/New_York")).date()
