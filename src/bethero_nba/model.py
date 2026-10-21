"""Veto-only team ratings (RULES §8). The model never creates or sizes a bet (P1).

Ratings are opponent-adjusted by ridge regression on game results:

    margin = hca + r_home - r_away + e         (expected home margin)
    total  = mu + t_home + t_away + e          (expected total)

Home-court advantage is a fitted parameter, not a textbook constant. The
ridge penalty is k games per team toward a prior (last season's ratings
regressed to the mean, or zero): a team with g games is pulled toward the
prior with weight about k / (g + k), which is the early-season shrinkage of
R-8.3; k is chosen by backtest (cfg:model.prior_shrinkage_k_games).

Possession-based ratings need box scores (possessions per game), which are on
nba.com and blocked from the cloud environment; until they are available the
model works on points, and it stays OFF in the config until Phase 3 has
evaluated it.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from statistics import NormalDist


@dataclass(frozen=True)
class GameResult:
    home: str
    away: str
    home_score: int
    away_score: int


def _solve(a: list[list[float]], b: list[float]) -> list[float]:
    """Gaussian elimination with partial pivoting (small dense systems)."""
    n = len(b)
    m = [row[:] + [b[i]] for i, row in enumerate(a)]
    for col in range(n):
        pivot = max(range(col, n), key=lambda r: abs(m[r][col]))
        if abs(m[pivot][col]) < 1e-12:
            raise ValueError("singular system")
        m[col], m[pivot] = m[pivot], m[col]
        for r in range(col + 1, n):
            f = m[r][col] / m[col][col]
            for c in range(col, n + 1):
                m[r][c] -= f * m[col][c]
    x = [0.0] * n
    for r in range(n - 1, -1, -1):
        x[r] = (m[r][n] - sum(m[r][c] * x[c] for c in range(r + 1, n))) / m[r][r]
    return x


def _ridge(rows: list[tuple[dict[int, float], float]], n: int, penalised: range,
           k: float, prior: list[float]) -> list[float]:
    """Minimise sum (y - x.b)^2 + k * sum_{j in penalised} (b_j - prior_j)^2."""
    a = [[0.0] * n for _ in range(n)]
    b = [0.0] * n
    for x, y in rows:
        for i, xi in x.items():
            b[i] += xi * y
            for j, xj in x.items():
                a[i][j] += xi * xj
    for j in penalised:
        a[j][j] += k
        b[j] += k * prior[j]
    return _solve(a, b)


@dataclass(frozen=True)
class Ratings:
    hca: float
    margin: dict[str, float]
    mu: float
    total: dict[str, float]
    sigma_margin: float
    sigma_total: float
    games: int

    def predict(self, home: str, away: str) -> dict[str, float]:
        return {"home_margin": self.hca + self.margin.get(home, 0.0) - self.margin.get(away, 0.0),
                "total": self.mu + self.total.get(home, 0.0) + self.total.get(away, 0.0)}

    def p_home_win(self, home: str, away: str) -> float:
        margin = self.predict(home, away)["home_margin"]
        if self.sigma_margin <= 0:
            return 0.5 if margin == 0 else float(margin > 0)
        return 1.0 - NormalDist(margin, self.sigma_margin).cdf(0.0)


def fit(games: list[GameResult], k: float, prior_margin: dict[str, float] | None = None,
        prior_total: dict[str, float] | None = None) -> Ratings:
    if not games:
        raise ValueError("no games to fit")
    teams = sorted({g.home for g in games} | {g.away for g in games})
    index = {t: i + 1 for i, t in enumerate(teams)}        # 0 = intercept (hca or mu)
    n = len(teams) + 1
    pm = [0.0] + [(prior_margin or {}).get(t, 0.0) for t in teams]
    pt = [0.0] + [(prior_total or {}).get(t, 0.0) for t in teams]
    margin_rows = [({0: 1.0, index[g.home]: 1.0, index[g.away]: -1.0}, g.home_score - g.away_score)
                   for g in games]
    total_rows = [({0: 1.0, index[g.home]: 1.0, index[g.away]: 1.0}, g.home_score + g.away_score)
                  for g in games]
    bm = _ridge(margin_rows, n, range(1, n), k, pm)
    bt = _ridge(total_rows, n, range(1, n), k, pt)

    def residual_sd(rows, beta):
        res = [y - sum(beta[i] * x for i, x in xs.items()) for xs, y in rows]
        return math.sqrt(sum(r * r for r in res) / max(len(res) - 1, 1))

    return Ratings(bm[0], {t: bm[index[t]] for t in teams}, bt[0], {t: bt[index[t]] for t in teams},
                   residual_sd(margin_rows, bm), residual_sd(total_rows, bt), len(games))


def regress_prior(ratings: dict[str, float], keep: float) -> dict[str, float]:
    """Last season's ratings pulled toward the league mean (keep = share retained)."""
    mean = sum(ratings.values()) / len(ratings) if ratings else 0.0
    return {t: mean + keep * (r - mean) for t, r in ratings.items()}


# ------------------------------------------------------------------ metrics


def mae(predictions: list[float], targets: list[float]) -> float:
    return sum(abs(p - t) for p, t in zip(predictions, targets)) / len(targets)


def brier(probabilities: list[float], outcomes: list[int]) -> float:
    return sum((p - o) ** 2 for p, o in zip(probabilities, outcomes)) / len(outcomes)


def log_loss(probabilities: list[float], outcomes: list[int], eps: float = 1e-12) -> float:
    total = 0.0
    for p, o in zip(probabilities, outcomes):
        p = min(max(p, eps), 1 - eps)
        total -= o * math.log(p) + (1 - o) * math.log(1 - p)
    return total / len(outcomes)
