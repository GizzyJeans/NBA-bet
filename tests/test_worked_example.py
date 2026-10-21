"""RULES §18 reproduced by the engine. If this fails, either the code or the
rulebook is wrong, and RULES.md wins (cc_npb AGENT.md convention)."""

import pytest

from bethero_nba import edge, report
from tests.helpers import (ANALYSIS_TS, HypotheticalTierB, REPORT_TS, US_TS, board, context,
                           game_consensus, us_game, with_values)


@pytest.fixture
def worked(cfg):
    cfg = with_values(cfg, **{"distribution.status": "VALIDATED"})
    b = board()
    gc = game_consensus(us_game(), cfg)
    ctx = context(cfg, b, tier_b=HypotheticalTierB())
    decisions = edge.evaluate_game(b.games[0], gc, ctx)
    edge.allocate(decisions, cfg)
    for d in decisions:
        if d.is_bet:
            d.worst_line = edge.worst_acceptable(d, gc, ctx)
    return cfg, b, gc, ctx, decisions


def pick(decisions, market, side):
    return next(d for d in decisions if d.market == market and d.side == side)


def test_the_bet(worked):
    *_, decisions = worked
    d = pick(decisions, "handicap", "home")
    assert d.codes == [] and d.tier == "B"
    assert d.worst_method == "multiplicative"
    assert d.p_worst == pytest.approx(0.5557, abs=1e-4)
    assert d.ev_worst == pytest.approx(0.0837, abs=1e-4)
    assert d.ev["shin"] == pytest.approx(0.0856, abs=1e-4)
    assert d.ev["power"] == pytest.approx(0.0866, abs=1e-4)
    assert d.sigma["books"] == pytest.approx(0.0025, abs=1e-4)
    assert d.sigma["translate"] == pytest.approx(0.0045, abs=1e-4)
    assert d.sigma["ev"] == pytest.approx(0.0102, abs=1e-4)
    assert d.divergence == pytest.approx(0.0557, abs=1e-4)
    assert d.kelly == pytest.approx(0.0881, abs=1e-4)
    assert d.stake == 1000
    assert d.confidence == "Medium" and d.edge_label == "LAG"
    assert 6.0 < d.fair_line < 6.5
    assert d.model_d == pytest.approx(0.5)


def test_worst_acceptable_line_uses_tail_steps(worked):
    """With tail lines confirmed (0.2.0) the threshold is 5-30, not 5平 (ERRATA E-003)."""
    *_, decisions = worked
    assert pick(decisions, "handicap", "home").worst_line == "讓 5-30"


def test_everything_else_is_no_bet(worked):
    *_, decisions = worked
    assert pick(decisions, "handicap", "away").primary == "NB-EV"
    over = pick(decisions, "total", "over")
    assert over.tier == "A" and over.primary == "NB-EV"
    assert over.ev_worst == pytest.approx(-0.03, abs=1e-6)
    assert pick(decisions, "moneyline", "home").primary == "NB-EV"
    assert sum(d.is_bet for d in decisions) == 1


def test_report_row_matches_the_rulebook(worked):
    cfg, b, gc, ctx, decisions = worked
    text = report.render(decisions, report.ReportMeta(
        b, ANALYSIS_TS, US_TS, REPORT_TS, "shadow", 100000, 5000, 0))
    assert "| 尼克@塞爾提克 08:30 | 塞爾提克 讓 4.5 | 4.5 / 0.95 | 55.6% | +8.4% (±1.0) | 1,000 | 中 |" in text
    assert "Tier B（美盤 -5.5 換算）｜LAG｜情境：無｜最差可接受：讓 5-30" in text
    assert "本金 100,000｜今日已用 1,000 / 5,000" in text
    assert "| 尼克@塞爾提克 | 大小 | NB-EV | EV -3.0% |" in text
