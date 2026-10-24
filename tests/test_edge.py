"""Each gate in isolation, in RULES order, plus allocation."""

from datetime import timedelta

import pytest

from bethero_nba import edge
from tests.helpers import (HypotheticalTierB, TIP, US_TS, board, context, game_consensus,
                           us_game, with_values)


def run(cfg, b=None, gc="default", exposure=0.0, **ctx_overrides):
    b = b or board()
    if gc == "default":
        gc = game_consensus(us_game(), cfg)
    ctx = context(cfg, b, **ctx_overrides)
    decisions = edge.evaluate_game(b.games[0], gc, ctx)
    edge.allocate(decisions, cfg, exposure)
    return {(d.market, d.side): d for d in decisions}


@pytest.fixture
def validated(cfg):
    return with_values(cfg, **{"distribution.status": "VALIDATED",
                               "distribution.validated_markets": ["spreads", "totals"]})


def tier_b():
    return HypotheticalTierB()


def test_not_offered_is_logged(cfg):
    ds = run(cfg, board(moneyline=("-", "-")))
    assert ds[("moneyline", "home")].codes == ["NB-NOT-OFFERED"]


@pytest.mark.parametrize("text", ["235", "4.75", "5+5"])
def test_unreadable_or_unconfirmed_notation_is_nb_format(cfg, text):
    ds = run(cfg, board(handicap=(text, "home", 0.95, 0.95)))
    assert ds[("handicap", "home")].primary == "NB-FORMAT"


def test_unresolved_transcription_is_nb_format(cfg):
    ds = run(cfg, board(unresolved=["handicap.text"]))
    assert ds[("handicap", "home")].primary == "NB-FORMAT"
    assert ds[("total", "over")].primary != "NB-FORMAT"


def test_settlement_gate_follows_config(cfg):
    unconfirmed = with_values(cfg, **{"platform.notation.tail_line": None})
    unconfirmed.data["platform"]["notation"]["tail_line"]["status"] = "UNCONFIRMED"
    ds = run(unconfirmed, board(handicap=("5+50", "home", 0.95, 0.95)))
    assert ds[("handicap", "home")].primary == "NB-SETTLEMENT"


def test_unknown_screenshot_time_is_stale(cfg):
    ds = run(cfg, board(platform_ts=None, ts_source="unknown"))
    assert all(d.primary in ("NB-STALE",) for k, d in ds.items())


def test_skew_over_limit_is_stale(cfg):
    b = board(platform_ts=US_TS - timedelta(minutes=21))
    assert run(cfg, b)[("total", "over")].primary == "NB-STALE"
    b = board(platform_ts=US_TS - timedelta(minutes=19))
    assert run(cfg, b)[("total", "over")].primary != "NB-STALE"


def test_after_tip_is_stale(cfg):
    ds = run(cfg, analysis_ts=TIP + timedelta(minutes=1))
    assert ds[("total", "over")].primary == "NB-STALE"


def test_old_injury_report_is_stale(cfg):
    ds = run(cfg, injury_report_ts=US_TS - timedelta(minutes=45))
    assert ds[("total", "over")].primary == "NB-STALE"


def test_missing_us_game_is_nb_data(cfg):
    assert run(cfg, gc=None)[("handicap", "home")].primary == "NB-DATA"


def test_too_few_books_is_nb_data(cfg):
    gc = game_consensus(us_game(spreads=[(-110, -110)] * 7), cfg)
    assert run(cfg, gc=gc)[("handicap", "home")].primary == "NB-DATA"


def test_board_moneyline_conflict_is_nb_data(cfg):
    ds = run(cfg, board(moneyline=(1.75, 0.45)))
    assert ds[("handicap", "home")].primary == "NB-DATA"
    assert ds[("moneyline", "home")].primary == "NB-DATA"
    assert ds[("total", "over")].primary != "NB-DATA"


