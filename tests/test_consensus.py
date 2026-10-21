from datetime import datetime, timedelta, timezone

import pytest

from bethero_nba import consensus, oddsapi
from bethero_nba.net import Fetched
from bethero_nba.odds import american_to_decimal, devig

US_TS = datetime(2026, 11, 3, 0, 12, tzinfo=timezone.utc)
METHODS = ("multiplicative", "power", "shin")


def book(key, spreads=None, totals=None, h2h=None, age_min=2):
    """One bookmaker block in Odds API shape. spreads: (home_point, home_price, away_price)."""
    updated = (US_TS - timedelta(minutes=age_min)).isoformat()
    markets = []
    if spreads:
        point, hp, ap = spreads
        markets.append({"key": "spreads", "last_update": updated, "outcomes": [
            {"name": "Home Team", "price": hp, "point": point},
            {"name": "Away Team", "price": ap, "point": -point}]})
    if totals:
        point, op, up = totals
        markets.append({"key": "totals", "last_update": updated, "outcomes": [
            {"name": "Over", "price": op, "point": point},
            {"name": "Under", "price": up, "point": point}]})
    if h2h:
        markets.append({"key": "h2h", "last_update": updated, "outcomes": [
            {"name": "Home Team", "price": h2h[0]}, {"name": "Away Team", "price": h2h[1]}]})
    return {"key": key, "title": key, "last_update": updated, "markets": markets}


def game(bookmakers):
    return oddsapi.normalise([{
        "id": "g1", "commence_time": "2026-11-03T00:30:00Z",
        "home_team": "Home Team", "away_team": "Away Team", "bookmakers": bookmakers}])[0]


# The eight books of the RULES §18 worked example, all at home -5.5.
WORKED = [(-120, 100), (-118, -102), (-122, 102), (-115, -105),
          (-120, 100), (-125, 105), (-119, -101), (-121, 101)]


def worked_consensus():
    books = [book(f"B{i + 1}", spreads=(-5.5, hp, ap), totals=(228.5, -110, -110), h2h=(-250, 205))
             for i, (hp, ap) in enumerate(WORKED)]
    return consensus.build(game(books), US_TS, methods=METHODS, max_age_min=30)


def test_median_consensus_matches_the_worked_example():
    gc = worked_consensus()
    lc = gc.line("spreads", -5.5)
    assert lc.n_books == 8
    assert lc.probs["multiplicative"] == pytest.approx(0.5217, abs=5e-5)
    assert lc.probs["power"] == pytest.approx(0.5232, abs=5e-5)
    assert lc.probs["shin"] == pytest.approx(0.5227, abs=5e-5)
    assert lc.sigma_books("multiplicative") == pytest.approx(0.0025, abs=1e-4)
    assert gc.l_ref("spreads") == -5.5 and gc.l_ref("totals") == 228.5


def test_cover_orientation():
    gc = worked_consensus()
    p = gc.line("spreads", -5.5).probs["shin"]
    home = gc.cover("spreads", "home", "shin", min_books=8)
    away = gc.cover("spreads", "away", "shin", min_books=8)
    assert home(5.5) == pytest.approx(p)            # home wins by 6+
    assert away(-5.5) == pytest.approx(1 - p)       # away +5.5 covers
    assert home(4.5) is None                        # nobody quotes -4.5
    assert gc.cover("spreads", "home", "shin", min_books=9)(5.5) is None
    over = gc.cover("totals", "over", "shin", min_books=8)
    assert over(228.5) == pytest.approx(0.5)
    ml = gc.cover("h2h", "home", "shin", min_books=8)
    assert ml(0.5) == pytest.approx(devig([american_to_decimal(-250), american_to_decimal(205)], "shin")[0])


def test_stale_quotes_are_dropped_and_counted():
    books = [book("fresh", spreads=(-3.5, -110, -110)),
             book("stale", spreads=(-3.5, -150, 130), age_min=45)]
    gc = consensus.build(game(books), US_TS, methods=METHODS, max_age_min=30)
    assert gc.line("spreads", -3.5).books == ("fresh",)
    assert gc.dropped_stale == 2


def test_mirror_spread_markets_stay_apart():
    books = [book("a", spreads=(-1.5, -110, -110)), book("b", spreads=(1.5, -110, -110))]
    gc = consensus.build(game(books), US_TS, methods=METHODS, max_age_min=30)
    assert gc.line("spreads", -1.5).books == ("a",)
    assert gc.line("spreads", 1.5).books == ("b",)


def test_one_sided_books_are_ignored():
    g = game([book("a", spreads=(-2.5, -110, -110))])
    g.quotes = [q for q in g.quotes if q.side == "Home Team"]
    assert consensus.build(g, US_TS, methods=METHODS, max_age_min=30).line("spreads", -2.5) is None


def test_budget_refuses_over_daily_count_and_reserve(tmp_path):
    budget = oddsapi.Budget(tmp_path / "usage.jsonl", max_calls_per_day=2, min_remaining_reserve=50)
    def fetched(remaining):
        return Fetched(b"[]", 200, {"x-requests-remaining": str(remaining)}, "u", US_TS, "0" * 64)
    budget.check(US_TS, 3)
    budget.record(fetched(60), "odds")
    with pytest.raises(oddsapi.BudgetRefused, match="reserve"):
        budget.check(US_TS, 11)
    budget.check(US_TS, 3)
    budget.record(fetched(57), "odds")
    with pytest.raises(oddsapi.BudgetRefused, match="already"):
        budget.check(US_TS, 3)


def test_completed_scores_include_overtime_finals():
    payload = [{"id": "x", "commence_time": "2026-11-03T00:30:00Z", "completed": True,
                "home_team": "Home Team", "away_team": "Away Team",
                "scores": [{"name": "Home Team", "score": "121"}, {"name": "Away Team", "score": "118"}]},
               {"id": "y", "commence_time": "2026-11-03T02:00:00Z", "completed": False,
                "home_team": "H", "away_team": "A", "scores": None}]
    scores = oddsapi.completed_scores(payload)
    assert len(scores) == 1 and (scores[0].home_score, scores[0].away_score) == (121, 118)
