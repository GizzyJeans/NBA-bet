"""Distribution machinery on synthetic history with a known answer."""

import random
from datetime import date

import pytest

from bethero_nba import dist
from bethero_nba.dist import EmpiricalFamily, HistoryRow, NormalFamily


def synthetic(n=6000, seed=7, sigma=12.0):
    """Home margins ~ round(N(-spread, sigma)), never 0 (overtime settles ties)."""
    rng = random.Random(seed)
    rows = []
    for i in range(n):
        spread = rng.choice([-9.5, -7.5, -5.5, -5.0, -3.5, -1.5, 1.5, 3.5, 6.5])
        margin = 0
        while margin == 0:
            margin = round(rng.gauss(-spread, sigma))
        home = 110 + margin if margin > 0 else 110
        away = home - margin
        total_line = 228.5
        rows.append(HistoryRow("2024-25", date(2025, 1, 1), "BOS", "NYK", home, away,
                               spread, total_line, "synthetic"))
    return rows


def test_empirical_family_recovers_the_generating_masses():
    rows = synthetic()
    fam = EmpiricalFamily.fit(rows, "spreads", bucket_width=0.5, bandwidth=0.25)
    pmf = fam.pmf(-5.5)
    assert sum(pmf.values()) == pytest.approx(1.0)
    assert 0 not in pmf
    assert dist.cover_from_pmf(pmf, 5.5) == pytest.approx(0.5, abs=0.05)
    assert fam.effective_n(-5.5) > 500


def test_normal_family_fit_and_no_tie_mass():
    rows = synthetic()
    fam = NormalFamily.fit(rows, "spreads")
    assert fam.sigma == pytest.approx(12.0, abs=0.6)
    pmf = fam.pmf(-5.5)
    assert 0 not in pmf and sum(pmf.values()) == pytest.approx(1.0)


@pytest.mark.parametrize("p_ref", [0.45, 0.5217, 0.58])
def test_anchor_reproduces_the_consensus(p_ref):
    fam = NormalFamily("spreads", 12.0)
    anchored = dist.anchor(fam, -5.5, p_ref)
    assert anchored.cover(5.5) == pytest.approx(p_ref, abs=1e-6)
    assert anchored.cover(4.5) > anchored.cover(5.5) > anchored.cover(6.5)


def test_anchor_on_an_integer_reference_uses_the_no_push_share():
    fam = NormalFamily("spreads", 12.0)
    anchored = dist.anchor(fam, -6.0, 0.51)
    win, push = anchored.cover(6.0), anchored.pmf.get(6, 0.0)
    assert win / (1 - push) == pytest.approx(0.51, abs=1e-6)


def test_anchor_totals_direction():
    fam = NormalFamily("totals", 18.0)
    low, high = dist.anchor(fam, 228.5, 0.45), dist.anchor(fam, 228.5, 0.55)
    assert high.s_star > low.s_star
    assert high.fair_point() > 228.5 > low.fair_point()


def test_sigma_translate_grows_with_distance():
    fam = NormalFamily("spreads", 12.0)
    primary = dist.anchor(fam, -5.5, 0.52)
    primary = dist.Anchored(primary.pmf, primary.s_star, 1500.0)
    alternative = dist.anchor(NormalFamily("spreads", 13.0), -5.5, 0.52)
    near = dist.sigma_translate(primary, alternative, 5.5, 4.5)
    far = dist.sigma_translate(primary, alternative, 5.5, 2.5)
    assert 0 < near < far


def test_history_csv_round_trip(tmp_path):
    path = tmp_path / "games.csv"
    path.write_text(",".join(dist.HISTORY_COLUMNS) + "\n"
                    "2024-25,2025-01-01,BOS,NYK,112,108,-5.5,228.5,test\n", encoding="utf-8")
    rows = dist.load_history(path)
    assert rows[0].margin == 4 and rows[0].total == 220 and rows[0].close_spread_home == -5.5
    bad = tmp_path / "bad.csv"
    bad.write_text("season,date\n", encoding="utf-8")
    with pytest.raises(ValueError, match="missing columns"):
        dist.load_history(bad)


def test_anchoring_a_big_line_stays_inside_the_history():
    """A 15.5-point line: a ±15 window would ask the empirical family about
    30-point lines it has never seen (ERRATA E-007)."""
    rows = [HistoryRow("2024-25", date(2025, 1, 1), "BOS", "NYK", 110 + m if m > 0 else 110, 110 - m if m < 0 else 110,
                       spread, 228.5, "synthetic")
            for spread in (12.5, 13.5, 14.5, 15.5, 16.5, 17.5)
            for m in range(-round(spread) - 20, -round(spread) + 21) if m != 0]      # centred on -spread
    fam = EmpiricalFamily.fit(rows, "spreads", bucket_width=0.5, bandwidth=2.0)
    with pytest.raises(ValueError):
        fam.pmf(30.5)
    anchored = dist.anchor(fam, 15.5, 0.5)
    assert 13.0 < anchored.s_star < 18.0
    with pytest.raises(ValueError):
        dist.anchor(fam, 15.5, 0.5, search=(15.0,))                 # the old single wide window


