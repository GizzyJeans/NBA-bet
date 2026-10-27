"""Official injury report -> per-player status timeline, and the status gates (RULES §9, R-4.5).

    python -m bethero_nba.injuries <Injury-Report_YYYY-MM-DD_hh_mmAM.pdf>

Reporting rules (official.nba.com, 2025-26 page; RULES Appendix A): each team
sets every player's status by 5 p.m. local the day before (second game of a
back-to-back: 1 p.m. local on game day), and files a game-day update between
11 a.m. and 1 p.m. local (8-10 a.m. for tips at 5 p.m. or earlier), except for
the second game of a back-to-back.

The report is the PDF Eric saves in his browser; nothing here fetches from NBA
hosts (official.nba.com refuses the cloud environment). `read_pdf` was built on
a real copy, the 2026-10-23 07:15 AM ET report (6 pages):

- every page repeats the title "Injury Report: MM/DD/YY hh:mm AM" (US Eastern);
  the column header row is on page 1 only;
- horizontal rules separate the rows. A cell that wraps fills its band while
  shorter cells are centred in it, so rows are cut at the rules, not at lines
  of text;
- a game and a team are printed only on their first row, so blank leading cells
  carry the value from the row above, across pages too;
- a reason can wrap past a page break, leaving a band with reason text only;
- a team that has not filed shows one row with no player and the reason
  "NOT YET SUBMITTED"; a team that filed with nothing to report is absent from
  its game's block (MIL in CHI@MIL on that report).

A JSON transcription (README) remains the fallback; without either, `blocking`
is None in the pass and every game ends at NB-STATUS (RULES R-9.2).
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import math
import re
from dataclasses import dataclass, replace
from datetime import date, datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo

from .teams import team

STATUSES = ("Out", "Doubtful", "Questionable", "Probable", "Available")
COLUMNS = ("Game Date", "Game Time", "Matchup", "Team", "Player Name", "Current Status", "Reason")
NOT_SUBMITTED = "NOT YET SUBMITTED"
EASTERN = ZoneInfo("America/New_York")
TITLE = re.compile(r"Injury Report: (\d{2}/\d{2}/\d{2}) (\d{1,2}:\d{2}) ([AP]M)")
FOOTER = re.compile(r"Page \d+ of \d+")
STATUS_DUE = time(13, 0)       # every game-day update, and a back-to-back's status, is in by 1 p.m. local


class ReportFormatError(ValueError):
    """The rows do not look like the official report; refuse rather than guess."""


@dataclass(frozen=True)
class StatusRecord:
    report_time: datetime
    team: str          # tricode
    player: str
    status: str
    reason: str


@dataclass(frozen=True)
class ReportEntry:
    game_date: date            # US Eastern, as printed
    away: str
    home: str
    team: str                  # tricode
    player: str | None         # None: the team has not submitted
    status: str | None
    reason: str


@dataclass(frozen=True)
class Report:
    report_time: datetime
    entries: tuple[ReportEntry, ...]
    sha256: str | None = None

    def records(self, days: set[date] | None = None) -> list[StatusRecord]:
        """Player rows as status records, for the given game dates only: a team
        playing on two dates in one report has a status for each game."""
        return [StatusRecord(self.report_time, e.team, e.player, e.status, e.reason) for e in self.entries
                if e.player is not None and (days is None or e.game_date in days)]

    def covers(self, day: date) -> bool:
        return any(e.game_date == day for e in self.entries)

    def not_submitted(self, day: date, tricode: str) -> bool:
        return any(e.game_date == day and e.team == tricode and e.player is None for e in self.entries)


def _matchup(text: str) -> tuple[str, str]:
    away, _, home = text.partition("@")
    return team(away).tricode, team(home).tricode


def parse_table(rows: list[list[str]], report_time: datetime) -> Report:
    """Rows of the official table (header first) -> report entries."""
    if not rows or [c.strip() for c in rows[0]] != list(COLUMNS):
        raise ReportFormatError(f"header is not {COLUMNS}")
    carried = [""] * 4
    entries: list[ReportEntry] = []
    for number, row in enumerate(rows[1:], start=2):
        if len(row) != len(COLUMNS):
            raise ReportFormatError(f"row {number} has {len(row)} cells")
        cells = [c.strip() for c in row]
        if not any(cells[:6]) and cells[6]:                  # a reason wrapped past a page break
            if not entries or entries[-1].player is None:
                raise ReportFormatError(f"row {number}: reason {cells[6]!r} continues no player row")
            entries[-1] = replace(entries[-1], reason=f"{entries[-1].reason} {cells[6]}")
            continue
        for i in range(4):                                   # game date, time, matchup, team
            if cells[i]:
                carried[i] = cells[i]
        try:
            game_date = datetime.strptime(carried[0], "%m/%d/%Y").date()
            away, home = _matchup(carried[2])
            tricode = team(carried[3]).tricode
        except (ValueError, KeyError):
            raise ReportFormatError(f"row {number}: cannot read game and team {carried!r}") from None
        if tricode not in (away, home):
            raise ReportFormatError(f"row {number}: {carried[3]} is not in {carried[2]}")
        player, status, reason = cells[4], cells[5], cells[6]
        if not player:
            if status or reason != NOT_SUBMITTED:
                raise ReportFormatError(f"row {number}: no player, but {status!r} {reason!r}")
            entries.append(ReportEntry(game_date, away, home, tricode, None, None, reason))
            continue
        if status not in STATUSES:
            raise ReportFormatError(f"row {number}: unknown status {status!r}")
        entries.append(ReportEntry(game_date, away, home, tricode, player, status, reason))
    return Report(report_time, tuple(entries))


def parse_rows(rows: list[list[str]], report_time: datetime) -> list[StatusRecord]:
    """Player rows of the official table as status records."""
    return parse_table(rows, report_time).records()


# ------------------------------------------------------------------ PDF layout


def _text_lines(words: list[dict]) -> list[list[dict]]:
    """Words grouped into printed lines by their top, each left to right."""
    lines: list[list[dict]] = []
    for w in sorted(words, key=lambda w: (w["top"], w["x0"])):
        if lines and abs(lines[-1][0]["top"] - w["top"]) < 2:
            lines[-1].append(w)
        else:
            lines.append([w])
    return [sorted(line, key=lambda w: w["x0"]) for line in lines]


def _join(words: list[dict]) -> str:
    return " ".join(w["text"] for w in words)


def layout_rows(words: list[dict], edges: list[float], starts: list[float]) -> list[list[str]]:
    """One page's table words -> rows of cells. A row is the band between two
    horizontal rules; a word goes to the rightmost column starting at or left of it."""
    rows = []
    for upper, lower in zip(edges, edges[1:]):
        band = [w for w in words if upper <= (w["top"] + w["bottom"]) / 2 < lower]
        if not band:
            continue
        cells: list[list[str]] = [[] for _ in starts]
        for line in _text_lines(band):
            for w in line:
                columns = [i for i, x in enumerate(starts) if w["x0"] >= x - 2]
                if not columns:
                    raise ReportFormatError(f"{w['text']!r} lies left of the table")
                cells[columns[-1]].append(w["text"])
        rows.append([" ".join(c) for c in cells])
    return rows


def parse_layout(pages: list[tuple[list[dict], list[float]]], sha256: str | None = None) -> Report:
    """Pages as (words, y of the horizontal rules) -> report. Pure, so tests need no PDF."""
    report_time, starts, rows = None, None, [list(COLUMNS)]
    for number, (words, rules) in enumerate(pages, start=1):
        lines = _text_lines(words)
        titles = [line for line in lines if TITLE.fullmatch(_join(line))]
        if len(titles) != 1:
            raise ReportFormatError(f"page {number}: no single 'Injury Report:' title")
        m = TITLE.fullmatch(_join(titles[0]))
        stamp = datetime.strptime(f"{m[1]} {m[2]} {m[3]}", "%m/%d/%y %I:%M %p").replace(tzinfo=EASTERN)
        if report_time not in (None, stamp):
            raise ReportFormatError(f"page {number}: title time {stamp} differs from page 1")
        report_time = stamp
        top = max(w["bottom"] for w in titles[0])
        if number == 1:
            header = [line for line in lines if _join(line) == " ".join(COLUMNS)]
            if len(header) != 1:
                raise ReportFormatError("page 1: no column header row")
            starts, i = [], 0
            for label in COLUMNS:                            # a column starts at its label's first word
                starts.append(header[0][i]["x0"])
                i += len(label.split())
            top = max(top, max(w["bottom"] for w in header[0]))
        body = [w for w in words if w["top"] > top]
        rules = sorted(r for r in rules if r > top)
        if not rules:
            raise ReportFormatError(f"page {number}: no table rules")
        below = _text_lines([w for w in body if (w["top"] + w["bottom"]) / 2 >= rules[-1]])
        if len(below) > 1 or (below and not FOOTER.fullmatch(_join(below[0]))):
            raise ReportFormatError(f"page {number}: text below the table: {[_join(line) for line in below]}")
        table = [w for w in body if (w["top"] + w["bottom"]) / 2 < rules[-1]]
        rows += layout_rows(table, [top] + rules, starts)
    if report_time is None:
        raise ReportFormatError("the PDF has no pages")
    return replace(parse_table(rows, report_time), sha256=sha256)


def _rules(page) -> list[float]:
    """y of the page's horizontal rules, drawn as lines or as hairline rectangles."""
    ys = [ln["top"] for ln in page.lines if abs(ln["bottom"] - ln["top"]) < 1 and ln["x1"] - ln["x0"] > 30]
    ys += [r["top"] for r in page.rects if r["height"] < 1.5 and r["width"] > 30]
    return sorted({round(y, 1) for y in ys})


