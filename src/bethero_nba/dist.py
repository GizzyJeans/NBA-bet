"""Empirical margin and total distributions, and Tier B translation (RULES §7).

The family is P(X = k | market line s): X is the final home margin (spreads)
or the final total (totals), overtime included, and s is the US closing home
spread or closing total. It is estimated from history by kernel smoothing
across neighbouring 0.5-point buckets of s, keeping integer masses so pushes
are priced; a discretized normal fitted to the same data is the comparison
model (RULES R-7.4).

Translation anchors the family to the consensus: find the line s* at which the
family reproduces the consensus probability at the reference line, then read
any other half-point off the same distribution. Tier B is allowed only once
the family is VALIDATED on holdout seasons (RULES R-6.4); until then the
engine never calls this module.
"""

from __future__ import annotations

import csv
import math
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from statistics import NormalDist
from typing import Iterable

HISTORY_COLUMNS = ("season", "date", "home", "away", "home_score", "away_score",
                   "close_spread_home", "close_total", "source")
OPTIONAL_COLUMNS = ("close_ml_home", "close_ml_away")      # American odds, for the de-vig comparison


@dataclass(frozen=True)
class HistoryRow:
    season: str
    date: date
    home: str
    away: str
    home_score: int
    away_score: int
    close_spread_home: float | None
    close_total: float | None
    source: str
    close_ml_home: float | None = None
    close_ml_away: float | None = None

    @property
    def margin(self) -> int:
        return self.home_score - self.away_score

    @property
    def total(self) -> int:
        return self.home_score + self.away_score