def test_large_gap_is_sanity_unless_explained(validated):
    b = board(handicap=("1.5", "home", 0.95, 0.95))       # fair ~6.2, gap > 3
    assert run(validated, b, tier_b=tier_b(), lag=lambda g, m: False)[("handicap", "home")].primary == "NB-SANITY"
    explained = run(validated, b, tier_b=tier_b())[("handicap", "home")]
    assert "NB-SANITY" not in explained.codes and explained.primary == "NB-TIER-C"


def test_direction_conflict_is_sanity(cfg):
    ds = run(cfg, board(handicap=("4.5", "away", 0.95, 0.95), moneyline=("-", "-")))
    assert "NB-SANITY" in ds[("handicap", "away")].codes


def test_translation_needs_a_validated_distribution(cfg, validated):
    unvalidated = with_values(cfg, **{"distribution.status": "UNAVAILABLE", "distribution.validated_markets": []})
    assert run(unvalidated)[("handicap", "home")].primary == "NB-TIER-C"
    assert run(unvalidated, tier_b=tier_b())[("handicap", "home")].primary == "NB-TIER-C"   # not VALIDATED
    assert run(validated, tier_b=tier_b())[("handicap", "home")].codes == []
    totals_only = with_values(validated, **{"distribution.validated_markets": ["totals"]})
    assert run(totals_only, tier_b=tier_b())[("handicap", "home")].primary == "NB-TIER-C"


def test_failed_anchoring_fails_closed(validated):
    class Unanchorable(HypotheticalTierB):
        def anchored(self, market, ref_line, p_ref):
            raise ValueError("no history near this line")
    d = run(validated, tier_b=Unanchorable())[("handicap", "home")]
    assert d.primary == "NB-TIER-C" and d.fair_source == "l_ref"


def test_tier_b_gap_limit(validated):
    b = board(handicap=("3.5", "home", 0.95, 0.95))        # 2 points from -5.5 > 1.5
    assert run(validated, b, tier_b=tier_b())[("handicap", "home")].primary == "NB-TIER-C"


@pytest.mark.parametrize("override, note", [
    ({"final_eligible": {}}, "當日傷病報告"),
    ({"blocking": None}, "拿不到傷病報告"),
    ({"blocking": {"NYK@BOS": ["Brunson"]}}, "Brunson"),
])
def test_status_gate(validated, override, note):
    d = run(validated, tier_b=tier_b(), **override)[("handicap", "home")]
    assert d.primary == "NB-STATUS" and any(note in n for n in d.notes)


def test_ev_gate_and_noise(validated):
    d = run(validated, tier_b=tier_b())[("handicap", "away")]
    assert d.primary == "NB-EV" and d.ev_worst < 0


def test_book_agreement_blocks_an_edge_three_books_dispute(cfg):
    # Five books make the over ~56%, three make it ~45%: the median says +9% EV,
    # but only 5 of 8 books agree, under the 75% bar (MLB gate 2B).
    totals = [(228.5, -141, 118)] * 5 + [(228.5, 113, -135)] * 3
    gc = game_consensus(us_game(totals=totals), cfg)
    d = run(cfg, gc=gc)[("total", "over")]
    assert d.tier == "A" and d.ev_worst > 0.04
    assert d.agreement == pytest.approx(5 / 8)
    assert "NB-EV" in d.codes and any("書商同意" in n for n in d.notes)


def test_divergence_gate_on_unequal_prices(cfg):
    # US: home wins 60%. Platform: home 0.80, away 1.50 (an overly generous away price),
    # so the platform's own no-vig is 58.1% and divergence is under 3pp despite EV of 8%.
    probs = [(-150, 150)] * 8
    gc = game_consensus(us_game(h2h=probs), cfg)
    d = run(cfg, board(moneyline=(0.80, 1.50)), gc=gc)[("moneyline", "home")]
    assert d.ev_worst > 0.04
    assert "NB-DIVERGENCE" in d.codes


