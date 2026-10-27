"""Box-score minutes (RULES R-9.3) on synthetic files shaped like the sportsdataverse ones."""

from datetime import date, datetime, timezone

import pytest

from bethero_nba import boxscores, net
from bethero_nba.boxscores import BoxScoreError
from tests.helpers import box_season

NOV2 = date(2026, 11, 2)


def parse(cfg, **kwargs):
    return boxscores.parse(*box_season(**kwargs), 2027, cfg)


def test_last_ten_games_played_before_the_slate(cfg):
    scores = parse(cfg, games=12)                                   # 2026-10-20 .. 10-31
    assert scores.summary() == "season 2027: 12 final games, 24/24 team box scores pass both checks"
    assert scores.recent("NYK", "Brunson, Jalen", NOV2, 10) == ([35.0] * 10, "")
    assert scores.recent("NYK", "Brunson, Jalen", date(2026, 10, 25), 10) == ([35.0] * 5, "")   # fewer
    assert scores.recent("NYK", "Brunson, Jalen", date(2026, 10, 20), 10) == ([], "")
    assert boxscores.season_key(cfg) == 2027


def test_a_box_score_short_of_points_or_minutes_stops_the_supply(cfg):
    def drop_shamet(i, knicks, row):
        if i == 11:
            del knicks[8]                                            # 18 minutes and 10 points missing
    assert parse(cfg, change=drop_shamet).recent("NYK", "Brunson, Jalen", NOV2, 10) == (
        None, "10/31 那場的逐場數據不完整")

    def minutes_only(i, knicks, row):                                # points still add up to the score
        if i == 11:
            knicks[8][4] = "0.0"
            row["away_score"] = "80"
            knicks[8][5] = "0"
    assert parse(cfg, change=minutes_only).recent("NYK", "Brunson, Jalen", NOV2, 10)[0] is None
    # a broken game after the window is never reached
    assert parse(cfg, change=drop_shamet).recent("NYK", "Brunson, Jalen", date(2026, 10, 31), 10) == (
        [35.0] * 10, "")


def test_overtime_and_rounding(cfg):
    def overtime(i, knicks, row):
        if i == 11:
            row["status_period"] = "5.0"                             # 265 minutes to fill
    assert parse(cfg, change=overtime).recent("NYK", "Brunson, Jalen", NOV2, 10)[0] is None

    def overtime_filled(i, knicks, row):
        if i == 11:
            row["status_period"] = "5.0"
            knicks[1][4] = "55.0"                                    # Hart 30 + 25
    scores = parse(cfg, change=overtime_filled)
    assert [g.checked for g in scores.games["NYK"]][-1] is True
    assert [g.checked for g in scores.games["BOS"]][-1] is False    # Boston's five still add up to 240

    def rounded(i, knicks, row):
        if i == 11:
            knicks[1][4] = "34.0"                                    # +4 on 9 players: within 4.5
    assert parse(cfg, change=rounded).games["NYK"][-1].checked is True

    def too_much(i, knicks, row):
        if i == 11:
            knicks[1][4] = "35.0"                                    # +5: outside
    assert parse(cfg, change=too_much).games["NYK"][-1].checked is False


def test_dnp_and_zero_minute_rows_are_not_games_played(cfg):
    def benched(i, knicks, row):
        if i == 11:                                                  # DNP: his 12 minutes go to Payne
            knicks[0][4:7] = ["", "", "true"]
            knicks[7][4] = f"{float(knicks[7][4]) + 12:.1f}"
            row["away_score"] = "80"
        if i == 10:                                                  # on for seconds: 0 minutes
            knicks[0][4] = "0.0"
            knicks[0][5] = "0"
            knicks[7][4] = f"{float(knicks[7][4]) + 12:.1f}"
            row["away_score"] = "80"
    scores = parse(cfg, brunson=12, change=benched)
    assert all(g.checked for g in scores.games["NYK"])
    minutes, _ = scores.recent("NYK", "Brunson, Jalen", NOV2, 10)
    assert minutes == [12.0] * 10                                    # games 0..9: 10 played


