"""Odds formats, de-vig, split-ticket settlement, EV and Kelly.

Ported from MLB `src/mlbline/devig.py` (GizzyJeans/MLB@9ca07aa) and cc_npb
`bethero/ev.py` (GizzyJeans/cc_npb@cfe74e9), with Shin rewritten.

Formats. The platform quotes Hong Kong odds h: a stake of 1 wins h, so the
decimal price is 1 + h and the amount at risk is the stake (RULES R-3.1). Malay
odds equal HK odds between 0 and 1; a negative Malay price -m risks m to win 1.
US books quote American odds.

De-vig. Multiplicative, power and Shin agree on balanced prices and diverge on
lopsided ones; the divergence is how much of a "fair probability" is
convention. Gating uses the worst case across methods (RULES R-5.3). Shin is
solved properly here: the MLB version returned the multiplicative answer
because its root-finder started at z = 0, where a special case made the sum
exactly one (MLB docs/gate_2b.md).

Tickets. A platform line is a split ticket: legs (line, weight) seen from the
side laying the line, or the over. Scores are integers, so a ticket is priced
exactly from P(X > x) at the half-points around its legs: a half-point leg
needs its own line, an integer leg needs the half-points on either side of it
(the difference is the push mass). `ticket_outcomes` turns those into the
ticket's full set of outcomes, which is what EV, the effective win
probability and Kelly all need.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Callable, Sequence

# --------------------------------------------------------------- conversions


def hk_to_decimal(hk: float) -> float:
    if hk <= 0:
        raise ValueError(f"Hong Kong odds must be positive, got {hk}")
    return 1.0 + hk


def decimal_to_hk(decimal: float) -> float:
    if decimal <= 1.0:
        raise ValueError(f"decimal odds must exceed 1, got {decimal}")
    return decimal - 1.0


def malay_to_hk(malay: float) -> float:
    """Malay m in (0, 1] equals HK m; Malay -m risks m to win 1, i.e. HK 1/m."""
    if malay == 0 or abs(malay) > 1:
        raise ValueError(f"Malay odds must lie in [-1, 0) or (0, 1], got {malay}")
    return malay if malay > 0 else 1.0 / -malay


def hk_to_malay(hk: float) -> float:
    if hk <= 0:
        raise ValueError(f"Hong Kong odds must be positive, got {hk}")
    return hk if hk <= 1.0 else -1.0 / hk


def american_to_decimal(american: float) -> float:
    if american >= 100:
        return 1.0 + american / 100.0
    if american <= -100:
        return 1.0 + 100.0 / -american
    raise ValueError(f"American odds must be <= -100 or >= +100, got {american}")


def decimal_to_american(decimal: float) -> float:
    if decimal <= 1.0:
        raise ValueError(f"decimal odds must exceed 1, got {decimal}")
    profit = decimal - 1.0
    return 100.0 * profit if profit >= 1.0 else -100.0 / profit


# --------------------------------------------------------------------- de-vig


def implied(decimals: Sequence[float]) -> list[float]:
    return [1.0 / d for d in decimals]


def overround(decimals: Sequence[float]) -> float:
    """Bookmaker margin as a fraction: 0.0476 for -110/-110."""
    return sum(implied(decimals)) - 1.0


def devig_multiplicative(decimals: Sequence[float]) -> list[float]:
    q = implied(decimals)
    total = sum(q)
    return [x / total for x in q]


def devig_additive(decimals: Sequence[float]) -> list[float]:
    """Equal subtraction; diagnostic only. Falls back to multiplicative when an
    outcome would go to or below zero."""
    q = implied(decimals)
    excess = (sum(q) - 1.0) / len(q)
    fair = [x - excess for x in q]
    return fair if all(p > 0 for p in fair) else devig_multiplicative(decimals)


def _bisect(f: Callable[[float], float], lo: float, hi: float, iterations: int = 200) -> float:
    """Root of a function that is positive at `lo` and negative at `hi`."""
    for _ in range(iterations):
        mid = 0.5 * (lo + hi)
        if f(mid) > 0:
            lo = mid
        else:
            hi = mid
    return 0.5 * (lo + hi)


def devig_power(decimals: Sequence[float]) -> list[float]:
    """Solve k > 1 with sum(q_i ** k) == 1."""
    q = implied(decimals)
    if sum(q) <= 1.0:
        return devig_multiplicative(decimals)
    k = _bisect(lambda kk: sum(x ** kk for x in q) - 1.0, 1.0, 100.0)
    fair = [x ** k for x in q]
    total = sum(fair)
    return [p / total for p in fair]


def devig_shin(decimals: Sequence[float]) -> list[float]:
    """Shin (1993): solve for the insider share z in (0, 1) that makes the
    recovered probabilities sum to one.

    At z = 0 the formula gives q_i / sqrt(Q), which sums to sqrt(Q) > 1 for any
    book with a margin, and the sum falls below one as z approaches 1, so the
    root is bracketed without any special case.
    """
    q = implied(decimals)
    total = sum(q)
    if total <= 1.0:
        return devig_multiplicative(decimals)

    def probabilities(z: float) -> list[float]:
        return [(math.sqrt(z * z + 4.0 * (1.0 - z) * x * x / total) - z) / (2.0 * (1.0 - z))
                for x in q]

    z = _bisect(lambda zz: sum(probabilities(zz)) - 1.0, 0.0, 1.0 - 1e-9)
    fair = probabilities(z)
    norm = sum(fair)
    return [p / norm for p in fair]


METHODS: dict[str, Callable[[Sequence[float]], list[float]]] = {
    "multiplicative": devig_multiplicative,
    "power": devig_power,
    "shin": devig_shin,
    "additive": devig_additive,
}


def devig(decimals: Sequence[float], method: str) -> list[float]:
    try:
        return METHODS[method](decimals)
    except KeyError:
        raise ValueError(f"unknown de-vig method {method!r}; choose from {sorted(METHODS)}") from None


# -------------------------------------------------------------------- tickets


@dataclass(frozen=True)
class Leg:
    """`weight` of the stake on `line`, seen from the side laying the line (or
    the over): that side wins the leg when the outcome X is above `line`,
    pushes when X equals it, and loses when X is below."""

    line: float
    weight: float


@dataclass(frozen=True)
class Outcome:
    """One settlement region of a ticket."""

    ret: float    # profit per unit staked
    prob: float
    win: float    # share of the stake that wins
    loss: float   # share of the stake that loses


def _is_integer(x: float) -> bool:
    return abs(x - round(x)) < 1e-9


def _is_half(x: float) -> bool:
    return _is_integer(x - 0.5)


def needed_points(legs: Sequence[Leg]) -> tuple[float, ...]:
    """Half-points x at which P(X > x) prices these legs exactly."""
    points: set[float] = set()
    for leg in legs:
        if _is_half(leg.line):
            points.add(round(leg.line * 2) / 2)
        elif _is_integer(leg.line):
            k = round(leg.line)
            points.update((k - 0.5, k + 0.5))
        else:
            raise ValueError(f"leg line {leg.line} is neither an integer nor a half-point")
    return tuple(sorted(points))


def ticket_outcomes(legs: Sequence[Leg], price: float, cover: Callable[[float], float],
                    laying: bool = True, tolerance: float = 1e-9) -> list[Outcome]:
    """Settlement regions of a ticket at HK `price`.

    `cover(x)` is P(X > x) for the half-points of `needed_points`, X being the
    laying side's margin (or the total). `laying=False` prices the other side
    of the same ticket. Raises ValueError when the cover probabilities are not
    non-increasing, i.e. when the quoted lines contradict each other.
    """
    if abs(sum(leg.weight for leg in legs) - 1.0) > 1e-9:
        raise ValueError("leg weights must sum to 1")
    points = needed_points(legs)
    covers = [cover(x) for x in points]
    bounds = [(-math.inf, 1.0), *zip(points, covers), (math.inf, 0.0)]
    outcomes: list[Outcome] = []
    for (lo, p_lo), (hi, p_hi) in zip(bounds, bounds[1:]):
        prob = p_lo - p_hi
        if prob < -tolerance:
            raise ValueError(f"inconsistent cover probabilities: P(X > {lo}) < P(X > {hi})")
        x = hi - 0.5 if lo == -math.inf else lo + 0.5   # an integer inside the region
        ret = win = loss = 0.0
        for leg in legs:
            if abs(x - leg.line) < 1e-9:
                continue                                     # push: stake returned
            won = (x > leg.line) == laying
            if won:
                ret += leg.weight * price
                win += leg.weight
            else:
                ret -= leg.weight
                loss += leg.weight
        outcomes.append(Outcome(ret, max(prob, 0.0), win, loss))
    return outcomes


def expected_value(outcomes: Sequence[Outcome]) -> float:
    return sum(o.prob * o.ret for o in outcomes)


def effective_win_probability(outcomes: Sequence[Outcome]) -> float:
    """p_eff = W / (W + L), pushes excluded (RULES R-12.2)."""
    won = sum(o.prob * o.win for o in outcomes)
    lost = sum(o.prob * o.loss for o in outcomes)
    return won / (won + lost) if won + lost > 0 else 0.0


def kelly_fraction(outcomes: Sequence[Outcome]) -> float:
    """Growth-optimal stake: argmax over f of sum(p * log(1 + f * r)).

    The derivative sum(p * r / (1 + f * r)) falls as f grows, so bisection on
    it is exact. Pushes and partial results make the bet non-binary, which is
    why the textbook (bp - q) / b is not used (cc_npb bethero/ev.py).
    """
    live = [o for o in outcomes if o.prob > 0 and o.ret != 0]
    if not live or expected_value(live) <= 0:
        return 0.0
    worst = min(o.ret for o in live)
    if worst >= 0:
        return 1.0
    upper = (1.0 / -worst) * (1.0 - 1e-9)

    def slope(f: float) -> float:
        return sum(o.prob * o.ret / (1.0 + f * o.ret) for o in live)

    if slope(upper) > 0:
        return upper
    return _bisect(slope, 0.0, upper)


def required_probability(price: float, target_ev: float = 0.0) -> float:
    """Win probability a no-push ticket needs at HK `price` for `target_ev`."""
    return (1.0 + target_ev) / (1.0 + price)
