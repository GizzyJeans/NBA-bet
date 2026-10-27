"""injuries, context, model, bias, clv, validate on synthetic inputs."""

import json
import random
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from bethero_nba import bias, clv, context, injuries, model, validate
from bethero_nba.dist import HistoryRow
from bethero_nba.odds import Leg

ET = ZoneInfo("America/New_York")


# ----------------------------------------------------------------- injuries

ROWS = [list(injuries.COLUMNS),
        ["11/02/2026", "07:30 (ET)", "NYK@BOS", "New York Knicks", "Brunson, Jalen", "Questionable", "Ankle"],
        ["", "", "", "", "Hart, Josh", "Out", "Knee"],
        ["", "", "", "Boston Celtics", "Tatum, Jayson", "Probable", "Rest"]]


def test_parse_rows_carries_cells_down():
    t = datetime(2026, 11, 2, 13, 0, tzinfo=ET)
    records = injuries.parse_rows(ROWS, t)
    assert [(r.team, r.player, r.status) for r in records] == [
        ("NYK", "Brunson, Jalen", "Questionable"), ("NYK", "Hart, Josh", "Out"),
        ("BOS", "Tatum, Jayson", "Probable")]


@pytest.mark.parametrize("rows", [
    [["Game Date", "Team"]],
    [list(injuries.COLUMNS), ["11/02/2026", "", "NYK@BOS", "New York Knicks", "X", "Maybe", ""]],
    [list(injuries.COLUMNS), ["11/02/2026", "", "NYK@BOS", "Gotham", "X", "Out", ""]],
])
def test_parse_rows_refuses_unexpected_shapes(rows):
    with pytest.raises(injuries.ReportFormatError):
        injuries.parse_rows(rows, datetime(2026, 11, 2, 13, tzinfo=ET))


def test_blocking_players_treat_unknown_minutes_as_key(cfg):
    t = datetime(2026, 11, 2, 13, 0, tzinfo=ET)
    tl = injuries.Timeline(injuries.parse_rows(ROWS, t))
    # Brunson is Questionable; Hart (Out) and Tatum (Probable) never block
    assert injuries.blocking_players(tl, ("NYK", "BOS"), None, cfg, t) == ["Brunson, Jalen（Questionable）"]
    assert injuries.listed_players(tl, ("NYK", "BOS"), None, cfg, t) == (
        ["Brunson, Jalen（Questionable）"], [], ["Brunson, Jalen"])            # no minutes: unsupplied
    minutes = {"NYK": {"Brunson, Jalen": [35] * 10, "Hart, Josh": [36] * 10}, "BOS": {"Tatum, Jayson": [37] * 10}}
    assert injuries.blocking_players(tl, ("NYK", "BOS"), minutes, cfg, t) == [
        "Brunson, Jalen（Questionable，本季近 10 場平均 35.0 分鐘）"]
    bench = {"NYK": {"Brunson, Jalen": [12] * 10}}
    assert injuries.blocking_players(tl, ("NYK", "BOS"), bench, cfg, t) == []
    assert injuries.listed_players(tl, ("NYK", "BOS"), bench, cfg, t) == (
        [], ["Brunson, Jalen（Questionable，本季近 10 場平均 12.0 分鐘）"], [])
    # nine games are not a 10-game average, so he still counts as key; of eleven, the last ten count
    nine = {"NYK": {"Brunson, Jalen": [12] * 9}}
    assert injuries.listed_players(tl, ("NYK", "BOS"), nine, cfg, t) == (
        ["Brunson, Jalen（Questionable，本季出賽 9 場）"], [], [])
    eleven = {"NYK": {"Brunson, Jalen": [40] + [12] * 10}}
    assert injuries.blocking_players(tl, ("NYK", "BOS"), eleven, cfg, t) == []
    starter = {"NYK": {"Brunson, Jalen": [12] * 5 + [44] * 5}}           # average 28.0: key
    assert injuries.blocking_players(tl, ("NYK", "BOS"), starter, cfg, t) == [
        "Brunson, Jalen（Questionable，本季近 10 場平均 28.0 分鐘）"]
    assert injuries.listed(tl, ("NYK", "BOS"), cfg, t) == {"NYK": {"Brunson, Jalen"}}
    quiet_rows = [ROWS[0], ["11/02/2026", "07:30 (ET)", "NYK@BOS", "New York Knicks", "Hart, Josh", "Out", "Knee"],
                  ROWS[3]]
    quiet = injuries.Timeline(injuries.parse_rows(quiet_rows, t))                # nobody Questionable or Doubtful
    assert injuries.blocking_players(quiet, ("NYK", "BOS"), None, cfg, t) == []
    two_way = [ROWS[0], ["11/02/2026", "07:30 (ET)", "NYK@BOS", "New York Knicks", "Akins, Jaden", "Questionable",
                         "G League - Two-Way"]]
    tl2 = injuries.Timeline(injuries.parse_rows(two_way, t))
    assert injuries.blocking_players(tl2, ("NYK", "BOS"), None, cfg, t) == []      # Eric 2026-10-23: B