def read_pdf(path: Path | str) -> Report:
    """The official report as Eric saved it. Only this function needs pdfplumber."""
    import pdfplumber

    data = Path(path).read_bytes()
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        pages = [(page.extract_words(x_tolerance=1.5, y_tolerance=2), _rules(page)) for page in pdf.pages]
    return parse_layout(pages, hashlib.sha256(data).hexdigest())


def gameday_submissions(report: Report, games: list[tuple[date, str, str]]) -> dict[str, datetime]:
    """Teams whose game-day status the report shows (RULES R-4.5), timed at the report.

    `games` are (US Eastern game date, away, home). A team counts when the report
    covers its game date, does not mark it NOT YET SUBMITTED, and came out at or
    after 1 p.m. on that date both where the game is played and in the team's own
    city, when every game-day update and a back-to-back's status are due. A team
    absent from its game's block filed with nothing to report.
    """
    out = {}
    for day, away, home in games:
        if not report.covers(day):
            continue
        for tricode in (away, home):
            if report.not_submitted(day, tricode):
                continue
            due = max(datetime.combine(day, STATUS_DUE, ZoneInfo(team(t).tz)) for t in (home, tricode))
            if report.report_time >= due:
                out[tricode] = report.report_time
    return out


# ------------------------------------------------------------------- timeline


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
    key_player_window_games games (RULES R-9.3). A shorter list is not that
    average, so its player counts as key."""
    window = cfg.get("injuries.key_player_window_games")
    threshold = cfg.get("injuries.key_player_min_minutes")
    return {p for p, mins in minutes.items() if len(mins) < window or sum(mins[-window:]) / window >= threshold}


def _listed(timeline: Timeline, tricodes: tuple[str, ...], cfg, at: datetime):
    """(team, player, status) for players currently listed with a blocking status. Reasons in
    injuries.nonblocking_reasons (a two-way player's G League assignment, Eric 2026-10-23) never block."""
    statuses = set(cfg.get("injuries.blocking_statuses"))
    exempt = set(cfg.get("injuries.nonblocking_reasons"))
    for tricode in tricodes:
        for player in sorted(timeline.players(tricode)):
            record = timeline.status_at(tricode, player, at)
            if record is not None and record.status in statuses and record.reason.strip() not in exempt:
                yield tricode, player, record.status


def listed(timeline: Timeline, tricodes: tuple[str, ...], cfg, at: datetime) -> dict[str, set[str]]:
    """Players currently listed with a blocking status, by team: the ones whose minutes R-9.3 needs."""
    found: dict[str, set[str]] = {}
    for tricode, player, _ in _listed(timeline, tricodes, cfg, at):
        found.setdefault(tricode, set()).add(player)
    return found


def listed_players(timeline: Timeline, tricodes: tuple[str, str],
                   minutes: dict[str, dict[str, list[float]]] | None, cfg,
                   at: datetime) -> tuple[list[str], list[str], list[str]]:
    """(blocking, cleared, unsupplied) among the players currently listed with a blocking status.

    A listed player blocks when he is key (RULES R-9.3). One whose recent
    minutes are not supplied counts as key: missing data can only block. So
    minutes are needed only to clear a bench player. Blocking and cleared
    players carry what their minutes showed, so the report can show it;
    `unsupplied` names the blocking players whose minutes were not supplied."""
    window = cfg.get("injuries.key_player_window_games")
    blocking, cleared, unsupplied = [], [], []
    for tricode, player, status in _listed(timeline, tricodes, cfg, at):
        known = (minutes or {}).get(tricode, {})
        if player not in known:
            blocking.append(f"{player}（{status}）")
            unsupplied.append(player)
        elif len(known[player]) < window:
            blocking.append(f"{player}（{status}，本季出賽 {len(known[player])} 場）")
        else:
            average = sum(known[player][-window:]) / window
            text = f"{player}（{status}，本季近 {window} 場平均 {average:.1f} 分鐘）"
            (blocking if player in key_players({player: known[player]}, cfg) else cleared).append(text)
    return blocking, cleared, unsupplied


def blocking_players(timeline: Timeline, tricodes: tuple[str, str],
                     minutes: dict[str, dict[str, list[float]]] | None, cfg, at: datetime) -> list[str]:
    """Players currently listed with a blocking status who are key (RULES R-9.3, R-9.4)."""
    return listed_players(timeline, tricodes, minutes, cfg, at)[0]


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
    return moment.astimezone(EASTERN).date()


# -------------------------------------------------------------------- minutes


class MinutesError(ValueError):
    """A minutes transcription that does not follow the README format."""


@dataclass(frozen=True)
class Minutes:
    """Listed players' minutes, transcribed from Eric's game-log screenshots (RULES R-9.3).

    `players` maps a tricode to each player's name as the injury report prints
    it and his minutes in his games played this season, oldest first. No source
    feeds this automatically: the free API checked on 2026-10-27 serves only a
    three-day window, and 5 of the 10 team box scores it gave for 2026-10-26 UTC
    left out players (RULES Appendix B)."""
    slate_et: date
    seen_at: datetime
    source: str
    players: dict[str, dict[str, list[float]]]
    sha256: str

    def fresh_for(self, slate_et: date, at: datetime, cfg) -> bool:
        """Taken on the slate's US Eastern date, late enough that the previous
        night's games are in the log (cfg:injuries.minutes_screenshot_from_et),
        and not after the analysis."""
        start = time.fromisoformat(cfg.get("injuries.minutes_screenshot_from_et"))
        return self.slate_et == slate_et and datetime.combine(slate_et, start, EASTERN) <= self.seen_at <= at


def load_minutes(path: Path | str) -> Minutes:
    raw = Path(path).read_bytes()
    try:
        data = json.loads(raw.decode("utf-8"))
        slate_et = date.fromisoformat(data["slate_et"])
        seen_at = datetime.fromisoformat(data["seen_at"])
        source = str(data["source"]).strip()
        by_team = data["players"].items()
    except (ValueError, KeyError, TypeError, AttributeError) as exc:
        raise MinutesError(f"{path}: not a minutes transcription ({exc})") from None
    if seen_at.tzinfo is None or not source:
        raise MinutesError(f"{path}: seen_at needs a UTC offset and source must say whose screenshot it was")
    players: dict[str, dict[str, list[float]]] = {}
    for key, by_name in by_team:
        try:
            tricode = team(key).tricode
        except KeyError:
            raise MinutesError(f"{path}: unknown team {key!r}") from None
        if not isinstance(by_name, dict):
            raise MinutesError(f"{path}: {tricode}: expected player names and their minutes")
        players[tricode] = {}
        for name, values in by_name.items():
            if not isinstance(values, list) or not all(
                    isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) and v >= 0
                    for v in values):
                raise MinutesError(f"{path}: {tricode} {name}: minutes must be a list of numbers, 0 or more")
            players[tricode][name] = [float(v) for v in values]
    return Minutes(slate_et, seen_at, source, players, hashlib.sha256(raw).hexdigest())


# ---------------------------------------------------------------------- CLI


def main(argv: list[str] | None = None) -> int:
    from . import cli

    cli.setup_output()
    parser = argparse.ArgumentParser(prog="python -m bethero_nba.injuries",
                                     description="Read an official injury report PDF and show what the gates see.")
    parser.add_argument("pdf", type=Path)
    args = parser.parse_args(argv)
    report = read_pdf(args.pdf)
    print(f"report {report.report_time:%Y-%m-%d %H:%M} ET, sha256 {report.sha256}")
    games: dict[tuple, list[ReportEntry]] = {}
    for e in report.entries:
        games.setdefault((e.game_date, e.away, e.home), []).append(e)
    for (day, away, home), entries in games.items():
        pending = sorted({e.team for e in entries if e.player is None})
        listed = sorted({e.team for e in entries if e.player is not None})
        flagged = [f"{e.team} {e.player} ({e.status})" for e in entries if e.status in ("Questionable", "Doubtful")]
        print(f"{day} {away}@{home}: listed {', '.join(listed) or '-'}; not submitted {', '.join(pending) or '-'}; "
              f"Q/D {'; '.join(flagged) or '-'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
