"""Golden cases for odds, de-vig and settlement, computed by hand."""

import math

import pytest

from bethero_nba import odds
from bethero_nba.odds import Leg


# ------------------------------------------------------------- conversions

@pytest.mark.parametrize("american, decimal", [
    (-110, 1 + 100 / 110), (+150, 2.5), (-200, 1.5), (+100, 2.0), (-100, 2.0)])
def test_american_decimal_golden(american, decimal):
    assert odds.american_to_decimal(american) == pytest.approx(decimal)


@pytest.mark.parametrize("american", [-1000, -250, -110, -101, 100, 105, 333, 1200])
def test_american_round_trip(american):
    back = odds.decimal_to_american(odds.american_to_decimal(american))
    assert back == pytest.approx(100.0 if american == -100 else american)


@pytest.mark.parametrize("hk", [0.05, 0.56, 0.94, 0.95, 1.0, 1.4, 3.2])
def test_hk_round_trips(hk):
    assert odds.decimal_to_hk(odds.hk_to_decimal(hk)) == pytest.approx(hk)
    assert odds.malay_to_hk(odds.hk_to_malay(hk)) == pytest.approx(hk)


def test_malay_golden():
    assert odds.malay_to_hk(0.95) == 0.95                 # same as HK below 1
    assert odds.malay_to_hk(-0.5) == pytest.approx(2.0)   # risk 0.5 to win 1
    assert odds.hk_to_malay(1.4) == pytest.approx(-1 / 1.4)


@pytest.mark.parametrize("bad", [0, 50, -50])
def test_invalid_american_rejected(bad):
    with pytest.raises(ValueError):
        odds.american_to_decimal(bad)


def test_invalid_malay_and_hk_rejected():
    with pytest.raises(ValueError):
        odds.malay_to_hk(1.4)
    with pytest.raises(ValueError):
        odds.hk_to_decimal(0)


# ------------------------------------------------------------------- de-vig

PRICE_SETS = [(-110, -110), (-120, +100), (-200, +170), (-400, +320), (-1000, +650), (+105, -125)]


@pytest.mark.parametrize("pair", PRICE_SETS)
@pytest.mark.parametrize("method", ["multiplicative", "power", "shin", "additive"])
def test_devig_sums_to_one(pair, method):
    probs = odds.devig([odds.american_to_decimal(a) for a in pair], method)
    assert sum(probs) == pytest.approx(1.0, abs=1e-12)
    assert all(0 < p < 1 for p in probs)


@pytest.mark.parametrize("method", ["multiplicative", "power", "shin", "additive"])
def test_balanced_prices_give_one_half(method):
    probs = odds.devig([odds.american_to_decimal(-110)] * 2, method)
    assert probs[0] == pytest.approx(0.5)


def test_multiplicative_golden():
    # -120 / +100: implied 0.545454.. and 0.5, total 1.045454..
    p = odds.devig_multiplicative([odds.american_to_decimal(-120), 2.0])
    assert p[0] == pytest.approx((120 / 220) / (120 / 220 + 0.5))


def test_shin_is_not_multiplicative_on_lopsided_prices():
    """The MLB bug: devig_shin returned the multiplicative result."""
    d = [odds.american_to_decimal(-400), odds.american_to_decimal(320)]
    mult, shin, power = (odds.devig(d, m)[0] for m in ("multiplicative", "shin", "power"))
    assert mult == pytest.approx(0.77064, abs=1e-5)
    assert shin == pytest.approx(0.78095, abs=1e-5)
    assert power == pytest.approx(0.78653, abs=1e-5)


def test_shin_matches_its_defining_equation():
    d = [odds.american_to_decimal(-200), odds.american_to_decimal(170)]
    p = odds.devig_shin(d)
    q = odds.implied(d)
    total = sum(q)
    # Recover z from the favourite, then the underdog must satisfy the same z.
    z_values = []
    for pi, qi in zip(p, q):
        # Shin price relation: qi / total = sqrt(z*pi + (1-z)*pi^2) ... solve pi(z) numerically
        lo, hi = 0.0, 0.5
        for _ in range(200):
            z = (lo + hi) / 2
            pz = (math.sqrt(z * z + 4 * (1 - z) * qi * qi / total) - z) / (2 * (1 - z))
            lo, hi = (z, hi) if pz > pi else (lo, z)
        z_values.append((lo + hi) / 2)
    assert z_values[0] == pytest.approx(z_values[1], abs=1e-6)
    assert 0 < z_values[0] < 0.2


def test_unknown_method_rejected():
    with pytest.raises(ValueError):
        odds.devig([1.9, 1.9], "magic")


# ---------------------------------------------------------- ticket settlement

def cover_from_pmf(pmf):
    return lambda x: sum(p for k, p in pmf.items() if k > x)


