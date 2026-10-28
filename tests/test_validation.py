"""History adapter and the Phase 3 validation harness, on synthetic inputs."""

import json
import math
import random
import sqlite3
from datetime import date, timedelta

import pytest

from bethero_nba import dist, history, validate
from bethero_nba.dist import EmpiricalFamily, HistoryRow, NormalFamily
from bethero_nba.history import AWAY_SIGNED, UNSIGNED, Table

# ------------------------------------------------------------------ adapter


@pytest.mark.parametrize("convention, spread, ml, expected", [
    (AWAY_SIGNED, 3.5, (-164, 138), (-3.5, None)),                 # away +3.5: home lays 3.5
    (AWAY_SIGNED, -2.5, (120, -142), (2.5, None)),
    (AWAY_SIGNED, 3.5, (150, -170), (None, "moneyline contradicts spread")),
    (UNSIGNED, 5.0, (-200, 170), (-5.0, None)),
    (UNSIGNED, 5.0, (170, -200), (5.0, None)),
    (UNSIGNED, 5.0, None, (None, "spread side unresolved")),
    (UNSIGNED, 5.0, (-110, -110), (None, "spread side unresolved")),
    (UNSIGNED, 4.5, (-115, -105), (None, "moneyline contradicts spread")),
    (UNSIGNED, 2.5, (-115, -105), (-2.5, None)),                    # close game: near-even is fine
    (UNSIGNED, 0.0, (-300, 250), (None, "moneyline contradicts spread")),
    (UNSIGNED, 0.0, None, (0.0, None)),
    (UNSIGNED, -3.0, (-150, 130), (None, "negative spread in an unsigned table")),
])
def test_home_line(convention, spread, ml, expected):
    assert history.home_line(convention, spread, ml) == expected


def test_moneyline_pair():
    assert history.moneyline_pair(-110, -110) == (-110, -110)
    assert history.moneyline_pair(-2500, -2500) is None              # margin far above 15%
    assert history.moneyline_pair(50, -120) is None
    assert history.moneyline_pair(None, 100) is None


COLUMNS = "Date, Home, Away, OU, Spread, ML_Home, ML_Away, Points, Win_Margin"
FILLER = ["Atlanta Hawks", "Chicago Bulls", "Dallas Mavericks", "Houston Rockets", "Indiana Pacers",
          "Memphis Grizzlies", "Orlando Magic", "Sacramento Kings", "Toronto Raptors", "Washington Wizards"]


def filler(day, spread, ml=(-140, 120)):
    """Ten games on one date, so D3 counts it as a regular-season day."""
    return [(day.isoformat(), FILLER[i], FILLER[(i + 1) % 10], 205.0, spread, *ml, 207, 5)
            for i in range(10)]


def make_sqlite(path):
    con = sqlite3.connect(path)
    for table in ("odds_2014-15_new", "2023-24"):
        con.execute(f'CREATE TABLE "{table}" (Date TEXT, Home TEXT, Away TEXT, OU REAL, Spread, '
                    'ML_Home REAL, ML_Away REAL, Points INTEGER, Win_Margin INTEGER)')
    d1, d2, d3 = date(2015, 4, 1), date(2015, 4, 2), date(2015, 4, 3)
    unsigned = filler(d1, 2.5) + filler(d2, 2.5) + filler(d3, 2.5) + [
        ("2015-04-01", "Boston Celtics", "New York Knicks", 200.5, 5.0, -220, 180, 205, 7),
        ("2015-04-02", "Charlotte Bobcats", "Miami Heat", 195.0, 3.0, 170, -200, 190, -4),
        ("2015-04-01", "Utah Jazz", "Phoenix Suns", 1955.5, 2.0, -130, 110, 200, 2),        # D2
        ("2015-04-01", "Utah Jazz", "Denver Nuggets", 200.0, 2.0, -130, 110, 0, 0),         # missing score
        ("2015-04-01", "Phoenix Suns", "New York Knicks", 199.0, 3.5, -125, 105, 190, 0),   # tied final
        ("2015-04-01", "Denver Nuggets", "Utah Jazz", 210.0, "PK", -110, -110, 211, 3),
        ("2015-04-01", "Denver Nuggets", "Utah Jazz", 210.0, "PK", -110, -110, 211, 3),     # duplicate
        ("2015-04-21", "Boston Celtics", "Miami Heat", 200.0, 4.0, -180, 150, 210, 8),      # after D3 cut
    ]
    signed = filler(date(2024, 3, 1), -2.5, ml=(120, -140)) + [
        ("2024-03-01", "LA Clippers", "Portland Trail Blazers", 225.5, 6.5, -260, 210, 230, 12)]
    con.executemany(f'INSERT INTO "odds_2014-15_new" ({COLUMNS}) VALUES (?,?,?,?,?,?,?,?,?)', unsigned)
    con.executemany(f'INSERT INTO "2023-24" ({COLUMNS}) VALUES (?,?,?,?,?,?,?,?,?)', signed)
    con.commit()
    con.close()