def test_model_veto_and_downgrade(validated):
    validated = with_values(validated, **{"model.model_veto_pts": {"spread": 3.0, "total": 6.0},
                                          "model.model_downgrade_pts": {"spread": 1.5, "total": 3.0}})
    vetoed = run(validated, tier_b=tier_b(), model=lambda g: {"home_margin": 0.5, "total": 228})
    assert vetoed[("handicap", "home")].primary == "NB-MODEL-VETO"
    downgraded = run(validated, tier_b=tier_b(), model=lambda g: {"home_margin": 2.5, "total": 228})
    d = downgraded[("handicap", "home")]
    assert d.codes == [] and d.downgrade and d.confidence == "Low"


def test_model_agreement_never_raises_the_stake(validated):
    keen = run(validated, tier_b=tier_b(), model=lambda g: {"home_margin": 15.0, "total": 228})
    neutral = run(validated, tier_b=tier_b(), model=lambda g: {"home_margin": 5.0, "total": 228})
    assert keen[("handicap", "home")].stake == neutral[("handicap", "home")].stake
    assert keen[("handicap", "home")].confidence == neutral[("handicap", "home")].confidence


def test_one_side_market_per_game(cfg):
    # Both the handicap (US home -2.5 at -160) and the moneyline (US home ~73%
    # vs platform 0.60) clear every gate; only one may be bet (G11).
    gc = game_consensus(us_game(spreads=[(-160, 140)] * 8, spread_point=-2.5,
                                h2h=[(-300, 250)] * 8), cfg)
    ds = run(cfg, board(handicap=("2.5", "home", 0.95, 0.95), moneyline=(0.60, 1.30)), gc=gc)
    hcap, ml = ds[("handicap", "home")], ds[("moneyline", "home")]
    assert {hcap.tier, ml.tier} == {"A"}
    assert sorted([hcap.codes, ml.codes]) == [[], ["NB-CORR"]]
    kept = hcap if not hcap.codes else ml
    dropped = ml if kept is hcap else hcap
    assert kept.ev_lower(1.0) >= dropped.ev_lower(1.0) and kept.stake == 1000


def test_caps(validated):
    full = run(validated, tier_b=tier_b(), exposure=4950)
    assert full[("handicap", "home")].primary == "NB-CAP"
    partial = run(validated, tier_b=tier_b(), exposure=4500)
    assert partial[("handicap", "home")].stake == 500
    strict = with_values(validated, **{"platform.min_stake": 1500})
    assert run(strict, tier_b=tier_b())[("handicap", "home")].primary == "NB-MIN-STAKE"


def test_paused_mode_blocks_everything(validated):
    paused = with_values(validated, mode="paused")
    ds = run(paused, tier_b=tier_b())
    assert all("NB-PAUSED" in d.codes for d in ds.values())


def test_notation_for_effective_lines():
    assert edge.notation_for(5.0).raw == "5平"
    assert edge.notation_for(4.75).raw == "5+50"
    assert edge.notation_for(5.15).raw == "5-30"
    assert edge.notation_for(5.5).raw == "5.5"
    assert edge.notation_for(-0.25) is None


def test_decision_record_is_serialisable(validated):
    import json
    d = run(validated, tier_b=tier_b())[("handicap", "home")]
    ctx = context(validated, board(), tier_b=tier_b())
    record = d.to_record(ctx)
    assert json.loads(json.dumps(record))["stake"] == 1000


def test_injury_waiver_is_slate_scoped_and_recorded(validated):
    blocked = {"blocking": {"NYK@BOS": ["Brunson"]}}
    waived = with_values(validated, **{"injuries.waived_slates": ["2026-11-02"]})     # the slate of TIP
    d = run(waived, tier_b=tier_b(), **blocked)[("handicap", "home")]
    assert "NB-STATUS" not in d.codes and d.waivers == ["injury"] and "Brunson" in d.waived[0]
    assert not any("傷病放行" in n for n in d.notes)                    # the primary code keeps its note
    other = with_values(validated, **{"injuries.waived_slates": ["2026-11-03"]})
    assert run(other, tier_b=tier_b(), **blocked)[("handicap", "home")].primary == "NB-STATUS"
