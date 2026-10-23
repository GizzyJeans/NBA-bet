"""Closing-line value and the pause rule (RULES §14).

The platform holds its price and moves its line, so price CLV is
structurally zero (lesson 5). `clv_line` measures what the platform actually
moves: the effective win probability of the bet line against that of the
platform's closing line, both under the US closing fair distribution.
`clv_us` is the ticket's EV under the US close at the platform price.
Missing closes give None, never an imputed number.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass
from datetime import date
from typing import Callable, Sequence

from .bias import bootstrap
from .odds import Leg, effective_win_probability, expected_value, ticket_outcomes


def clv_line(bet_legs: Sequence[Leg], close_legs: Sequence[Leg] | None, price: float, laying: bool,
             cover_close: Callable[[float], float] | None) -> float | None:
    if close_legs is None or cover_close is None:
        return None
    bet = effective_win_probability(ticket_outcomes(bet_legs, price, cover_close, laying))
    close = effective_win_probability(ticket_outcomes(close_legs, price, cover_close, laying))
    return bet - close


def clv_us(legs: Sequence[Leg], price: float, laying: bool, cover_close: Callable[[float], float] | None,
           ev_at_bet: float | None) -> tuple[float | None, float | None]:
    """(EV under the US close, change since bet time)."""
    if cover_close is None:
        return None, None
    ev_close = expected_value(ticket_outcomes(legs, price, cover_close, laying))
    return ev_close, (ev_close - ev_at_bet if ev_at_bet is not None else None)


@dataclass(frozen=True)
class PauseCheck:
    paused: bool
    n: int
    mean: float | None
    low: float | None
    high: float | None


def pause_check(values: list[tuple[date, float]], cfg) -> PauseCheck:
    """RULES R-14.7 on the most recent `pause_min_n` or more recommendations."""
    n_min = cfg.get("clv.pause_min_n")
    if len(values) < n_min:
        return PauseCheck(False, len(values), None, None, None)
    by_day: dict[date, list[float]] = {}
    for day, v in values:
        by_day.setdefault(day, []).append(v)
    boot = cfg.get("bias.bootstrap")
    mean, lo, hi = bootstrap(by_day, resamples=boot["resamples"], ci=cfg.get("clv.pause_ci"))
    return PauseCheck(mean < 0 and hi < 0, len(values), mean, lo, hi)


@dataclass(frozen=True)
class GoLiveCheck:
    ready: bool
    n: int
    days: int
    mean: float | None
    low: float | None
    high: float | None


def golive_check(values: list[tuple[date, float]], cfg) -> GoLiveCheck:
    """Go-live readiness as Eric accepted it (2026-10-23, strict; VALIDATION.md §3):
    at least `golive.min_bets` prospective shadow bets with CLV_US over at least
    `golive.min_slate_days` slate dates, and the date-block bootstrap CI of mean CLV_US
    entirely above 0. Readiness only: the mode changes on Eric's message alone (R-12.7)."""
    by_day: dict[date, list[float]] = {}
    for day, v in values:
        by_day.setdefault(day, []).append(v)
    if len(values) < cfg.get("golive.min_bets") or len(by_day) < cfg.get("golive.min_slate_days"):
        return GoLiveCheck(False, len(values), len(by_day), None, None, None)
    boot = cfg.get("bias.bootstrap")
    mean, lo, hi = bootstrap(by_day, resamples=boot["resamples"], ci=cfg.get("golive.ci"))
    return GoLiveCheck(mean > 0 and lo > 0, len(values), len(by_day), mean, lo, hi)


def summary(values: list[float]) -> dict[str, float | int | None]:
    if not values:
        return {"n": 0, "mean": None}
    return {"n": len(values), "mean": statistics.fmean(values)}