def test_convert_applies_the_dataset_rules(tmp_path, monkeypatch):
    path = tmp_path / "odds.sqlite"
    make_sqlite(path)
    monkeypatch.setattr(history, "TABLES", {"2014-15": Table("odds_2014-15_new", UNSIGNED, "test"),
                                            "2023-24": Table("2023-24", AWAY_SIGNED, "test")})
    with pytest.raises(SystemExit):
        history.convert(path, tmp_path / "games.csv")                 # pinned SHA-256 differs
    out = tmp_path / "history" / "games.csv"
    prov = history.convert(path, out, expected_sha256=history.sha256_of(path))
    s = prov["seasons"]["2014-15"]
    assert s["last_regular_day"] == "2015-04-03" and s["complete"]
    assert s["dropped"] == {"after regular season (D3)": 1, "missing score": 1, "impossible score": 1,
                            "line out of range (D2)": 1, "duplicate game": 1}
    rows = dist.load_history(out)
    by_key = {(r.date.isoformat(), r.home, r.away): r for r in rows}
    assert by_key[("2015-04-01", "BOS", "NYK")].close_spread_home == -5.0       # moneyline favourite lays it
    assert by_key[("2015-04-02", "CHA", "MIA")].close_spread_home == 3.0        # former name, away favourite
    assert by_key[("2015-04-01", "DEN", "UTA")].close_spread_home == 0.0        # "PK"
    assert by_key[("2015-04-01", "ATL", "CHI")].close_spread_home == -2.5
    lac = by_key[("2024-03-01", "LAC", "POR")]
    assert lac.close_spread_home == -6.5 and (lac.home_score, lac.away_score) == (121, 109)
    assert by_key[("2024-03-01", "ATL", "CHI")].close_spread_home == 2.5       # away spread -2.5
    assert history.load_provenance(out)["source"]["sha256_checked"] == history.sha256_of(path)
    assert prov["seasons"]["2023-24"]["complete"] is False                       # ends in March


# ------------------------------------------------------------------ harness