def write_minutes(tmp_path, **changes):
    data = {"schema": "bethero-nba-minutes/1", "slate_et": "2026-11-02", "seen_at": "2026-11-03T07:00:00+08:00",
            "source": "Eric's screenshot of the player's game log, phone clock 7:00 (Taipei)",
            "players": {"NYK": {"Brunson, Jalen": [12] * 10}}}
    data.update(changes)
    path = tmp_path / "minutes.json"
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return path


def test_minutes_transcription_is_checked_and_must_be_from_the_slate_day(cfg, tmp_path):
    m = injuries.load_minutes(write_minutes(tmp_path))
    assert m.players == {"NYK": {"Brunson, Jalen": [12.0] * 10}} and len(m.sha256) == 64
    slate, at = date(2026, 11, 2), datetime(2026, 11, 2, 18, 14, tzinfo=ET)
    assert m.fresh_for(slate, at, cfg)                                  # 07:00 Taipei = 18:00 ET
    at_six = injuries.load_minutes(write_minutes(tmp_path, seen_at="2026-11-02T06:00:00-05:00"))
    assert at_six.fresh_for(slate, at, cfg)
    early = injuries.load_minutes(write_minutes(tmp_path, seen_at="2026-11-02T05:59:00-05:00"))
    assert not early.fresh_for(slate, at, cfg)           # the previous night's late games may be missing
    assert not m.fresh_for(slate, datetime(2026, 11, 2, 17, 0, tzinfo=ET), cfg)   # taken after the analysis
    assert not m.fresh_for(date(2026, 11, 3), datetime(2026, 11, 3, 18, 0, tzinfo=ET), cfg)   # another slate
    alias = injuries.load_minutes(write_minutes(tmp_path, players={"NO": {"Jones, Herbert": [30] * 10}}))
    assert list(alias.players) == ["NOP"]


@pytest.mark.parametrize("changes", [
    {"seen_at": "2026-11-02T18:00:00"},                              # no offset
    {"source": " "},
    {"players": {"Gotham": {"X, Y": [10] * 10}}},
    {"players": {"NYK": {"Brunson, Jalen": [12] * 9 + [-1]}}},
    {"players": {"NYK": {"Brunson, Jalen": [12] * 9 + [True]}}},
    {"players": {"NYK": {"Brunson, Jalen": "12"}}},
    {"players": ["NYK"]},
])
def test_malformed_minutes_are_refused(tmp_path, changes):
    with pytest.raises(injuries.MinutesError):
        injuries.load_minutes(write_minutes(tmp_path, **changes))


def test_final_eligible_windows():
    tip = datetime(2026, 11, 2, 19, 30, tzinfo=ET)
    refs = datetime(2026, 11, 2, 9, 0, tzinfo=ET)
    late = {"NYK": datetime(2026, 11, 2, 11, 30, tzinfo=ET), "BOS": datetime(2026, 11, 2, 12, 0, tzinfo=ET)}
    at = datetime(2026, 11, 2, 13, 0, tzinfo=ET)
    assert injuries.final_eligible(tip, ("NYK", "BOS"), late, refs, at)
    early = dict(late, BOS=datetime(2026, 11, 1, 17, 0, tzinfo=ET))       # only the day-before report
    assert not injuries.final_eligible(tip, ("NYK", "BOS"), early, refs, at)
    assert injuries.final_eligible(tip, ("NYK", "BOS"), early, refs, at, back_to_back_second=frozenset()) is False
    assert not injuries.final_eligible(tip, ("NYK", "BOS"), late, None, at)
    matinee = datetime(2026, 11, 2, 15, 0, tzinfo=ET)
    assert injuries.gameday_window_start("BOS", matinee).hour == 8


