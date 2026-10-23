"""Reading the official injury report PDF, on a synthetic layout shaped like the real one.

The real report (2026-10-23 07:15 AM ET) is the NBA's document and stays out of
the repository; set BETHERO_INJURY_PDF to its path to run the last test on it.
"""

import os
from datetime import date, datetime
from pathlib import Path

import pytest

from bethero_nba import analyze, injuries
from bethero_nba.injuries import EASTERN, Report, ReportEntry, ReportFormatError
from tests.helpers import board

STARTS = {"date": 24, "time": 120, "matchup": 201, "team": 265, "player": 426, "status": 587, "reason": 667}


def words(text, x0, top):
    """A line of text as pdfplumber words, about 5 points per character."""
    out, x = [], x0
    for t in text.split():
        out.append({"text": t, "x0": x, "x1": x + 5 * len(t), "top": top, "bottom": top + 10})
        x += 5 * len(t) + 3
    return out


def row(top, **cells):
    return [w for column, text in cells.items() for w in words(text, STARTS[column], top)]


def title(stamp="10/23/26 06:30 PM"):
    return words(f"Injury Report: {stamp}", 288, 45)


HEADER = [w for label, x in (("Game Date", 23), ("Game Time", 119), ("Matchup", 200), ("Team", 264),
                             ("Player Name", 425), ("Current Status", 586), ("Reason", 666))
          for w in words(label, x, 107)]


def pages(second_title="10/23/26 06:30 PM", extra_below=None):
    page1 = (title() + HEADER
             + row(129, date="10/23/2026", time="07:00 (ET)", matchup="NYK@BOS", team="New York Knicks",
                   player="Brunson, Jalen", status="Questionable", reason="Injury/Illness - Left Ankle Sprain")
             # a reason that wraps fills the band; player and status sit centred between its lines
             + row(146, reason="Injury/Illness - Right Knee") + row(152, player="Hart, Josh", status="Out")
             + row(158, reason="Soreness")
             + row(180, team="Boston Celtics", player="Tatum, Jayson", status="Probable", reason="Rest")
             + row(210, date="10/24/2026", time="06:00 (ET)", matchup="MIA@CHA", team="Charlotte Hornets",
                   player="Ball, LaMelo", status="Questionable", reason="Injury/Illness - Right")
             + words("Page 1 of 2", 400, 545) + (extra_below or []))
    page2 = (title(second_title)
             + row(80, reason="Ankle Sprain")                    # the reason above, wrapped past the page
             + row(110, team="Miami Heat", reason="NOT YET SUBMITTED")
             + words("Page 2 of 2", 400, 545))
    return [(page1, [144.0, 170.0, 200.0, 230.0]), (page2, [100.0, 130.0])]


def test_layout_rows_follow_the_rules_not_the_text_lines():
    report = injuries.parse_layout(pages())
    assert report.report_time == datetime(2026, 10, 23, 18, 30, tzinfo=EASTERN)
    nov = date(2026, 10, 23)
    assert report.entries == (
        ReportEntry(nov, "NYK", "BOS", "NYK", "Brunson, Jalen", "Questionable", "Injury/Illness - Left Ankle Sprain"),
        ReportEntry(nov, "NYK", "BOS", "NYK", "Hart, Josh", "Out", "Injury/Illness - Right Knee Soreness"),
        ReportEntry(nov, "NYK", "BOS", "BOS", "Tatum, Jayson", "Probable", "Rest"),
        ReportEntry(date(2026, 10, 24), "MIA", "CHA", "CHA", "Ball, LaMelo", "Questionable",
                    "Injury/Illness - Right Ankle Sprain"),
        ReportEntry(date(2026, 10, 24), "MIA", "CHA", "MIA", None, None, "NOT YET SUBMITTED"))
    assert [r.player for r in report.records({nov})] == ["Brunson, Jalen", "Hart, Josh", "Tatum, Jayson"]


@pytest.mark.parametrize("change", [
    {"second_title": "10/23/26 06:45 PM"},                              # pages from two reports
    {"extra_below": words("Something else", 400, 560)},                # text after the table
])
def test_layout_refuses_what_it_has_not_seen(change):
    with pytest.raises(ReportFormatError):
        injuries.parse_layout(pages(**change))