# A small margin distribution, P(margin = k), used to check settlement by hand.
PMF = {-2: 0.10, -1: 0.10, 1: 0.10, 2: 0.10, 3: 0.10, 4: 0.10, 5: 0.15, 6: 0.15, 7: 0.10}
COVER = cover_from_pmf(PMF)
H = 0.95


def ev_by_hand(legs, laying=True):
    total = 0.0
    for margin, p in PMF.items():
        ret = 0.0
        for leg in legs:
            if margin == leg.line:
                continue
            won = (margin > leg.line) == laying
            ret += leg.weight * (H if won else -1.0)
        total += p * ret
    return total


@pytest.mark.parametrize("legs", [
    (Leg(4.5, 1.0),),                         # half line
    (Leg(5.0, 1.0),),                         # flat line, pushes at 5
    (Leg(4.5, 0.5), Leg(5.0, 0.5)),           # 5+50 = 4.75
    (Leg(5.0, 0.7), Leg(5.5, 0.3)),           # 5-30 = 5.15
    (Leg(-0.5, 0.25), Leg(0.0, 0.75)),        # 0+25, a pick'em tail
])
@pytest.mark.parametrize("laying", [True, False])
def test_ticket_ev_matches_hand_settlement(legs, laying):
    outcomes = odds.ticket_outcomes(legs, H, COVER, laying)
    assert sum(o.prob for o in outcomes) == pytest.approx(1.0)
    assert odds.expected_value(outcomes) == pytest.approx(ev_by_hand(legs, laying))


def test_erics_confirmed_case_5_plus_50():
    """WAS 5+50 at 0.95; WAS by exactly 5: +47.5 on WAS, -50 on MIL per 100."""
    legs = (Leg(4.5, 0.5), Leg(5.0, 0.5))
    exactly_five = lambda x: 1.0 if x < 5 else 0.0      # noqa: E731  P(margin > x) with margin = 5
    giving = odds.ticket_outcomes(legs, H, exactly_five, laying=True)
    taking = odds.ticket_outcomes(legs, H, exactly_five, laying=False)
    assert 100 * odds.expected_value(giving) == pytest.approx(47.5)
    assert 100 * odds.expected_value(taking) == pytest.approx(-50.0)


def test_flat_line_push_is_excluded_from_effective_probability():
    outcomes = odds.ticket_outcomes((Leg(5.0, 1.0),), H, COVER)
    win, push = COVER(5.5), COVER(4.5) - COVER(5.5)
    assert odds.effective_win_probability(outcomes) == pytest.approx(win / (1 - push))


def test_inconsistent_covers_are_refused():
    broken = {4.5: 0.40, 5.5: 0.45}.get
    with pytest.raises(ValueError):
        odds.ticket_outcomes((Leg(5.0, 1.0),), H, broken)


def test_needed_points():
    assert odds.needed_points((Leg(4.5, 0.5), Leg(5.0, 0.5))) == (4.5, 5.5)
    assert odds.needed_points((Leg(238.5, 1.0),)) == (238.5,)
    with pytest.raises(ValueError):
        odds.needed_points((Leg(4.75, 1.0),))


# ------------------------------------------------------------------- Kelly

def test_kelly_binary_matches_textbook():
    p = 0.5557
    outcomes = [odds.Outcome(H, p, 1, 0), odds.Outcome(-1.0, 1 - p, 0, 1)]
    assert odds.kelly_fraction(outcomes) == pytest.approx((p * H - (1 - p)) / H, abs=1e-9)


def test_kelly_zero_without_edge_and_smaller_with_pushes():
    assert odds.kelly_fraction([odds.Outcome(H, 0.5, 1, 0), odds.Outcome(-1, 0.5, 0, 1)]) == 0.0
    # Same win/loss odds ratio, but a push removes 10% of the mass.
    with_push = [odds.Outcome(H, 0.5, 1, 0), odds.Outcome(0.0, 0.1, 0, 0), odds.Outcome(-1, 0.4, 0, 1)]
    no_push = [odds.Outcome(H, 0.5 / 0.9, 1, 0), odds.Outcome(-1, 0.4 / 0.9, 0, 1)]
    assert odds.kelly_fraction(with_push) == pytest.approx(odds.kelly_fraction(no_push), rel=1e-6)


def test_kelly_maximises_log_growth_on_a_split_ticket():
    outcomes = odds.ticket_outcomes((Leg(4.5, 0.5), Leg(5.0, 0.5)), H, COVER)
    f = odds.kelly_fraction(outcomes)

    def growth(x):
        return sum(o.prob * math.log(1 + x * o.ret) for o in outcomes)

    if f > 0:
        assert growth(f) >= growth(f * 0.9) and growth(f) >= growth(min(f * 1.1, 0.99))


def test_required_probability():
    assert odds.required_probability(0.95, 0.04) == pytest.approx(1.04 / 1.95)
