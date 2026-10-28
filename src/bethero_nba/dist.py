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
import json
import math
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from statistics import NormalDist
from typing import Iterable

DIST_SCHEMA = "bethero-nba-dist/1"
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
    overtime clusters) survives. Each bucket weighs the same whatever its size,
    so where history is sparse or lies on one side of s the mixture leans
    toward the nearby lines and need not move one way with s (ERRATA E-012).
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

    @classmethod
    def from_buckets(cls, market: str, buckets: dict[float, dict[int, int]], *, bucket_width: float,
                     bandwidth: float) -> "EmpiricalFamily":
        family = cls(market, (), bucket_width, bandwidth)
        family.buckets = {float(b): {int(x): int(n) for x, n in counts.items()} for b, counts in buckets.items()}
        return family

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


class ShiftedEmpiricalFamily(EmpiricalFamily):
    """The empirical family with each neighbouring bucket moved to the target line
    before mixing (VALIDATION.md §4 L2).

    A bucket at line b contributes its outcomes shifted by location(s) -
    location(b), each outcome's mass split between the two nearest integers, so
    the mixture stays centred on s however unevenly the history lies around it.
    The unshifted mixture leans toward the denser lines beside a sparse one,
    which is why it cannot be anchored at large spreads. Spreads drop the tied
    margin, as the normal family does.
    """

    def pmf(self, s: float) -> dict[int, float]:
        weights = self._weights(s)
        mass: dict[int, float] = {}
        total = 0.0
        for b, w in weights.items():
            d = _location(self.market, s) - _location(self.market, b)
            step = math.floor(d)
            frac = d - step
            n = sum(self.buckets[b].values())
            for x, count in self.buckets[b].items():
                p = w * count / n
                mass[x + step] = mass.get(x + step, 0.0) + p * (1 - frac)
                if frac > 0:
                    mass[x + step + 1] = mass.get(x + step + 1, 0.0) + p * frac
            total += w
        if total == 0:
            raise ValueError(f"no history within reach of line {s}")
        if self.market == "spreads":
            mass.pop(0, None)
        z = sum(mass.values())
        return {x: m / z for x, m in mass.items() if m > 0}


class PooledShiftedEmpiricalFamily(EmpiricalFamily):
    """The shifted family with each game, not each bucket, carrying its bucket's
    kernel weight (VALIDATION.md §5 L6): a bucket of n games enters with weight
    w x n, the usual kernel estimator over games, each game's outcome moved to the
    target line. One- or two-game buckets at nearby lines no longer decide the
    mixture, which the per-bucket weights of the shifted family let them do.
    """

    def pmf(self, s: float) -> dict[int, float]:
        weights = self._weights(s)
        mass: dict[int, float] = {}
        total = 0.0
        for b, w in weights.items():
            d = _location(self.market, s) - _location(self.market, b)
            step = math.floor(d)
            frac = d - step
            for x, count in self.buckets[b].items():
                p = w * count
                mass[x + step] = mass.get(x + step, 0.0) + p * (1 - frac)
                if frac > 0:
                    mass[x + step + 1] = mass.get(x + step + 1, 0.0) + p * frac
                total += p
        if total == 0:
            raise ValueError(f"no history within reach of line {s}")
        if self.market == "spreads":
            mass.pop(0, None)
        z = sum(mass.values())
        return {x: m / z for x, m in mass.items() if m > 0}


FALLBACKS = {"shifted_empirical": ShiftedEmpiricalFamily, "pooled_shifted_empirical": PooledShiftedEmpiricalFamily}


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
    family: str = ""                   # the family's class name, for the ledger

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


def line_probability(family, s: float, ref_line: float) -> float:
    """What anchoring matches at line s: P(home covers ref_line) (spreads) or P(over
    ref_line) (totals); at an integer line, the share of non-push outcomes."""
    point = -ref_line if family.market == "spreads" else ref_line
    pmf = family.pmf(s)
    if abs(point - round(point)) < 1e-9:
        win = cover_from_pmf(pmf, point)
        push = pmf.get(int(round(point)), 0.0)
        return win / (1 - push) if push < 1 else 0.0
    return cover_from_pmf(pmf, point)