def synthetic(seasons, per=400, seed=11, sigma=12.0, tsigma=18.0):
    """Home margin ~ round(N(-spread, sigma)) with no ties; total ~ round(N(line, tsigma))."""
    rng = random.Random(seed)
    teams = ["ATL", "BOS", "BKN", "CHA", "CHI", "CLE", "DAL", "DEN", "DET", "GSW"]
    rows = []
    for season in seasons:
        start = date(int(season[:4]), 10, 20)
        for i in range(per):
            spread = rng.choice([-9.5, -7.5, -6.0, -5.5, -3.5, -2.0, -1.5, 1.5, 3.5, 4.0, 6.5])
            line = rng.choice([215.5, 222.0, 228.5, 234.5])
            margin = 0
            while margin == 0:
                margin = round(rng.gauss(-spread, sigma))
            total = round(rng.gauss(line, tsigma))
            if (total + margin) % 2:
                total += 1
            h, a = rng.sample(teams, 2)
            rows.append(HistoryRow(season, start + timedelta(days=i // 5), h, a, (total + margin) // 2,
                                   (total - margin) // 2, spread, line, "synthetic",
                                   -150.0 if spread < 0 else 130.0, 130.0 if spread < 0 else -150.0))
    return rows


def test_dist_ticket_orientation_and_push():
    pmf = {-3: 0.25, 2: 0.25, 4: 0.5}
    home = validate.Dist(pmf, flip=False)
    assert home.ticket(2.0) == pytest.approx((0.5, 0.25, 0.25))
    away = validate.Dist(pmf, flip=True)                 # away view: margins -4, -2, 3
    assert away.ticket(2.5) == pytest.approx((0.25, 0.0, 0.75))
    row = HistoryRow("2024-25", date(2025, 1, 1), "BOS", "NYK", 100, 105, 3.5, 220.0, "x")
    assert validate.oriented(row, "spreads") == (3.5, 5, True)          # away lays 3.5 and won by 5


def test_allowed_gap():
    def rows(failing):
        return [validate.V3Row(o, 100, 0.5, 0.5 + (0.2 if o in failing else 0.0), 0.1, 0, 0)
                for o in validate.OFFSETS]
    assert validate.allowed_gap(rows(()), 1.5) == 1.5
    assert validate.allowed_gap(rows((2.0, -2.0)), 2.0) == 1.5
    assert validate.allowed_gap(rows((-1.0,)), 2.0) == 0.5
    assert validate.allowed_gap(rows((0.0,)), 2.0) == 0.0


def test_calibrated_family_passes_v3_on_matching_data(cfg):
    rows = synthetic(["2021-22", "2022-23", "2023-24", "2024-25"], per=1500)
    train = [r for r in rows if r.season < "2023-24"]
    hold = [r for r in rows if r.season >= "2023-24"]
    res = validate.evaluate_market(train, hold, "spreads", cfg)
    assert res.n_scored == res.n_holdout == 3000
    assert all(v.ok for v in res.v3)
    assert 11.0 < res.resid_sd < 13.0 and res.v4_ok and res.validated
    assert res.gap == cfg.get("tiers.tier_b_max_gap.spread")
    emp, nor = res.families
    assert nor.sigma == pytest.approx(12.0, abs=0.5)
    assert {bw for bw, _, _ in res.cv} == set(validate.BANDWIDTHS)


def test_too_narrow_bug_band_fails_v4(cfg):
    from tests.helpers import with_values
    strict = with_values(cfg, **{"distribution.bug_bands": {"margin_sigma": [10, 11], "total_sigma": [15, 23]}})
    rows = synthetic(["2021-22", "2022-23", "2023-24", "2024-25"], per=600)
    res = validate.evaluate_market([r for r in rows if r.season < "2023-24"],
                                   [r for r in rows if r.season > "2022-23"], "spreads", strict)
    assert not res.v4_ok and not res.validated


def test_supported_excludes_lines_far_from_training():
    train = synthetic(["2022-23"], per=200)
    far = HistoryRow("2023-24", date(2024, 1, 1), "BOS", "NYK", 130, 100, -25.0, 228.5, "x")
    assert validate.supported([far], train, "spreads") == []
    assert validate.supported([far], train, "totals") == [far]


def test_walk_forward_uses_only_earlier_dates():
    rows = synthetic(["2024-25"], per=300)
    preds = validate.walk_forward(rows, k=10)
    first_day = min(p.row.date for p in preds)
    assert sum(1 for r in rows if r.date < first_day) >= validate.MIN_GAMES
    # changing results on a predicted day leaves that day's predictions untouched
    day = sorted({p.row.date for p in preds})[3]
    changed = [HistoryRow(r.season, r.date, r.home, r.away, r.home_score + 40, r.away_score, r.close_spread_home,
                          r.close_total, r.source) if r.date == day else r for r in rows]
    again = validate.walk_forward(changed, k=10)
    before = [p.margin for p in preds if p.row.date == day]
    after = [p.margin for p in again if p.row.date == day]
    assert before == after


def test_roles_follow_s1():
    prov = {"seasons": {"2013-14": {"complete": True}, "2014-15": {"complete": True},
                        "2019-20": {"complete": False}, "2023-24": {"complete": True},
                        "2024-25": {"complete": True}, "2025-26": {"complete": False}}}
    rows = [HistoryRow(s, date(int(s[:4]), 11, 1), "BOS", "NYK", 100, 90, -3.0, 220.0, "x")
            for s in prov["seasons"]]
    r = validate.roles(prov, rows)
    assert r.holdout == ("2023-24", "2024-25")
    assert r.train == ("2014-15", "2019-20")
    assert r.sensitivity_train == ("2013-14", "2014-15", "2019-20")
    assert r.later == ("2025-26",)


def test_devig_scores_and_percentile():
    rows = synthetic(["2024-25"], per=300)
    out = validate.devig_scores(rows, ("multiplicative", "power", "shin"))
    assert {m: out[m]["n"] for m in out} == {"multiplicative": 300, "power": 300, "shin": 300}
    assert validate.percentile([1, 2, 3, 4, 5], 0.8) == pytest.approx(4.2)
    assert validate.floor1(3.4999) == 3.4 and validate.floor1(3.5) == 3.5
    mean, se = validate.paired([1.0, 2.0, 3.0], [1.0, 1.0, 1.0])
    assert mean == pytest.approx(1.0) and se == pytest.approx(math.sqrt(1 / 3))


def test_write_results_keeps_the_criteria(tmp_path):
    path = tmp_path / "VALIDATION.md"
    path.write_text("# Validation\n\n## 0. Criteria\n\nfixed text\n", encoding="utf-8")
    validate.write_results(path, validate.RESULTS_MARKER + "\n\nfirst\n")
    validate.write_results(path, validate.RESULTS_MARKER + "\n\nsecond\n")
    text = path.read_text(encoding="utf-8")
    assert text.startswith("# Validation\n\n## 0. Criteria\n\nfixed text\n\n")
    assert "second" in text and "first" not in text and text.count(validate.RESULTS_MARKER) == 1


def test_families_round_trip_and_tier_b(tmp_path):
    rows = synthetic(["2024-25"], per=800)
    emp = EmpiricalFamily.fit(rows, "spreads", bucket_width=0.5, bandwidth=1.0)
    nor = NormalFamily.fit(rows, "spreads")
    dist.save_families(tmp_path / "spreads.json", emp, nor, {"validated": True, "selected_method": "normal"})
    emp2, nor2, meta = dist.load_families(tmp_path / "spreads.json")
    assert meta["validated"] and emp2.pmf(-5.5) == pytest.approx(emp.pmf(-5.5))
    assert nor2.pmf(-5.5) == pytest.approx(nor.pmf(-5.5))
    raw = json.loads((tmp_path / "spreads.json").read_text(encoding="utf-8"))
    assert set(raw) >= {"schema", "market", "empirical", "normal", "buckets"} and "rows" not in raw
    tb = dist.load_tier_b(tmp_path, ["spreads"], {"spread": "normal", "total": "empirical"}, {"spread": 1.0})
    assert tb.primary["spreads"].__class__ is NormalFamily
    assert tb.alternative["spreads"].__class__ is EmpiricalFamily
    assert dist.load_tier_b(tmp_path, [], {"spread": "normal"}) is None
    with pytest.raises(ValueError):                                      # config chose another family
        dist.load_tier_b(tmp_path, ["spreads"], {"spread": "empirical"})
    with pytest.raises(ValueError):                                      # bandwidth drifted
        dist.load_tier_b(tmp_path, ["spreads"], {"spread": "normal"}, {"spread": 2.0})
    pooled = dist.load_tier_b(tmp_path, ["spreads"], {"spread": "normal"}, {"spread": 1.0},
                              {"spread": "pooled_shifted_empirical"})
    assert pooled.fallback["spreads"].__class__ is dist.PooledShiftedEmpiricalFamily
    assert pooled.fallback["spreads"].buckets == emp.buckets
    assert dist.load_tier_b(tmp_path, ["spreads"], {"spread": "normal"}, {"spread": 1.0},
                            {"spread": "none"}).fallback == {}
    with pytest.raises(ValueError):                                      # no such family
        dist.load_tier_b(tmp_path, ["spreads"], {"spread": "normal"}, {"spread": 1.0}, {"spread": "isotonic"})


def test_end_to_end_run_and_render(tmp_path, cfg):
    seasons = ["2013-14", "2014-15", "2015-16", "2016-17", "2023-24", "2024-25", "2025-26"]
    rows = synthetic(seasons, per=300)
    csv_path = tmp_path / "games.csv"
    history.write_csv(rows, csv_path)
    prov = {"converted_at": "2026-10-23T00:00:00+00:00",
            "source": {**history.SOURCE, "sha256_checked": history.SOURCE["sha256"]},
            "rules": {"D2": "d2", "D3": "d3", "moneyline": "ml", "spread side": "side", "contradiction": "c"},
            "seasons": {s: {"table": "t", "raw": 300, "kept": 300, "last_regular_day": f"{int(s[:4]) + 1}-04-10",
                            "complete": s != "2025-26", "dropped": {}} for s in seasons}}
    history.provenance_path(csv_path).write_text(json.dumps(prov), encoding="utf-8")
    ctx = validate.run(csv_path, cfg)
    assert ctx["roles"].holdout == ("2023-24", "2024-25")
    assert ctx["roles"].train == ("2014-15", "2015-16", "2016-17")
    keys = [k for k, _, _ in ctx["decisions"]]
    assert "distribution.validated_markets" in keys and "model.model_veto_pts" in keys
    assert ctx["k"] in validate.K_GRID
    text = validate.render(ctx)
    for heading in ("### R1 Dataset", "### R3 Spreads", "### R3 Totals", "### R5 De-vig", "### R6 Veto model",
                    "### R8 Large spreads", "### R9 Pooled shifted family", "### R7 Values"):
        assert heading in text
    # no laid line of 12+ in this history: T3 and T5 cannot hold on no games
    assert ("distribution.comparison_fallback.spread", "none", "§4 T1-T3, §5 T4-T5") in ctx["decisions"]
    paths = validate.write_dist(ctx, tmp_path / "dist")
    assert sorted(p.name for p in paths) == ["spreads.json", "totals.json"]


def test_committed_families_match_the_config(cfg, root):
    """The engine's Tier B must load from the repository as committed (a fresh clone)."""
    if cfg.get("distribution.status") != "VALIDATED":
        pytest.skip("distribution not validated")
    markets = cfg.get("distribution.validated_markets")
    tb = dist.load_tier_b(root / "data" / "dist", markets, cfg.get("distribution.selected_method"),
                          cfg.get("distribution.smoothing_bandwidth"))
    assert set(tb.primary) == set(markets)
    anchored, alternative = tb.anchored("spreads", -5.5, 0.5)
    assert anchored.cover(5.5) == pytest.approx(0.5, abs=1e-6)
    assert 5.0 < anchored.fair_point() < 6.0