def load_history(path: Path | str) -> list[HistoryRow]:
    """Read the canonical history CSV (columns in `HISTORY_COLUMNS`). Whatever
    the original source, an adapter converts it to this shape first."""
    rows = []
    with Path(path).open(encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        missing = set(HISTORY_COLUMNS) - set(reader.fieldnames or ())
        if missing:
            raise ValueError(f"{path}: missing columns {sorted(missing)}")
        for raw in reader:
            def number(key: str) -> float | None:
                value = raw.get(key)
                return float(value) if value not in ("", None) else None
            rows.append(HistoryRow(raw["season"], date.fromisoformat(raw["date"]), raw["home"],
                                   raw["away"], int(raw["home_score"]), int(raw["away_score"]),
                                   number("close_spread_home"), number("close_total"), raw["source"],
                                   number("close_ml_home"), number("close_ml_away")))
    return rows


def _observations(rows: Iterable[HistoryRow], market: str) -> list[tuple[float, int]]:
    out = []
    for row in rows:
        line = row.close_spread_home if market == "spreads" else row.close_total
        if line is None:
            continue
        out.append((line, row.margin if market == "spreads" else row.total))
    return out


def _location(market: str, line: float) -> float:
    """Expected X implied by a line: a home spread of -5.5 means a 5.5-point home edge."""
    return -line if market == "spreads" else line


class EmpiricalFamily:
    """Kernel-smoothed P(X = k | s) over 0.5-point buckets of s.

    Buckets near s are mixed with Gaussian weights of `bandwidth` points and
    never shifted, so the integer structure of each bucket (key margins,
    overtime clusters) survives; a symmetric kernel keeps the mixture centred.
    """

    def __init__(self, market: str, observations: Iterable[tuple[float, int]],
                 bucket_width: float, bandwidth: float):
        self.market, self.bucket_width, self.bandwidth = market, bucket_width, bandwidth
        self.buckets: dict[float, dict[int, int]] = {}
        for line, x in observations:
            b = round(line / bucket_width) * bucket_width
            counts = self.buckets.setdefault(b, {})
            counts[x] = counts.get(x, 0) + 1

    @classmethod
    def fit(cls, rows: Iterable[HistoryRow], market: str, *, bucket_width: float,
            bandwidth: float) -> "EmpiricalFamily":
        return cls(market, _observations(rows, market), bucket_width, bandwidth)

    def _weights(self, s: float) -> dict[float, float]:
        reach = 4 * self.bandwidth
        return {b: math.exp(-0.5 * ((b - s) / self.bandwidth) ** 2)
                for b in self.buckets if abs(b - s) <= reach}

    def pmf(self, s: float) -> dict[int, float]:
        weights = self._weights(s)
        mass: dict[int, float] = {}
        total = 0.0
        for b, w in weights.items():
            n = sum(self.buckets[b].values())
            for x, count in self.buckets[b].items():
                mass[x] = mass.get(x, 0.0) + w * count / n
            total += w
        if total == 0:
            raise ValueError(f"no history within reach of line {s}")
        return {x: m / total for x, m in mass.items()}

    def effective_n(self, s: float) -> float:
        """Kish effective sample size of the kernel mixture at s."""
        pairs = [(w, sum(self.buckets[b].values())) for b, w in self._weights(s).items()]
        num = sum(w * n for w, n in pairs) ** 2
        den = sum(w * w * n for w, n in pairs)
        return num / den if den else 0.0


class NormalFamily:
    """Discretized normal around the line-implied location, with no mass at a
    tied margin (overtime settles every game)."""

    def __init__(self, market: str, sigma: float, offset: float = 0.0):
        self.market, self.sigma, self.offset = market, sigma, offset

    @classmethod
    def fit(cls, rows: Iterable[HistoryRow], market: str) -> "NormalFamily":
        residuals = [x - _location(market, line) for line, x in _observations(rows, market)]
        if len(residuals) < 2:
            raise ValueError("need at least two games to fit a normal")
        mean = sum(residuals) / len(residuals)
        sd = math.sqrt(sum((r - mean) ** 2 for r in residuals) / (len(residuals) - 1))
        return cls(market, sd, mean)

    def pmf(self, s: float) -> dict[int, float]:
        mu = _location(self.market, s) + self.offset
        nd = NormalDist(mu, self.sigma)
        lo, hi = math.floor(mu - 6 * self.sigma), math.ceil(mu + 6 * self.sigma)
        mass = {k: nd.cdf(k + 0.5) - nd.cdf(k - 0.5) for k in range(lo, hi + 1)}
        if self.market == "spreads":
            mass.pop(0, None)
        total = sum(mass.values())
        return {k: m / total for k, m in mass.items()}


def cover_from_pmf(pmf: dict[int, float], x: float) -> float:
    return sum(p for k, p in pmf.items() if k > x)


@dataclass(frozen=True)
class Anchored:
    """A family pinned to the consensus. `cover(x)` = P(X > x) in home / over space."""

    pmf: dict[int, float]
    s_star: float
    effective_n: float

    def cover(self, x: float) -> float:
        return cover_from_pmf(self.pmf, x)

    def fair_point(self) -> float:
        """Where P(X > x) crosses 0.5, interpolated between half-points."""
        xs = sorted(self.pmf)
        a = xs[0] - 0.5
        while a < xs[-1]:
            if self.cover(a) >= 0.5 > self.cover(a + 1):
                return a + (self.cover(a) - 0.5) / (self.cover(a) - self.cover(a + 1))
            a += 1.0
        return a


def anchor(family, ref_line: float, p_ref: float, *, search: float = 15.0) -> Anchored:
    """Find s* such that the family gives the consensus P(home covers ref_line)
    (spreads) or P(over ref_line) (totals) = p_ref.

    The reference point is the half-point X must exceed: home -5.5 needs
    X > 5.5; over 228.5 needs X > 228.5. Integer reference lines are anchored
    on the no-push share. P(cover) rises as s moves toward the home side, so
    bisection on s is monotone.
    """
    market = family.market
    point = -ref_line if market == "spreads" else ref_line

    def gap(s: float) -> float:
        pmf = family.pmf(s)
        if abs(point - round(point)) < 1e-9:              # integer line: no-push share
            win = cover_from_pmf(pmf, point)
            push = pmf.get(int(round(point)), 0.0)
            prob = win / (1 - push) if push < 1 else 0.0
        else:
            prob = cover_from_pmf(pmf, point)
        return prob - p_ref

    # spreads: a more negative s means a stronger home side; totals: higher s, more overs
    lo, hi = ref_line - search, ref_line + search
    sign = -1.0 if market == "spreads" else 1.0
    f_lo, f_hi = sign * gap(lo), sign * gap(hi)
    if f_lo > 0 or f_hi < 0:
        raise ValueError(f"cannot anchor {market} at {ref_line} to {p_ref:.4f} within ±{search}")
    for _ in range(60):
        mid = 0.5 * (lo + hi)
        if sign * gap(mid) < 0:
            lo = mid
        else:
            hi = mid
    s_star = 0.5 * (lo + hi)
    eff_n = family.effective_n(s_star) if hasattr(family, "effective_n") else math.inf
    return Anchored(family.pmf(s_star), s_star, eff_n)


class TierB:
    """The provider `edge` uses: a primary family and its comparison per market.

    Built only once cfg:distribution.status is VALIDATED; `primary` is the
    family VALIDATION.md selected (cfg:distribution.selected_method).
    """

    def __init__(self, primary: dict[str, object], alternative: dict[str, object]):
        self.primary, self.alternative = primary, alternative

    def anchored(self, market: str, ref_line: float, p_ref: float) -> tuple[Anchored, Anchored]:
        return (anchor(self.primary[market], ref_line, p_ref),
                anchor(self.alternative[market], ref_line, p_ref))

    @staticmethod
    def sigma_translate(primary: Anchored, alternative: Anchored, ref_point: float, x: float) -> float:
        return sigma_translate(primary, alternative, ref_point, x)


def sigma_translate(primary: Anchored, alternative: Anchored, ref_point: float, x: float) -> float:
    """Translation noise from the reference half-point to x (RULES R-12.3):
    binomial SE of the mass moved, plus half the gap to the comparison model."""
    moved = abs(primary.cover(x) - primary.cover(ref_point))
    se = math.sqrt(moved * (1 - moved) / primary.effective_n) if math.isfinite(primary.effective_n) else 0.0
    model_gap = abs(primary.cover(x) - alternative.cover(x)) / 2
    return math.sqrt(se ** 2 + model_gap ** 2)
