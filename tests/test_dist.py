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