SEARCH = (3.0, 6.0, 15.0)


def find_bracket(family, ref_line: float, p_ref: float, search: tuple[float, ...] = SEARCH):
    """The narrowest window (lo, hi) around the line where the family crosses p_ref,
    or None. A wide window around a 15-point line reaches lines the empirical family
    has no history for (ERRATA E-007), so the narrow ones come first."""
    sign = -1.0 if family.market == "spreads" else 1.0
    for width in search:
        lo, hi = ref_line - width, ref_line + width
        try:
            f_lo = sign * (line_probability(family, lo, ref_line) - p_ref)
            f_hi = sign * (line_probability(family, hi, ref_line) - p_ref)
        except ValueError:                 # no history that far out; a wider window is no better
            return None
        if f_lo <= 0 <= f_hi:
            return lo, hi
    return None


GRID_STEP = 0.25


class NotOneWay(ValueError):
    """A family crossed p_ref but did not move one way across the window (VALIDATION.md §5 L8)."""


def moves_one_way(family, ref_line: float, bracket: tuple[float, float], step: float = GRID_STEP,
                  memo: dict | None = None) -> bool:
    """Whether the anchored probability never moves the wrong way across the bracket, on a
    `step`-point grid (VALIDATION.md §4 T2, §5 L8): for spreads P(home covers) must not rise
    as s increases; for totals P(over) must not fall."""
    memo = {} if memo is None else memo
    lo, hi = bracket
    values = []
    for i in range(int(round((hi - lo) / step)) + 1):
        key = (ref_line, lo + i * step)
        if key not in memo:
            memo[key] = line_probability(family, key[1], ref_line)
        values.append(memo[key] if family.market == "spreads" else -memo[key])
    return all(b - a <= 1e-9 for a, b in zip(values, values[1:]))


def anchor(family, ref_line: float, p_ref: float, *, search: tuple[float, ...] = SEARCH,
           one_way: bool = False) -> Anchored:
    """Find s* such that the family gives the consensus P(home covers ref_line)
    (spreads) or P(over ref_line) (totals) = p_ref.

    The reference point is the half-point X must exceed: home -5.5 needs
    X > 5.5; over 228.5 needs X > 228.5. Integer reference lines are anchored
    on the no-push share. For the normal family P(cover) falls as s moves away
    from the home side (rises with s for totals), so bisection finds the one
    root. The empirical families need not move one way where history is sparse
    (VALIDATION.md §4, §5): when one does not cross p_ref inside the window it
    raises, and with `one_way` it also raises when it crosses without moving one
    way across the window (§5 L8); Tier B then fails closed (R-6.4).
    """
    market = family.market
    sign = -1.0 if market == "spreads" else 1.0
    bracket = find_bracket(family, ref_line, p_ref, search)
    if bracket is None:
        raise ValueError(f"cannot anchor {market} at {ref_line} to {p_ref:.4f} within ±{max(search)}")
    if one_way and not moves_one_way(family, ref_line, bracket):
        raise NotOneWay(f"{type(family).__name__} does not move one way around {market} {ref_line}")
    lo, hi = bracket
    for _ in range(60):
        mid = 0.5 * (lo + hi)
        if sign * (line_probability(family, mid, ref_line) - p_ref) < 0:
            lo = mid
        else:
            hi = mid
    s_star = 0.5 * (lo + hi)
    eff_n = family.effective_n(s_star) if hasattr(family, "effective_n") else math.inf
    return Anchored(family.pmf(s_star), s_star, eff_n, type(family).__name__)


def save_families(path: Path | str, empirical: EmpiricalFamily, normal: NormalFamily, meta: dict) -> None:
    """Both families of one market as aggregate counts: per line bucket, how many
    games ended at each margin (or total). No game rows (VALIDATION.md D5)."""
    head = {"schema": DIST_SCHEMA, "market": empirical.market, **meta,
            "normal": {"sigma": normal.sigma, "offset": normal.offset},
            "empirical": {"bucket_width": empirical.bucket_width, "bandwidth": empirical.bandwidth}}
    buckets = ",\n".join(f'  "{b:g}": ' + json.dumps({str(x): n for x, n in sorted(counts.items())},
                                                     separators=(",", ":"))
                         for b, counts in sorted(empirical.buckets.items()))
    text = json.dumps(head, indent=1)[:-1].rstrip() + ',\n "buckets": {\n' + buckets + "\n }\n}\n"
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


