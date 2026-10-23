"""The Odds API client, quote normalisation and the credit budget.

Ported from MLB `src/mlbline/odds.py` (GizzyJeans/MLB@9ca07aa). The upstream payload nests game ->
bookmaker -> market -> outcome; everything here flattens to `Quote` rows that
keep each book's `last_update`, since a stale quote is not a real price.

Spreads are keyed to the home team (`line_key`): a book quoting "home -5.5 /
away +5.5" and one quoting "home +5.5 / away -5.5" price two different
markets, and pooling them by absolute value invents edges (MLB README).

Credits: a live odds pull costs markets x regions; the remaining balance comes
back in the `x-requests-*` headers, and `Budget` refuses a pull that would cut
into the reserve (RULES R-5.8).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable, Iterator
from zoneinfo import ZoneInfo

from .net import Fetched, HttpClient
from .odds import american_to_decimal

BASE = "https://api.the-odds-api.com/v4"
EASTERN = ZoneInfo("America/New_York")


class BudgetRefused(RuntimeError):
    pass


# ----------------------------------------------------------------- requests


def fetch_odds(client: HttpClient, api_key: str, sport: str, regions: Iterable[str],
               markets: Iterable[str]) -> Fetched:
    return client.get(f"{BASE}/sports/{sport}/odds/", {
        "apiKey": api_key, "regions": ",".join(regions), "markets": ",".join(markets),
        "oddsFormat": "american", "dateFormat": "iso"})


def fetch_scores(client: HttpClient, api_key: str, sport: str, days_from: int) -> Fetched:
    return client.get(f"{BASE}/sports/{sport}/scores/", {
        "apiKey": api_key, "daysFrom": str(days_from), "dateFormat": "iso"})


def fetch_participants(client: HttpClient, api_key: str, sport: str) -> Fetched:
    return client.get(f"{BASE}/sports/{sport}/participants", {"apiKey": api_key})


def odds_cost(regions: Iterable[str], markets: Iterable[str]) -> int:
    return len(list(regions)) * len(list(markets))


@dataclass(frozen=True)
class Usage:
    remaining: int | None
    used: int | None
    last: int | None


def usage_from_headers(headers: dict[str, str]) -> Usage:
    def number(key: str) -> int | None:
        value = headers.get(key)
        try:
            return int(float(value)) if value is not None else None
        except ValueError:
            return None
    return Usage(number("x-requests-remaining"), number("x-requests-used"),
                 number("x-requests-last"))


class Budget:
    """Pull log in JSONL; refuses pulls over the daily count or into the reserve."""

    def __init__(self, log_path: Path | str, *, max_calls_per_day: int, min_remaining_reserve: int):
        self.log_path = Path(log_path)
        self.max_calls_per_day = max_calls_per_day
        self.min_remaining_reserve = min_remaining_reserve

    @classmethod
    def from_config(cls, cfg, log_path: Path | str) -> "Budget":
        return cls(log_path, max_calls_per_day=cfg.get("us_odds.max_calls_per_day"),
                   min_remaining_reserve=cfg.get("us_odds.min_remaining_reserve"))

    def _rows(self) -> list[dict]:
        if not self.log_path.exists():
            return []
        return [json.loads(line) for line in self.log_path.read_text(encoding="utf-8").splitlines()
                if line.strip()]

    def check(self, now: datetime, cost: int, kind: str = "odds") -> None:
        rows = self._rows()
        today = now.astimezone(timezone.utc).date().isoformat()
        if kind == "odds":
            pulls_today = sum(1 for r in rows if r["kind"] == "odds" and r["at"][:10] == today)
            if pulls_today >= self.max_calls_per_day:
                raise BudgetRefused(f"{pulls_today} odds pulls already on {today} (UTC)")
        known = [r["remaining"] for r in rows if r.get("remaining") is not None]
        if known and known[-1] - cost < self.min_remaining_reserve:
            raise BudgetRefused(f"{known[-1]} credits left; a {cost}-credit pull would cut "
                                f"into the {self.min_remaining_reserve}-credit reserve")

    def record(self, fetched: Fetched, kind: str) -> Usage:
        usage = usage_from_headers(fetched.headers)
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        stored = None
        if fetched.path:
            root = self.log_path.resolve().parent.parent
            path = fetched.path.resolve()
            stored = (path.relative_to(root) if path.is_relative_to(root) else path).as_posix()
        row = {"at": fetched.retrieved_at.astimezone(timezone.utc).isoformat(), "kind": kind,
               "remaining": usage.remaining, "used": usage.used, "last": usage.last, "file": stored}
        with self.log_path.open("a", encoding="utf-8", newline="\n") as fh:
            fh.write(json.dumps(row) + "\n")
        return usage


# -------------------------------------------------------------- normalising


@dataclass(frozen=True)
class Quote:
    game_id: str
    book: str
    market: str           # "h2h" | "spreads" | "totals"
    side: str             # team name, or "Over" / "Under"
    point: float | None
    american: float
    last_update: datetime
    line_key: float | None = None

    @property
    def decimal(self) -> float:
        return american_to_decimal(self.american)


@dataclass
class Game:
    game_id: str
    commence_time: datetime
    home_team: str
    away_team: str
    quotes: list[Quote] = field(default_factory=list)

    def select(self, market: str, line_key: float | None = None) -> list[Quote]:
        out = [q for q in self.quotes if q.market == market]
        if line_key is not None:
            out = [q for q in out if q.line_key is not None and abs(q.line_key - line_key) < 1e-9]
        return out

    def line_keys(self, market: str) -> list[float]:
        return sorted({q.line_key for q in self.quotes if q.market == market and q.line_key is not None})


def parse_ts(raw: str) -> datetime:
    return datetime.fromisoformat(raw.replace("Z", "+00:00"))


def eastern_date(moment: datetime) -> date:
    """US Eastern calendar date: one night's slate spans two UTC dates."""
    return moment.astimezone(EASTERN).date()