def test_rows_without_a_player_must_be_not_submitted():
    with pytest.raises(ReportFormatError):
        injuries.parse_table([list(injuries.COLUMNS), ["10/24/2026", "06:00 (ET)", "MIA@CHA", "Miami Heat", "", "",
                                                       "Something"]], datetime(2026, 10, 23, 18, tzinfo=EASTERN))
    with pytest.raises(ReportFormatError):                               # team not in the matchup
        injuries.parse_table([list(injuries.COLUMNS), ["10/24/2026", "06:00 (ET)", "MIA@CHA", "Boston Celtics",
                                                       "X, Y", "Out", "Rest"]], datetime(2026, 10, 23, 18, tzinfo=EASTERN))


def report_at(hour, minute=0, day=23, entries=None):
    nov = date(2026, 10, 23)
    entries = entries or (
        ReportEntry(nov, "CHI", "MIL", "CHI", "Hawkins, Jordan", "Questionable", "Illness"),   # MIL absent
        ReportEntry(nov, "LAC", "LAL", "LAL", "LaRavia, Jake", "Questionable", "Ankle"),
        ReportEntry(date(2026, 10, 24), "MIA", "CHA", "MIA", None, None, "NOT YET SUBMITTED"))
    return Report(datetime(2026, 10, day, hour, minute, tzinfo=EASTERN), tuple(entries))


def test_gameday_submissions_wait_for_1pm_local_and_skip_unsubmitted():
    games = [(date(2026, 10, 23), "CHI", "MIL"), (date(2026, 10, 23), "LAC", "LAL"),
             (date(2026, 10, 24), "MIA", "CHA")]
    assert injuries.gameday_submissions(report_at(7, 15), games) == {}             # morning: day-before statuses
    at_1530 = injuries.gameday_submissions(report_at(15, 30), games)
    assert set(at_1530) == {"CHI", "MIL"}          # 1 p.m. Central has passed, 1 p.m. Pacific (16:00 ET) not
    at_1615 = injuries.gameday_submissions(report_at(16, 15), games)
    assert set(at_1615) == {"CHI", "MIL", "LAC", "LAL"}     # MIL absent from its block: filed, nothing to report
    assert "MIA" not in at_1615 and "CHA" not in at_1615    # not submitted; and 10/24 statuses are not due yet
    assert injuries.gameday_submissions(report_at(18, 0), [(date(2026, 10, 25), "BOS", "NYK")]) == {}


def test_injury_gates_from_the_official_report(cfg):
    b = board()                                       # NYK @ BOS, tip 2026-11-02 19:30 ET
    day = date(2026, 11, 2)
    official = Report(datetime(2026, 11, 2, 18, 0, tzinfo=EASTERN), (
        ReportEntry(day, "NYK", "BOS", "NYK", "Brunson, Jalen", "Questionable", "Ankle"),
        ReportEntry(date(2026, 11, 3), "NYK", "TOR", "NYK", "Brunson, Jalen", "Out", "Ankle")))  # next game
    at = datetime(2026, 11, 2, 18, 40, tzinfo=EASTERN)
    eligible, blocking = analyze.injury_gates(official, datetime(2026, 11, 2, 9, 5, tzinfo=EASTERN), b, cfg, at)
    label = b.games[0].label
    assert eligible[label] is True
    assert blocking[label] == ["Brunson, Jalen（Questionable）"]      # today's status, not tomorrow's
    no_refs, _ = analyze.injury_gates(official, None, b, cfg, at)
    assert no_refs[label] is False


REAL = os.environ.get("BETHERO_INJURY_PDF")


@pytest.mark.skipif(not REAL or not Path(REAL).exists(), reason="set BETHERO_INJURY_PDF to the real report")
def test_real_report_2026_10_23_0715():
    report = injuries.read_pdf(REAL)
    assert report.report_time == datetime(2026, 10, 23, 7, 15, tzinfo=EASTERN)
    players = [e for e in report.entries if e.player is not None]
    assert len(players) == 85 and len(report.entries) - len(players) == 16
    by_name = {(e.team, e.player): e for e in players}
    assert by_name[("HOU", "Sheppard, Reed")].reason == "Injury/Illness - Left Knee Contusion / Bone Bruise"
    assert by_name[("DAL", "Howard, Jett")].status == "Doubtful"                  # first row on page 2
    assert by_name[("SAC", "Simmons, Ben")].status == "Out"                       # carried onto page 6
    assert any(e.team == "LAC" for e in players)                                   # "LA Clippers"
    oct23 = date(2026, 10, 23)
    assert not any(e.team == "MIL" and e.game_date == oct23 for e in report.entries)   # filed, nothing to report
    games = sorted({(e.game_date, e.away, e.home) for e in report.entries})
    assert injuries.gameday_submissions(report, games) == {}                      # 07:15 AM: nothing game-day yet
