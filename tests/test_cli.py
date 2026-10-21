"""End-to-end: analyze writes ledger rows and a report; settle settles them. No network."""

import json
import shutil
from datetime import datetime, timezone

import pytest

from bethero_nba import analyze, ledger, net, settle
from tests.helpers import ANALYSIS_TS, HOME, AWAY, TIP, US_TS, us_game


class FakeOpener:
    def __init__(self, payload):
        self.body = json.dumps(payload).encode("utf-8")

    def __call__(self, request, timeout):
        body = self.body

        class R:
            status = 200
            headers = {"x-requests-remaining": "400"}

            def read(self):
                return body

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False
        return R()


def store(root, payload, when):
    client = net.HttpClient(root / "data" / "raw", live=True, user_agent="t", min_interval_s=0,
                            opener=FakeOpener(payload), now=lambda: when)
    return client.get("https://api.the-odds-api.com/v4/x").path


def odds_payload():
    g = us_game(spreads=[(-110, -110)] * 8, spread_point=-2.5, h2h=[(-300, 250)] * 8)
    books = {}
    for q in g.quotes:
        b = books.setdefault(q.book, {"key": q.book, "title": q.book, "last_update": q.last_update.isoformat(),
                                      "markets": {}})
        m = b["markets"].setdefault(q.market, {"key": q.market, "last_update": q.last_update.isoformat(),
                                               "outcomes": []})
        out = {"name": q.side, "price": q.american}
        if q.point is not None:
            out["point"] = q.point
        m["outcomes"].append(out)
    for b in books.values():
        b["markets"] = list(b["markets"].values())
    return [{"id": "g1", "commence_time": TIP.astimezone(timezone.utc).isoformat(), "home_team": HOME,
             "away_team": AWAY, "bookmakers": list(books.values())}]


@pytest.fixture
def repo(tmp_path, root):
    (tmp_path / "rules" / "nba").mkdir(parents=True)
    shutil.copy(root / "rules" / "nba" / "config.yaml", tmp_path / "rules" / "nba" / "config.yaml")
    board = {"schema": "bethero-nba-board/1", "slate_et": "2026-11-02",
             "platform_ts": "2026-11-03T07:10:00+08:00", "ts_source": "screenshot_clock", "source": "test",
             "games": [{"tip": TIP.isoformat(), "home": "BOS", "away": "NYK",
                        "handicap": {"text": "2.5", "row": "home", "price_home": 0.95, "price_away": 0.95},
                        "total": {"text": "大228.5", "price_over": 0.94, "price_under": 0.94},
                        "moneyline": {"price_home": 0.60, "price_away": 1.30}, "unresolved": []}]}
    path = tmp_path / "data" / "boards" / "2026-11-02" / "board.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(board, ensure_ascii=False), encoding="utf-8")
    injuries = {"report_time": "2026-11-03T06:45:00+08:00", "referees_posted_at": "2026-11-02T22:00:00+08:00",
                "submissions": {"BOS": "2026-11-03T01:00:00+08:00", "NYK": "2026-11-03T01:00:00+08:00"},
                "statuses": [], "minutes": {"BOS": {}, "NYK": {}}}
    (tmp_path / "injuries.json").write_text(json.dumps(injuries), encoding="utf-8")
    return tmp_path, path, store(tmp_path, odds_payload(), US_TS.astimezone(timezone.utc))


def test_analyze_then_settle(repo):
    tmp, board_path, snapshot = repo
    code = analyze.main(["--root", str(tmp), "--board", str(board_path), "--odds", str(snapshot),
                         "--injuries", str(tmp / "injuries.json"), "--now", ANALYSIS_TS.isoformat()])
    assert code == 0
    records = ledger.verify(tmp / "logs" / "ledger.jsonl")
    assert records[0]["record_type"] == "pass" and records[0]["decisions"] == 6
    bets = [r for r in records if r.get("record_type") == "decision" and not r["codes"] and r["stake"]]
    assert len(bets) == 1 and bets[0]["market"] == "moneyline"     # US home ~73% vs platform 0.60
    assert list((tmp / "reports" / "2026-11-02").glob("*.md"))

    scores = [{"id": "g1", "commence_time": TIP.astimezone(timezone.utc).isoformat(), "completed": True,
               "home_team": HOME, "away_team": AWAY,
               "scores": [{"name": HOME, "score": "112"}, {"name": AWAY, "score": "104"}]}]
    scores_path = store(tmp, scores, datetime(2026, 11, 3, 6, 0, tzinfo=timezone.utc))
    assert settle.main(["--root", str(tmp), "--slate", "2026-11-02", "--scores", str(scores_path),
                        "--close-odds", str(snapshot)]) == 0
    settled = [r for r in ledger.verify(tmp / "logs" / "ledger.jsonl") if r.get("record_type") == "settlement"]
    assert len(settled) == 1
    assert settled[0]["return_per_unit"] == pytest.approx(0.60)
    assert settled[0]["clv_us"] is not None


def test_realised_return_on_a_tail_line():
    record = {"market": "handicap", "side": "home", "laying": True,
              "platform": {"legs": [[4.5, 0.5], [5.0, 0.5]], "price": 0.95}}
    assert settle.realised(record, 105, 100) == pytest.approx(0.475)       # Eric's confirmed case
    assert settle.realised({**record, "side": "away", "laying": False}, 105, 100) == pytest.approx(-0.5)
    assert settle.realised(record, 110, 100) == pytest.approx(0.95)