def load_families(path: Path | str) -> tuple[EmpiricalFamily, NormalFamily, dict]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if data.get("schema") != DIST_SCHEMA:
        raise ValueError(f"{path}: not a {DIST_SCHEMA} file")
    e = data["empirical"]
    empirical = EmpiricalFamily.from_buckets(data["market"], {float(b): c for b, c in data["buckets"].items()},
                                             bucket_width=e["bucket_width"], bandwidth=e["bandwidth"])
    normal = NormalFamily(data["market"], data["normal"]["sigma"], data["normal"]["offset"])
    return empirical, normal, data


def load_tier_b(directory: Path | str, markets: Iterable[str], selected: dict[str, str],
                bandwidths: dict[str, float] | None = None,
                fallback: dict[str, str] | None = None) -> "TierB | None":
    """TierB for the validated markets only, from the files `validate --write-dist` wrote.
    `selected`, `bandwidths` and `fallback` are the config's (keyed spread / total); a file
    that disagrees with them, or was not validated, is refused rather than used. A market
    with a fallback (`pooled_shifted_empirical`, VALIDATION.md §5) gets that family, built
    from the same counts, as the comparison where the empirical family cannot be anchored
    or does not move one way (§5 L7)."""
    primary, alternative, backup = {}, {}, {}
    for market in markets:
        path = Path(directory) / f"{market}.json"
        empirical, normal, meta = load_families(path)
        scale = "spread" if market == "spreads" else "total"
        if not meta.get("validated") or meta.get("selected_method") != selected[scale]:
            raise ValueError(f"{path}: not the family the config validated for {market}")
        if bandwidths is not None and abs(empirical.bandwidth - bandwidths[scale]) > 1e-9:
            raise ValueError(f"{path}: bandwidth {empirical.bandwidth} differs from the config's {bandwidths[scale]}")
        first, second = (empirical, normal) if selected[scale] == "empirical" else (normal, empirical)
        primary[market], alternative[market] = first, second
        name = (fallback or {}).get(scale, "none")
        if name != "none":
            if name not in FALLBACKS or second is not empirical:
                raise ValueError(f"comparison fallback {name!r} is not defined for {market}")
            backup[market] = FALLBACKS[name].from_buckets(
                market, empirical.buckets, bucket_width=empirical.bucket_width, bandwidth=empirical.bandwidth)
    return TierB(primary, alternative, backup) if primary else None


class TierB:
    """The provider `edge` uses: a primary family and its comparison per market.

    Built only once cfg:distribution.status is VALIDATED, and only for the
    markets in cfg:distribution.validated_markets; `primary` is the family
    VALIDATION.md selected (cfg:distribution.selected_method).
    """

    def __init__(self, primary: dict[str, object], alternative: dict[str, object],
                 fallback: dict[str, object] | None = None):
        self.primary, self.alternative = primary, alternative
        self.fallback = fallback or {}      # comparison where `alternative` cannot be anchored

    def fair(self, market: str, ref_line: float, p_ref: float) -> Anchored:
        """The selected family alone pinned to the consensus, for the fair line (RULES R-5.6):
        the comparison only widens σ_translate, so it never moves the fair line."""
        return anchor(self.primary[market], ref_line, p_ref)

    def anchored(self, market: str, ref_line: float, p_ref: float) -> tuple[Anchored, Anchored]:
        """Both families pinned to the consensus. A comparison that cannot be anchored, or
        does not move one way across its window, counts as not anchored (VALIDATION.md §5
        L8); the fallback replaces it if there is one, else this raises and Tier B fails
        closed."""
        first = anchor(self.primary[market], ref_line, p_ref)
        try:
            second = anchor(self.alternative[market], ref_line, p_ref, one_way=True)
        except ValueError:
            if market not in self.fallback:
                raise
            second = anchor(self.fallback[market], ref_line, p_ref, one_way=True)
        return first, second

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
