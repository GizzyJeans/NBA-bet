"""Platform bias monitor and persistent-mispricing tracker (RULES §11).

Bias is measured on every synchronized platform market, separately from the
game-level edge (P6). One slate's observations share a day's information, so
the bootstrap resamples whole slate dates, never single rows. A bias becomes
USABLE only with enough rows, enough distinct dates, and a 95% interval that
excludes zero; otherwise it is TENTATIVE. A usable bias labels edges `BIAS`;
it never changes an EV.
"""

from __future__ import annotations

import random
import statistics
from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class Observation:
    slate: date
    game: str
    market: str                 # handicap | total
    platform_line: float        # giving / over orientation, effective
    fair_line: float
    giver_home: bool | None     # handicap: is the giving team at home
    minutes_to_tip: float
    p_bias: float               # P_US(laying side covers the platform line) - 0.5
    team: str | None = None     # handicap: the giving team

    @property
    def bias_pts(self) -> float:
        """Handicap: fair giving line - platform giving line (positive favours the
        favourite's backers). Total: fair total - platform total (positive favours overs)."""
        return self.fair_line - self.platform_line

    @property
    def line_size(self) -> float:
        return abs(self.platform_line) if self.market == "handicap" else self.platform_line


@dataclass(frozen=True)
class Estimate:
    mean: float
    low: float
    high: float
    n: int
    days: int
    status: str                 # USABLE | TENTATIVE


def bootstrap(values_by_day: dict[date, list[float]], *, resamples: int, ci: float,
              seed: int = 2026) -> tuple[float, float, float]:
    """Mean and percentile interval, resampling whole days."""
    days = sorted(values_by_day)
    flat = [v for d in days for v in values_by_day[d]]
    mean = statistics.fmean(flat)
    rng = random.Random(seed)
    means = []
    for _ in range(resamples):
        sample = [v for d in rng.choices(days, k=len(days)) for v in values_by_day[d]]
        means.append(statistics.fmean(sample))
    means.sort()
    lo_i = int((1 - ci) / 2 * resamples)
    hi_i = min(int((1 + ci) / 2 * resamples), resamples - 1)
    return mean, means[lo_i], means[hi_i]


def estimate(observations: list[Observation], cfg, value=lambda o: o.bias_pts) -> Estimate | None:
    if not observations:
        return None
    by_day: dict[date, list[float]] = {}
    for o in observations:
        by_day.setdefault(o.slate, []).append(value(o))
    boot = cfg.get("bias.bootstrap")
    mean, lo, hi = bootstrap(by_day, resamples=boot["resamples"], ci=boot["ci"])
    n, days = len(observations), len(by_day)
    usable = (n >= cfg.get("bias.bias_min_n") and days >= cfg.get("bias.bias_min_days")
              and (lo > 0 or hi < 0))
    return Estimate(mean, lo, hi, n, days, "USABLE" if usable else "TENTATIVE")


def splits(observations: list[Observation]) -> dict[str, list[Observation]]:
    """RULES R-11.2: market, home/away of the giving side, line size, time to tip."""
    out: dict[str, list[Observation]] = {}

    def put(key, o):
        out.setdefault(key, []).append(o)

    for o in observations:
        put(f"{o.market}", o)
        if o.market == "handicap" and o.giver_home is not None:
            put(f"handicap:giver_{'home' if o.giver_home else 'away'}", o)
        if o.market == "handicap":
            put(f"handicap:size_{'0-3' if o.line_size < 3 else '3-7' if o.line_size < 7 else '7+'}", o)
        put(f"{o.market}:tip_{'<2h' if o.minutes_to_tip < 120 else '2h+'}", o)
    return out


def hypotheses(observations: list[Observation], cfg) -> dict[str, Estimate | None]:
    """H-MLB-1: platform totals below the US fair total. H-MLB-2: larger handicaps
    shaded toward the receiving side (negative bias_pts on lines of 7+)."""
    totals = [o for o in observations if o.market == "total"]
    large = [o for o in observations if o.market == "handicap" and o.line_size >= 7]
    return {"H-MLB-1": estimate(totals, cfg), "H-MLB-2": estimate(large, cfg)}


def persistent(observations: list[Observation], cfg) -> list[tuple[str, Estimate]]:
    """Teams whose last window_obs handicap observations lean one way (report only)."""
    p = cfg.get("bias.persistence")
    flagged = []
    by_team: dict[str, list[Observation]] = {}
    for o in sorted(observations, key=lambda o: o.slate):
        if o.market == "handicap" and o.team:
            by_team.setdefault(o.team, []).append(o)
    for tricode, obs in sorted(by_team.items()):
        recent = obs[-p["window_obs"]:]
        if len(recent) < p["window_obs"]:
            continue
        by_day: dict[date, list[float]] = {}
        for o in recent:
            by_day.setdefault(o.slate, []).append(o.bias_pts)
        mean, lo, hi = bootstrap(by_day, resamples=cfg.get("bias.bootstrap")["resamples"], ci=p["ci"])
        if abs(mean) >= p["min_abs_mean_pts"] and (lo > 0 or hi < 0):
            flagged.append((tricode, Estimate(mean, lo, hi, len(recent), len(by_day), "PERSISTENT")))
    return flagged