def test_a_past_game_that_is_not_final_stops_the_supply(cfg):
    def stale(i, knicks, row):
        if i == 11:
            row["status_type_name"] = "STATUS_SCHEDULED"
    scores = parse(cfg, change=stale)
    assert scores.recent("NYK", "Brunson, Jalen", NOV2, 10) == (
        None, "10/31 那場在數據裡不是終場（STATUS_SCHEDULED）")
    assert scores.recent("NYK", "Brunson, Jalen", date(2026, 10, 31), 10) == ([35.0] * 10, "")


def test_unknown_codes_and_shapes(cfg):
    def tbd(i, knicks, row):
        if i == 11:
            row.update(status_type_name="STATUS_SCHEDULED", home_abbreviation="TBD", away_abbreviation="TBD")
    assert len(parse(cfg, change=tbd).games["NYK"]) == 11         # a knockout placeholder is skipped

    def unknown(i, knicks, row):
        if i == 11:
            row["home_abbreviation"] = "XXX"
    with pytest.raises(BoxScoreError, match="XXX"):
        parse(cfg, change=unknown)
    box, schedule = box_season(games=1)
    with pytest.raises(BoxScoreError, match="columns"):
        boxscores.parse(box.replace("did_not_play", "dnp"), schedule, 2027, cfg)


@pytest.mark.parametrize("report, espn", [
    ("Brunson, Jalen", "Jalen Brunson"),
    ("Lively II, Dereck", "Dereck Lively II"),
    ("Udeh, Jr., Ernest", "Ernest Udeh Jr."),
    ("McConnell, T.J.", "T.J. McConnell"),
    ("Tomlin, Nae'Qwan", "Nae'Qwan Tomlin"),
    ("Doncic, Luka", "Luka Dončić"),
    ("Niederhauser, Yanic Konan", "Yanic Konan Niederhauser"),
])
def test_report_names_meet_espn_names(report, espn):
    assert boxscores.report_name(report) == boxscores.normalise(espn)


def test_names_must_match_one_player_on_that_team(cfg):
    def twin(i, knicks, row):
        if i == 0:
            knicks.append(["100", "77", "Jalen Brunson Jr.", "NY", "0.0", "0", "false"])
    scores = parse(cfg, change=twin)
    assert scores.recent("NYK", "Brunson, Jalen", NOV2, 10) == (None, "逐場數據裡有同名球員")
    assert scores.recent("NYK", "Nobody, Some", NOV2, 10) == (None, "逐場數據找不到這個名字")
    assert scores.recent("BOS", "Brunson, Jalen", NOV2, 10) == (None, "逐場數據找不到這個名字")
    found, missing = parse(cfg).supply({"NYK": {"Brunson, Jalen", "Nobody, Some"}}, NOV2, 10)
    assert found == {"NYK": {"Brunson, Jalen": [35.0] * 10}}
    assert missing == {"NYK Nobody, Some": "逐場數據找不到這個名字"}


def test_fetch_downloads_the_season_files_through_the_live_gate(cfg, tmp_path):
    box, schedule = box_season(games=12)

    class Opener:
        def __init__(self):
            self.urls = []

        def __call__(self, request, timeout):
            self.urls.append(request.full_url)
            body = (box if "player_box" in request.full_url else schedule).encode("utf-8")

            class R:
                status, headers = 200, {"Content-Type": "application/octet-stream"}

                def read(self):
                    return body

                def __enter__(self):
                    return self

                def __exit__(self, *a):
                    return False
            return R()

    opener = Opener()
    client = net.HttpClient(tmp_path, live=True, user_agent="t", min_interval_s=0, opener=opener,
                            now=lambda: datetime(2026, 11, 2, 23, 0, tzinfo=timezone.utc))
    scores = boxscores.fetch(client, cfg)
    assert opener.urls == [boxscores.PLAYER_BOX.format(season=2027), boxscores.SCHEDULE.format(season=2027)]
    assert [s["file"].endswith(".csv.gz") for s in scores.sources] == [True, True]
    again = boxscores.load(*(tmp_path / "github.com" / s["file"] for s in scores.sources), cfg)
    assert again.recent("NYK", "Brunson, Jalen", NOV2, 10) == ([35.0] * 10, "")
    with pytest.raises(net.LiveRequestsDisabled):
        boxscores.fetch(net.HttpClient(tmp_path, live=False, user_agent="t", min_interval_s=0), cfg)