# ------------------------------------------------------------------ context

def test_rest_travel_and_calendar_flags(cfg):
    tip = datetime(2026, 11, 13, 19, 30, tzinfo=ET)                           # a Cup night
    schedule = [context.PlayedGame(datetime(2026, 11, 12, 22, 0, tzinfo=ET), "LAL", "BOS"),
                context.PlayedGame(datetime(2026, 11, 10, 19, 0, tzinfo=ET), "MIA", "BOS"),
                context.PlayedGame(datetime(2026, 11, 9, 19, 0, tzinfo=ET), "DEN", "NYK")]
    flags = context.flags_for("DEN", "BOS", tip, schedule, cfg, season_games_played={"DEN": 9, "BOS": 10})
    assert "B2B:BOS" in flags and "3IN4:BOS" in flags
    assert "TRAVEL_TZ:BOS" not in flags                  # Los Angeles -> Denver is one hour
    assert "ALTITUDE" in flags and "CUP_GROUP" in flags and "EARLY_SEASON" in flags
    assert "REST_DIFF" not in flags                       # DEN's last game is outside the 3-day horizon
    assert set(context.material(flags, cfg)) == {"B2B:BOS", "3IN4:BOS", "ALTITUDE", "CUP_GROUP"}


def test_neutral_site_and_inputs(cfg):
    final = datetime(2026, 12, 11, 20, 30, tzinfo=ET)
    flags = context.flags_for("IND", "LAL", final, [], cfg, stars_out={"LAL"}, referee_crew=["A", "B", "C"])
    assert {"NEUTRAL_SITE", "STAR_ABSENT", "REF_CREW"} <= set(flags)


# -------------------------------------------------------------------- model

def synthetic_season(n_games=900, seed=11, hca=2.0, sd=12.0):
    rng = random.Random(seed)
    teams = ["T%02d" % i for i in range(30)]
    true = {t: rng.gauss(0, 5) for t in teams}
    games = []
    for _ in range(n_games):
        home, away = rng.sample(teams, 2)
        margin = round(hca + true[home] - true[away] + rng.gauss(0, sd)) or 1
        games.append(model.GameResult(home, away, 110 + max(margin, 0), 110 + max(-margin, 0)))
    return true, games


def test_ratings_recover_strength_and_home_court():
    true, games = synthetic_season()
    r = model.fit(games, k=1.0)
    assert r.hca == pytest.approx(2.0, abs=1.0)
    centred = {t: v - sum(true.values()) / 30 for t, v in true.items()}
    errors = [abs(r.margin[t] - centred[t]) for t in true]
    assert sum(errors) / len(errors) < 1.5
    assert 0 < r.p_home_win("T00", "T01") < 1


def test_shrinkage_pulls_toward_the_prior():
    _, games = synthetic_season(n_games=60)
    loose, tight = model.fit(games, k=0.1), model.fit(games, k=1000.0)
    spread = lambda rt: max(rt.margin.values()) - min(rt.margin.values())   # noqa: E731
    assert spread(tight) < spread(loose)


def test_metrics():
    assert model.mae([1, 3], [2, 1]) == 1.5
    assert model.brier([0.5, 1.0], [1, 1]) == pytest.approx(0.125)
    assert model.log_loss([0.5], [1]) == pytest.approx(0.6931, abs=1e-4)


# --------------------------------------------------------------------- bias

def obs(day, bias_pts, market="total"):
    return bias.Observation(day, "g", market, 228.5, 228.5 + bias_pts, None, 60, 0.0, None)