def _line_key(market: str, point: float | None, side: str, home_team: str) -> float | None:
    if point is None:
        return None
    if market != "spreads":
        return float(point)
    return (float(point) if side == home_team else -float(point)) + 0.0   # no -0.0 keys


def normalise(payload: list[dict]) -> list[Game]:
    games: list[Game] = []
    for raw in payload:
        game = Game(raw["id"], parse_ts(raw["commence_time"]), raw["home_team"], raw["away_team"])
        for book in raw.get("bookmakers", []):
            for market in book.get("markets", []):
                updated = parse_ts(market.get("last_update") or book["last_update"])
                for outcome in market.get("outcomes", []):
                    point = outcome.get("point")
                    game.quotes.append(Quote(
                        game.game_id, book["key"], market["key"], outcome["name"], point,
                        float(outcome["price"]), updated,
                        _line_key(market["key"], point, outcome["name"], game.home_team)))
        games.append(game)
    return games


def pair_sides(quotes: Iterable[Quote], first: str, second: str) -> Iterator[tuple[str, Quote, Quote]]:
    """(book, first-side quote, second-side quote) for books quoting both sides."""
    by_book: dict[str, dict[str, Quote]] = {}
    for q in quotes:
        by_book.setdefault(q.book, {})[q.side] = q
    for book, sides in sorted(by_book.items()):
        if first in sides and second in sides:
            yield book, sides[first], sides[second]


@dataclass(frozen=True)
class Score:
    game_id: str
    commence_time: datetime
    home_team: str
    away_team: str
    home_score: int
    away_score: int


def completed_scores(payload: list[dict]) -> list[Score]:
    """Final scores of completed games. Overtime is included: the API reports
    final scores, which is what the platform settles on (RULES R-3.5)."""
    out: list[Score] = []
    for raw in payload:
        if not raw.get("completed") or not raw.get("scores"):
            continue
        points = {s["name"]: int(s["score"]) for s in raw["scores"]}
        out.append(Score(raw["id"], parse_ts(raw["commence_time"]), raw["home_team"],
                         raw["away_team"], points[raw["home_team"]], points[raw["away_team"]]))
    return out


def within(moment: datetime, other: datetime, hours: float) -> bool:
    return abs(moment - other) <= timedelta(hours=hours)
