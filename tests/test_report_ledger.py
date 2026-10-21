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
    assert text.count("\n| ") >= 4


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