def test_bias_needs_n_days_and_a_clear_interval(cfg):
    start = date(2026, 11, 1)
    few = [obs(start + timedelta(days=i), 0.5) for i in range(30)]
    assert bias.estimate(few, cfg).status == "TENTATIVE"            # n < 200
    rng = random.Random(3)
    many = [obs(start + timedelta(days=i % 40), 0.5 + rng.gauss(0, 0.5)) for i in range(400)]
    est = bias.estimate(many, cfg)
    assert est.status == "USABLE" and est.low > 0 and est.days == 40
    noise = [obs(start + timedelta(days=i % 40), rng.gauss(0, 0.5)) for i in range(400)]
    assert bias.estimate(noise, cfg).status == "TENTATIVE"


def test_bias_splits_and_hypotheses(cfg):
    o = bias.Observation(date(2026, 11, 1), "g", "handicap", 8.5, 9.0, True, 30, 0.02, "BOS")
    keys = set(bias.splits([o]))
    assert {"handicap", "handicap:giver_home", "handicap:size_7+", "handicap:tip_<2h"} <= keys
    assert set(bias.hypotheses([o], cfg)) == {"H-MLB-1", "H-MLB-2"}


# ---------------------------------------------------------------------- clv

def test_clv_line_and_us():
    cover = {4.5: 0.56, 5.5: 0.52, 6.5: 0.49}.get
    better = clv.clv_line((Leg(4.5, 1.0),), (Leg(5.5, 1.0),), 0.95, True, cover)
    assert better == pytest.approx(0.04)
    assert clv.clv_line((Leg(4.5, 1.0),), None, 0.95, True, cover) is None
    ev_close, change = clv.clv_us((Leg(4.5, 1.0),), 0.95, True, cover, ev_at_bet=0.08)
    assert ev_close == pytest.approx(0.56 * 1.95 - 1) and change == pytest.approx(ev_close - 0.08)


def test_golive_readiness_is_strict(cfg):
    start = date(2026, 11, 1)
    good = [(start + timedelta(days=i), 0.03 + 0.002 * (i % 3)) for i in range(30)]
    assert clv.golive_check(good, cfg).ready
    assert not clv.golive_check(good[:29], cfg).ready                         # under golive.min_bets
    one_day = [(start, 0.03)] * 40
    assert not clv.golive_check(one_day, cfg).ready                           # under golive.min_slate_days
    unclear = [(start + timedelta(days=i), (-1) ** i * 0.03 + 0.002) for i in range(40)]
    check = clv.golive_check(unclear, cfg)
    assert check.mean > 0 and check.low < 0 and not check.ready              # CI crosses 0: keep shadow


def test_pause_rule(cfg):
    start = date(2026, 11, 1)
    bad = [(start + timedelta(days=i), -0.02 + 0.001 * (i % 3)) for i in range(40)]
    assert clv.pause_check(bad, cfg).paused
    assert not clv.pause_check(bad[:10], cfg).paused                 # under pause_min_n
    mixed = [(start + timedelta(days=i), (-1) ** i * 0.02) for i in range(40)]
    assert not clv.pause_check(mixed, cfg).paused


# ----------------------------------------------------------------- validate

def test_exclusions():
    bubble = HistoryRow("2019-20", date(2020, 8, 1), "A", "B", 1, 0, None, None, "x")
    pre = HistoryRow("2019-20", date(2020, 3, 1), "A", "B", 1, 0, None, None, "x")
    assert validate.excluded(bubble) and not validate.excluded(pre)
    assert validate.excluded(HistoryRow("2020-21", date(2021, 1, 1), "A", "B", 1, 0, None, None, "x"))


def test_timezone_rules_from_brief():
    tip = datetime(2026, 10, 31, 19, 30, tzinfo=ET)
    taipei = ZoneInfo("Asia/Taipei")
    assert tip.astimezone(taipei).strftime("%m-%d %H:%M") == "11-01 07:30"
    assert (tip + timedelta(days=2)).astimezone(taipei).strftime("%H:%M") == "08:30"
    assert datetime(2027, 3, 14, 19, 30, tzinfo=ET).astimezone(taipei).strftime("%H:%M") == "07:30"
    assert tip.astimezone(timezone.utc).hour == 23
