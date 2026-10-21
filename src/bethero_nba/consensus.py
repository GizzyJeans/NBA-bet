"""US consensus per line and Tier A cover probabilities.

For every line a book quotes on both sides, the book's price is de-vigged with
each method; the consensus is the median across books (MLB
`market.summarise_line`, GizzyJeans/MLB@9ca07aa). There is no sharp-book weighting (RULES R-5.4), and
no leave-one-out either: the bet is struck on the Asian platform, which is
not one of the books being averaged.

Probabilities are stored for the home side (spreads, moneyline) or the over
(totals). `cover` turns them into P(X > x) for the half-points a ticket needs,
with X the laying side's margin or the total; it returns None when fewer than
`min_books` books quote that exact line, which is what makes a leg Tier A or
not (RULES R-6.2, R-6.3).
"""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Callable, Sequence

from .odds import devig
from .oddsapi import Game, pair_sides

MARKETS = ("h2h", "spreads", "totals")


@dataclass(frozen=True)
class LineConsensus:
    market: str
    line_key: float | None
    books: tuple[str, ...]
    book_probs: dict[str, dict[str, float]]      # method -> book -> P(home side / over)
    probs: dict[str, float]                      # method -> median

    @property
    def n_books(self) -> int:
        return len(self.books)

    def sigma_books(self, method: str) -> float:
        """Standard error of the median across books: 1.2533 * (IQR / 1.349) / sqrt(n)."""
        values = list(self.book_probs[method].values())
        if len(values) < 2:
            return 0.0
        q1, _, q3 = statistics.quantiles(values, n=4)
        return 1.2533 * ((q3 - q1) / 1.349) / math.sqrt(len(values))


@dataclass
class GameConsensus:
    game: Game
    us_ts: datetime
    methods: tuple[str, ...]
    lines: dict[tuple[str, float | None], LineConsensus] = field(default_factory=dict)
    dropped_stale: int = 0

    def line(self, market: str, line_key: float | None) -> LineConsensus | None:
        if line_key is not None:
            line_key = round(line_key * 2) / 2
        return self.lines.get((market, line_key))

    def l_ref(self, market: str) -> float | None:
        """The line most books quote (ties: the one nearer zero, then the lower)."""
        candidates = [lc for (m, _), lc in self.lines.items() if m == market and lc.line_key is not None]
        if not candidates:
            return None
        best = max(candidates, key=lambda lc: (lc.n_books, -abs(lc.line_key), -lc.line_key))
        return best.line_key

    def line_for_point(self, market: str, giver: str, x: float) -> tuple[LineConsensus | None, bool]:
        """The quoted line behind P(X > x), and whether its probability must be flipped."""
        if market == "totals":
            return self.line(market, x), False
        if market == "h2h":
            return self.line(market, None), giver != "home"
        if giver == "home":
            return self.line(market, -x), False
        return self.line(market, x), True

    def book_covers(self, market: str, giver: str, method: str, x: float) -> dict[str, float]:
        """Each book's own P(X > x), in the same orientation as `cover`."""
        lc, flip = self.line_for_point(market, giver, x)
        if lc is None:
            return {}
        return {book: (1.0 - p if flip else p) for book, p in lc.book_probs[method].items()}

    def cover(self, market: str, giver: str, method: str, min_books: int) -> Callable[[float], float | None]:
        """P(X > x) at half-point x from lines quoted by at least `min_books` books.

        spreads, giver "home": X = home margin; P(X > x) = P(home covers -x).
        spreads, giver "away": X = away margin; P(X > x) = 1 - P(home covers +x).
        totals: X = total; P(X > x) = P(over x).
        h2h: X = home margin and only x = +-0.5 exist: P(home wins), no ties.
        """
        def lookup(key: float | None) -> float | None:
            lc = self.line(market, key)
            return lc.probs[method] if lc is not None and lc.n_books >= min_books else None

        def cover(x: float) -> float | None:
            if market == "totals":
                return lookup(x)
            if market == "h2h":
                p = lookup(None)
                if p is None or abs(abs(x) - 0.5) > 1e-9:
                    return None
                return p if giver == "home" else 1.0 - p
            if giver == "home":
                return lookup(-x)
            p = lookup(x)
            return None if p is None else 1.0 - p

        return cover


def _sides(market: str, game: Game) -> tuple[str, str]:
    return ("Over", "Under") if market == "totals" else (game.home_team, game.away_team)


def build(game: Game, us_ts: datetime, *, methods: Sequence[str], max_age_min: float) -> GameConsensus:
    """Consensus for every line of one game; quotes older than `max_age_min` at
    `us_ts` are dropped (RULES R-4.3) and counted."""
    cutoff = us_ts - timedelta(minutes=max_age_min)
    fresh = [q for q in game.quotes if q.last_update >= cutoff]
    result = GameConsensus(game, us_ts, tuple(methods), dropped_stale=len(game.quotes) - len(fresh))
    keys: dict[tuple[str, float | None], list] = {}
    for q in fresh:
        if q.market in MARKETS:
            keys.setdefault((q.market, q.line_key), []).append(q)
    for (market, line_key), quotes in keys.items():
        first, second = _sides(market, game)
        book_probs: dict[str, dict[str, float]] = {m: {} for m in methods}
        books = []
        for book, a, b in pair_sides(quotes, first, second):
            books.append(book)
            for method in methods:
                book_probs[method][book] = devig([a.decimal, b.decimal], method)[0]
        if not books:
            continue
        probs = {m: statistics.median(book_probs[m].values()) for m in methods}
        result.lines[(market, line_key)] = LineConsensus(market, line_key, tuple(books), book_probs, probs)
    return result
