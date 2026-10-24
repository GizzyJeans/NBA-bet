import copy
import json

import pytest

from bethero_nba import platform
from bethero_nba.odds import Leg
from bethero_nba.platform import LineKind, notation_status, parse_line

SAMPLE = "data/boards/2026-10-21/sample_ts-unknown.json"


@pytest.mark.parametrize("text, kind, legs, effective", [
    ("2.5", LineKind.HALF, (Leg(2.5, 1.0),), 2.5),
    ("大238.5", LineKind.HALF, (Leg(238.5, 1.0),), 238.5),
    ("大235平", LineKind.FLAT, (Leg(235.0, 1.0),), 235.0),
    ("5+50", LineKind.TAIL, (Leg(4.5, 0.5), Leg(5.0, 0.5)), 4.75),
    ("5-30", LineKind.TAIL, (Leg(5.0, 0.7), Leg(5.5, 0.3)), 5.15),
    ("1+95", LineKind.TAIL, (Leg(0.5, 0.95), Leg(1.0, 0.05)), 0.525),
    ("0-50", LineKind.TAIL, (Leg(0.0, 0.5), Leg(0.5, 0.5)), 0.25),
    ("225－40", LineKind.TAIL, (Leg(225.0, 0.6), Leg(225.5, 0.4)), 225.2),   # full-width minus
])
def test_notation_golden(text, kind, legs, effective):
    line = parse_line(text)
    assert line.kind is kind
    assert len(line.legs) == len(legs)
    for got, want in zip(line.legs, legs):
        assert got.line == pytest.approx(want.line) and got.weight == pytest.approx(want.weight)
    assert line.effective == pytest.approx(effective)


@pytest.mark.parametrize("text, kind", [
    ("-", LineKind.NOT_OFFERED),
    ("235", LineKind.BARE),
    ("5+5", LineKind.UNREADABLE),       # one-digit tail
    ("5+00", LineKind.UNREADABLE),
    ("4.75", LineKind.UNREADABLE),
    ("5/5.5", LineKind.UNREADABLE),
    ("", LineKind.UNREADABLE),
])
def test_notation_refusals(text, kind):
    assert parse_line(text).kind is kind


def test_notation_status_follows_config(cfg):
    assert platform.notation_status(parse_line("2.5"), cfg) == "CONFIRMED"
    assert platform.notation_status(parse_line("235平"), cfg) == "CONFIRMED"
    assert platform.notation_status(parse_line("5+50"), cfg) == "CONFIRMED"
    assert platform.notation_status(parse_line("235"), cfg) == "UNCONFIRMED"
    assert platform.notation_status(parse_line("5+5"), cfg) == "UNREADABLE"


def test_erics_real_board(root):
    board = platform.load_board(root / SAMPLE)
    assert board.ts_source == "unknown" and board.platform_ts is None
    orl, was = board.games
    assert (orl.home.tricode, orl.away.tricode) == ("ORL", "ATL")
    assert orl.handicap.giver == "home" and orl.handicap.line.effective == 2.5
    assert orl.total.line.kind is LineKind.FLAT and orl.total.prices == {"over": 0.94, "under": 0.94}
    assert not orl.moneyline.offered
    assert was.handicap.line.effective == pytest.approx(4.75)
    assert was.moneyline.prices == {"home": 0.56, "away": 1.4}
    assert platform.moneyline_conflict(was) is None
    assert orl.tip.utcoffset().total_seconds() == 8 * 3600


def test_moneyline_conflict_detected(root):
    data = json.loads((root / SAMPLE).read_text(encoding="utf-8"))
    data["games"][1]["moneyline"] = {"price_home": 1.4, "price_away": 0.56}
    game = platform.parse_board(data).games[1]
    assert "favours away" in platform.moneyline_conflict(game)


def test_unresolved_marks_only_that_market(root):
    data = json.loads((root / SAMPLE).read_text(encoding="utf-8"))
    data["games"][0]["unresolved"] = ["total.price_over"]
    game = platform.parse_board(data).games[0]
    assert game.total.unresolved and not game.handicap.unresolved


@pytest.mark.parametrize("mutate, message", [
    (lambda d: d.update(schema="other"), "schema"),
    (lambda d: d.update(ts_source="guess"), "ts_source"),
    (lambda d: d.update(platform_ts="2026-10-22T06:40:00+08:00"), "null exactly"),
    (lambda d: d["games"][0].update(home="XYZ"), "unknown team"),
    (lambda d: d["games"][0]["handicap"].update(price_home=0), "positive number"),
    (lambda d: d["games"][0]["handicap"].update(row="top"), "row"),
    (lambda d: d["games"][0].update(tip="2026-10-22T07:05:00"), "offset"),
    (lambda d: d.update(slate_et="2026-10-22"), "Eastern date"),
])
def test_board_schema_errors(root, mutate, message):
    data = json.loads((root / SAMPLE).read_text(encoding="utf-8"))
    broken = copy.deepcopy(data)
    mutate(broken)
    with pytest.raises(platform.BoardError, match=message):
        platform.parse_board(broken)


def test_zero_is_a_confirmed_pickem(cfg):
    line = parse_line("0")                          # Eric 2026-10-25: 0是平手盤，誰贏誰贏
    assert line.kind is LineKind.PICKEM and line.effective == 0.0
    assert notation_status(line, cfg) == "CONFIRMED"
    assert parse_line("1").kind is LineKind.BARE    # other bare integers stay unconfirmed