def one_sided(seed=11):
    """Dense history at smaller spreads and none beyond -13.5: the shape that tilts the
    unshifted mixture toward smaller lines (VALIDATION.md §4)."""
    rng = random.Random(seed)
    rows = []
    for spread in [-9.5] * 800 + [-11.5] * 400 + [-13.5] * 100:
        margin = 0
        while margin == 0:
            margin = round(rng.gauss(-spread, 12.0))
        home = 110 + margin if margin > 0 else 110
        rows.append(HistoryRow("2024-25", date(2025, 1, 1), "BOS", "NYK", home, home - margin,
                               spread, 228.5, "synthetic"))
    return rows


def test_shifted_family_stays_centred_beyond_the_history():
    emp = EmpiricalFamily.fit(one_sided(), "spreads", bucket_width=0.5, bandwidth=2.0)
    se = dist.ShiftedEmpiricalFamily.from_buckets("spreads", emp.buckets, bucket_width=0.5, bandwidth=2.0)

    def mean(pmf):
        return sum(k * p for k, p in pmf.items())

    assert mean(emp.pmf(-15.5)) < 14.0                      # leans toward the denser smaller lines
    # centred up to the sampling noise of 100-game buckets (12 / sqrt(100) = 1.2 points)
    assert mean(se.pmf(-15.5)) == pytest.approx(15.5, abs=1.0)
    assert abs(mean(se.pmf(-15.5)) - 15.5) < abs(mean(emp.pmf(-15.5)) - 15.5)
    pmf = se.pmf(-15.25)                                     # a quarter-point shift splits the mass
    assert 0 not in pmf and sum(pmf.values()) == pytest.approx(1.0)
    probs = [dist.line_probability(se, s, -15.5) for s in (-21.5, -18.5, -15.5, -12.5, -9.5)]
    assert all(b <= a + 1e-12 for a, b in zip(probs, probs[1:]))     # falls as the home side weakens
    anchored = dist.anchor(se, -15.5, 0.5)
    assert anchored.family == "ShiftedEmpiricalFamily"
    assert anchored.cover(15.5) == pytest.approx(0.5, abs=1e-6)


def test_pooled_family_weights_games_not_buckets():
    """One game at -13.5 and fifty at -9.5 lie 2 points either side of -11.5. The shifted family
    gives the one game half the mixture; the pooled family gives it 1/51 (VALIDATION.md §5 L6)."""
    buckets = {-13.5: {20: 1}, -9.5: {5: 50}}
    se = dist.ShiftedEmpiricalFamily.from_buckets("spreads", buckets, bucket_width=0.5, bandwidth=2.0)
    pse = dist.PooledShiftedEmpiricalFamily.from_buckets("spreads", buckets, bucket_width=0.5, bandwidth=2.0)
    assert se.pmf(-11.5) == pytest.approx({18: 0.5, 7: 0.5})            # both moved to the target line
    assert pse.pmf(-11.5) == pytest.approx({18: 1 / 51, 7: 50 / 51})
    assert set(dist.FALLBACKS) == {"shifted_empirical", "pooled_shifted_empirical"}
    with pytest.raises(ValueError):
        pse.pmf(0.5)                                                     # no history within reach


def test_tier_b_falls_back_only_where_the_comparison_cannot_be_anchored():
    rows = synthetic()
    nor = NormalFamily.fit(rows, "spreads")
    wider = NormalFamily("spreads", nor.sigma + 1.5, nor.offset)       # a comparison that moves one way
    emp = EmpiricalFamily.fit(rows, "spreads", bucket_width=0.5, bandwidth=1.0)
    wobbly = dist.ShiftedEmpiricalFamily.from_buckets("spreads", emp.buckets, bucket_width=0.5, bandwidth=1.0)
    bracket = dist.find_bracket(wobbly, -5.5, 0.52)
    assert bracket is not None and not dist.moves_one_way(wobbly, -5.5, bracket)   # crosses, not one way
    dist.anchor(wobbly, -5.5, 0.52)                                      # anchors when one way is not asked
    with pytest.raises(dist.NotOneWay):
        dist.anchor(wobbly, -5.5, 0.52, one_way=True)

    class Unanchorable:
        market = "spreads"

        def pmf(self, s):
            raise ValueError("no history")

    expected = dist.anchor(wider, -5.5, 0.52).s_star
    assert expected != pytest.approx(dist.anchor(nor, -5.5, 0.52).s_star, abs=1e-3)
    usual = dist.TierB({"spreads": nor}, {"spreads": wider}, {"spreads": nor})
    assert usual.anchored("spreads", -5.5, 0.52)[1].s_star == pytest.approx(expected)   # no fallback needed
    for broken in (Unanchorable(), wobbly):                # cannot be anchored / not one way (§5 L8)
        replaced = dist.TierB({"spreads": nor}, {"spreads": broken}, {"spreads": wider})
        assert replaced.anchored("spreads", -5.5, 0.52)[1].s_star == pytest.approx(expected)
        with pytest.raises(ValueError):
            dist.TierB({"spreads": nor}, {"spreads": broken}).anchored("spreads", -5.5, 0.52)
        # the fair line comes from the selected family alone, whatever the comparison does
        assert dist.TierB({"spreads": nor}, {"spreads": broken}).fair("spreads", -5.5, 0.52).s_star == \
            pytest.approx(dist.anchor(nor, -5.5, 0.52).s_star)
