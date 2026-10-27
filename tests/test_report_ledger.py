import json
import re

import pytest

from bethero_nba import edge, ledger, report
from tests.helpers import ANALYSIS_TS, REPORT_TS, US_TS, board, context, game_consensus, us_game


def test_reason_codes_match_rules_table(root):
    rules = (root / "rules" / "nba" / "RULES.md").read_text(encoding="utf-8")
    table = re.findall(r"^\| `(NB-[A-Z-]+)` \| G\d+ \| (.+?) \|$", rules, re.M)
    assert [code for code, _ in table] == list(edge.CODES)
    assert dict(table) == edge.CODES


def test_no_bet_report_has_every_market_and_the_transcription(cfg):
    b = board(platform_ts=None, ts_source="unknown")
    ctx = context(cfg, b)
    decisions = edge.evaluate_game(b.games[0], game_consensus(us_game(), cfg), ctx)
    edge.allocate(decisions, cfg)
    text = report.render(decisions, report.ReportMeta(b, ANALYSIS_TS, US_TS, REPORT_TS, "shadow",
                                                      100000, 5000, 0))
    assert "今天沒有合格的注。" in text
    for market in ("讓分", "大小", "獨贏"):
        assert f"| 尼克@塞爾提克 | {market} | NB-STALE | 截圖時間不明 |" in text
    assert "平台截圖 —（時間不明）" in text
    assert "## 抄盤核對" in text and "讓 塞爾提克 4.5 / 0.95" in text
    ev_rows = [line for line in text.splitlines() if line.startswith("| 尼克@塞爾提克 | 塞爾提克讓 4.5")]
    assert len(ev_rows) == 1 and "〔過時〕" in ev_rows[0]           # R-16.5: one EV row per game
    assert text.count("\n| ") >= 4


def test_report_names_markets_held_only_by_listed_players(cfg):
    # handicap and moneyline both pass every other gate here (as in test_one_side_market_per_game)
    b = board(handicap=("2.5", "home", 0.95, 0.95), moneyline=(0.60, 1.30))
    gc = game_consensus(us_game(spreads=[(-160, 140)] * 8, spread_point=-2.5, h2h=[(-300, 250)] * 8), cfg)
    label = b.games[0].label

    def rendered(**ctx):
        decisions = edge.evaluate_game(b.games[0], gc, context(cfg, b, **ctx))
        edge.allocate(decisions, cfg)
        return report.render(decisions, report.ReportMeta(b, ANALYSIS_TS, US_TS, REPORT_TS, "shadow",
                                                          100000, 5000, 0, (10, 28)))

    text = rendered(blocking={label: ["Brunson, Jalen（Questionable）"]})
    assert "今天沒有合格的注。" in text
    held = [line for line in text.splitlines() if line.startswith("- 只差傷病：")]
    assert len(held) == 1                                                  # one line per game
    assert "塞爾提克 讓 2.5（EV +" in held[0] and "塞爾提克 獨贏（EV +" in held[0]
    assert held[0].endswith("被 Brunson, Jalen（Questionable） 擋下。若他本季近 10 場平均上場不到 28 分鐘，"
                            "傳他本季逐場上場時間的截圖，我重算")
    two = rendered(blocking={label: ["Brunson, Jalen（Questionable）", "Hart, Josh（Doubtful）"]})
    assert "若他們本季近 10 場平均上場都不到 28 分鐘，傳他們" in two

    note = "Brunson, Jalen（Questionable，本季近 10 場平均 12.0 分鐘）"
    text = rendered(cleared={label: [note]})
    assert f"替補放行（上場時間來自截圖）：尼克@塞爾提克 {note}" in text
    assert "只差傷病" not in text and "今天沒有合格的注。" not in text


def test_ledger_chain(tmp_path):
    path = tmp_path / "ledger.jsonl"
    ledger.append(path, [{"a": 1}, {"b": "中文"}])
    ledger.append(path, [{"c": 3}])
    records = ledger.verify(path)
    assert [r["sequence"] for r in records] == [1, 2, 3]
    assert records[1]["b"] == "中文"


def test_ledger_detects_edits_and_reserved_keys(tmp_path):
    path = tmp_path / "ledger.jsonl"
    ledger.append(path, [{"stake": 1000}, {"stake": 500}])
    lines = path.read_text(encoding="utf-8").splitlines()
    first = json.loads(lines[0])
    first["stake"] = 2000
    lines[0] = ledger.canonical_json(first)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    with pytest.raises(ledger.LedgerError, match="hash mismatch"):
        ledger.verify(path)
    with pytest.raises(ledger.LedgerError, match="reserved"):
        ledger.append(tmp_path / "other.jsonl", [{"sequence": 9}])
