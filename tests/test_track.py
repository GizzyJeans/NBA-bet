"""The tracking report (RULES R-14.6): settled results and CLV_US by EV threshold. No network."""

import shutil
from datetime import date, datetime, timedelta, timezone

import pytest

from bethero_nba import boxscores, ledger, net, track
from tests.helpers import TIP, US_TS, box_season
from tests.test_cli import FakeOpener, odds_payload

ODDS_URL = "https://api.the-odds-api.com/v4/sports/basketball_nba/odds/"


def decision(market, side, laying, legs, price, ev, text, home="BOS", away="NYK", codes=("NB-EV",)):
    return {"record_type": "decision", "game": {"home": home, "away": away, "tip": TIP.isoformat()},
            "market": market, "side": side, "laying": laying,
            "platform": {"legs": legs, "price": price, "text": text},
            "ev": {"shin": ev, "power": ev + 0.002, "multiplicative": ev + 0.004} if ev is not None else {},
            "p_eff": {"shin": 0.52, "power": 0.52, "multiplicative": 0.52}, "worst_method": "shin",
            "codes": list(codes), "primary": codes[0] if codes else None, "tier": "A"}


def records():
    first = [{"record_type": "pass", "slate_et": "2026-11-02"},
             decision("handicap", "home", True, [[2.5, 1.0]], 0.95, -0.03, "2.5")]     # superseded below
    second = [{"record_type": "pass", "slate_et": "2026-11-02"},
              decision("handicap", "home", True, [[2.5, 1.0]], 0.95, 0.015, "2.5"),
              decision("handicap", "away", False, [[2.5, 1.0]], 0.95, -0.06, "2.5"),
              decision("total", "over", True, [[228.5, 1.0]], 0.94, -0.05, "大228.5"),
              decision("total", "under", False, [[228.5, 1.0]], 0.94, 0.005, "大228.5"),
              decision("moneyline", "home", True, [], 0.60, -0.005, "-"),
              decision("moneyline", "away", False, [], 1.30, -0.09, "-"),
              decision("moneyline", "away", False, [], 1.30, None, "-", home="MIA", away="ORL",
                       codes=("NB-NOT-OFFERED",)),                                  # no EV: not a side
              decision("handicap", "home", True, [[3.5, 1.0]], 0.95, 0.02, "3.5", home="MIA", away="ORL")]
    return first + second


@pytest.fixture
def scores(cfg):
    return boxscores.parse(*box_season(games=1, start=date(2026, 11, 2)), 2027, cfg)    # BOS 100, NY 90


def sides_by_key(sides):
    return {(s.record["game"]["home"], s.record["market"], s.record["side"]): s for s in sides}


def test_latest_sides_settle_on_checked_finals(cfg, scores):
    assert scores.finals == {("BOS", "NYK", date(2026, 11, 2)): (100, 90)}
    sides = track.latest_sides(records())
    assert len(sides) == 7                                   # the earlier pass and the no-EV row drop out
    track.settle_sides(sides, scores.finals)
    by = sides_by_key(sides)
    assert by[("BOS", "handicap", "home")].ev == pytest.approx(0.015)     # the later pass wins
    assert (by[("BOS", "handicap", "home")].won, by[("BOS", "handicap", "home")].ret) == (1.0, pytest.approx(0.95))
    assert by[("BOS", "total", "under")].ret == pytest.approx(0.94)       # 190 < 228.5
    assert by[("BOS", "moneyline", "away")].lost == 1.0
    assert not by[("MIA", "handicap", "home")].settled                    # no final score: pending


def test_thresholds_count_settled_sides_above_each(cfg, scores):
    sides = track.latest_sides(records())
    track.settle_sides(sides, scores.finals)
    above = {t: track.summarize([s for s in sides if s.ev > t / 100], cfg) for t in track.THRESHOLDS}
    assert (above[1.0].n, above[0.0].n, above[-1.0].n) == (1, 2, 3)
    assert above[-1.0].won == 3 and above[-1.0].hit == 1.0
    assert above[-1.0].roi == pytest.approx((0.95 + 0.94 + 0.60) / 3)
    low, high = track.wilson(3, 3)
    assert (above[-1.0].hit_low, above[-1.0].hit_high) == (pytest.approx(low), pytest.approx(high))
    assert track.summarize([s for s in sides if s.ev > 0.05], cfg) is None


def store_odds(root, payload, when):
    client = net.HttpClient(root / "data" / "raw", live=True, user_agent="t", min_interval_s=0,
                            opener=FakeOpener(payload), now=lambda: when)
    return client.get(ODDS_URL).path


def close_payload(when):
    return odds_payload(age_min=-(when - US_TS).total_seconds() / 60 + 2)


def test_clv_comes_from_the_last_snapshot_in_the_close_window(cfg, scores, tmp_path):
    sides = track.latest_sides(records())
    for minutes in (40, 10, -5):                             # too early, the close, after tip
        when = TIP - timedelta(minutes=minutes)
        store_odds(tmp_path, close_payload(when), when.astimezone(timezone.utc))
    snapshots = track.stored_snapshots(tmp_path / "data" / "raw")
    assert len(snapshots) == 3
    track.add_clv(sides, snapshots, cfg)
    by = sides_by_key(sides)
    assert by[("BOS", "handicap", "home")].clv_us == pytest.approx(0.5 * 0.95 - 0.5)   # -110 both ways at 2.5
    assert by[("BOS", "total", "under")].clv_us == pytest.approx(0.5 * 0.94 - 0.5)
    assert by[("MIA", "handicap", "home")].clv_us is None    # not in the snapshot


def test_no_snapshot_in_the_window_means_no_clv(cfg, tmp_path):
    sides = track.latest_sides(records())
    when = TIP - timedelta(minutes=40)
    store_odds(tmp_path, close_payload(when), when.astimezone(timezone.utc))
    track.add_clv(sides, track.stored_snapshots(tmp_path / "data" / "raw"), cfg)
    assert all(s.clv_us is None for s in sides)


def test_command_writes_the_report(root, tmp_path):
    (tmp_path / "rules" / "nba").mkdir(parents=True)
    shutil.copy(root / "rules" / "nba" / "config.yaml", tmp_path / "rules" / "nba" / "config.yaml")
    ledger.append(tmp_path / "logs" / "ledger.jsonl", records())
    box, schedule = box_season(games=1, start=date(2026, 11, 2))
    paths = []
    for name, body in (("player_box_2027.csv", box), ("nba_schedule_2027.csv", schedule)):
        class Opener(FakeOpener):
            def __init__(self, text):
                self.body = text.encode("utf-8")
        client = net.HttpClient(tmp_path / "data" / "raw", live=True, user_agent="t", min_interval_s=0,
                                opener=Opener(body), now=lambda: datetime(2026, 11, 9, 9, 0, tzinfo=timezone.utc))
        paths.append(str(client.get(f"https://github.com/x/{name}").path))
    assert track.main(["--root", str(tmp_path), "--box-scores", *paths,
                       "--now", "2026-11-09T09:00:00+00:00"]) == 0
    text = (tmp_path / "reports" / "tracking" / "20261109T090000Z.md").read_text(encoding="utf-8")
    assert "| EV > +1% | 1 | 1–0–0 |" in text and "| EV > −1% | 3 | 3–0–0 |" in text
    assert "未結算 1" in text and "CC BY 4.0" in text
