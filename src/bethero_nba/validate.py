"""Validation harness for rules/nba/VALIDATION.md (RULES R-7.4, R-8.6, Phase 3).

    python -m bethero_nba.validate --history data/history/games.csv \
        --holdout 2024-25,2025-26 --out rules/nba/VALIDATION.md

Three checks, each with N reported:

1. Distributions: empirical vs discretized normal on holdout seasons, log
   loss of win / push / lose for tickets at offsets around the closing line
   (where translation happens), plus calibration and the bug-detection bands.
2. De-vig methods: log loss and Brier of the closing moneyline's de-vigged home
   win probability against results, per method (needs moneyline columns).
3. Model: walk-forward MAE against the closing spread and total, and Brier and
   log loss of the home win probability, by season phase.

Nothing here runs without a history file with documented provenance.
"""

from __future__ import annotations

import argparse
import math
from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from . import cli, model
from .dist import EmpiricalFamily, HistoryRow, NormalFamily, cover_from_pmf, load_history
from .odds import american_to_decimal, devig

OFFSETS = (-1.5, -1.0, -0.5, 0.0, 0.5, 1.0, 1.5)
EPS = 1e-12


@dataclass(frozen=True)
class OffsetResult:
    offset: float
    n: int
    log_loss_empirical: float
    log_loss_normal: float
    predicted_win: float      # mean predicted P(win), empirical
    observed_win: float


def _point(market: str, line: float) -> float:
    return -line if market == "spreads" else line


def _outcome_logloss(pmf: dict[int, float], x: float, line: float) -> float:
    """-log P(observed outcome) for a ticket laying `line` (win above, push at, lose below)."""
    if abs(line - round(line)) < 1e-9:
        k = int(round(line))
        p = cover_from_pmf(pmf, line) if x > line else (pmf.get(k, 0.0) if x == k else
                                                        1 - cover_from_pmf(pmf, line - 0.5))
    else:
        p = cover_from_pmf(pmf, line) if x > line else 1 - cover_from_pmf(pmf, line)
    return -math.log(max(p, EPS))


def distribution_check(train: list[HistoryRow], holdout: list[HistoryRow], market: str, *,
                       bucket_width: float, bandwidth: float) -> dict:
    emp = EmpiricalFamily.fit(train, market, bucket_width=bucket_width, bandwidth=bandwidth)
    nor = NormalFamily.fit(train, market)
    rows = [r for r in holdout if (r.close_spread_home if market == "spreads" else r.close_total) is not None]
    results = []
    for offset in OFFSETS:
        ll_e = ll_n = pred = obs = 0.0
        for r in rows:
            line = r.close_spread_home if market == "spreads" else r.close_total
            x = r.margin if market == "spreads" else r.total
            level = _point(market, line) + offset
            pe, pn = emp.pmf(line), nor.pmf(line)
            ll_e += _outcome_logloss(pe, x, level)
            ll_n += _outcome_logloss(pn, x, level)
            pred += cover_from_pmf(pe, level)
            obs += x > level
        n = len(rows)
        results.append(OffsetResult(offset, n, ll_e / n, ll_n / n, pred / n, obs / n))
    residuals = [((r.margin if market == "spreads" else r.total) -
                  _point(market, r.close_spread_home if market == "spreads" else r.close_total))
                 for r in rows]
    sd = math.sqrt(sum(e * e for e in residuals) / max(len(residuals) - 1, 1)) if residuals else float("nan")
    winner = "empirical" if sum(o.log_loss_empirical for o in results) < sum(o.log_loss_normal for o in results) else "normal"
    return {"market": market, "n_train": len(train), "n_holdout": len(rows), "offsets": results,
            "residual_sd": sd, "normal_sigma": nor.sigma, "winner": winner}


def devig_check(rows: list[HistoryRow], methods: tuple[str, ...]) -> dict[str, dict[str, float]]:
    usable = [r for r in rows if r.close_ml_home is not None and r.close_ml_away is not None]
    out = {}
    for m in methods:
        probs, outcomes = [], []
        for r in usable:
            p = devig([american_to_decimal(r.close_ml_home), american_to_decimal(r.close_ml_away)], m)[0]
            probs.append(p)
            outcomes.append(1 if r.margin > 0 else 0)
        if usable:
            out[m] = {"n": len(usable), "log_loss": model.log_loss(probs, outcomes),
                      "brier": model.brier(probs, outcomes)}
    return out


BUBBLE_START = date(2020, 7, 30)


def excluded(row: HistoryRow) -> bool:
    """cfg:distribution.exclude: the 2019-20 bubble games and the 2020-21 season (RULES R-7.3)."""
    return row.season == "2020-21" or (row.season == "2019-20" and row.date >= BUBBLE_START)


def phase_of(games_played: int, total_games: int = 82) -> str:
    if games_played < 20:
        return "games 1-20"
    if games_played >= total_games - 20:
        return "last 20"
    return "middle"


def model_check(rows: list[HistoryRow], k: float, refit_every: int = 50,
                min_games: int = 30) -> dict[str, dict]:
    """Walk forward through one or more seasons; predictions use only earlier games
    of the same season, and start once `min_games` of them exist."""
    rows = sorted(rows, key=lambda r: r.date)
    by_phase: dict[str, dict[str, list]] = defaultdict(lambda: defaultdict(list))
    played: dict[tuple[str, str], int] = defaultdict(int)
    ratings = None
    history: list[model.GameResult] = []
    for i, r in enumerate(rows):
        if ratings is None or i % refit_every == 0:
            season_games = [g for g, row in zip(history, rows) if row.season == r.season]
            ratings = model.fit(season_games, k) if len(season_games) >= min_games else None
        if ratings is not None and r.close_spread_home is not None and r.close_total is not None:
            pred = ratings.predict(r.home, r.away)
            phase = phase_of(min(played[(r.season, r.home)], played[(r.season, r.away)]))
            bucket = by_phase[phase]
            bucket["spread_pred"].append(pred["home_margin"])
            bucket["spread_close"].append(-r.close_spread_home)
            bucket["total_pred"].append(pred["total"])
            bucket["total_close"].append(r.close_total)
            bucket["p"].append(ratings.p_home_win(r.home, r.away))
            bucket["won"].append(1 if r.margin > 0 else 0)
        history.append(model.GameResult(r.home, r.away, r.home_score, r.away_score))
        played[(r.season, r.home)] += 1
        played[(r.season, r.away)] += 1
    report = {}
    for phase, b in by_phase.items():
        report[phase] = {"n": len(b["p"]),
                         "mae_spread": model.mae(b["spread_pred"], b["spread_close"]),
                         "mae_total": model.mae(b["total_pred"], b["total_close"]),
                         "brier": model.brier(b["p"], b["won"]),
                         "log_loss": model.log_loss(b["p"], b["won"])}
    return report


def markdown(dist_results: list[dict], devig_results: dict, model_results: dict, source: str) -> str:
    lines = ["# Validation", "", f"History: {source}", ""]
    for d in dist_results:
        lines += [f"## Distribution: {d['market']}", "",
                  f"Train N = {d['n_train']}, holdout N = {d['n_holdout']}; holdout residual SD "
                  f"{d['residual_sd']:.2f}; normal sigma {d['normal_sigma']:.2f}; lower log loss: {d['winner']}.", "",
                  "| offset | N | log loss empirical | log loss normal | predicted win | observed win |",
                  "|---|---|---|---|---|---|"]
        for o in d["offsets"]:
            lines.append(f"| {o.offset:+.1f} | {o.n} | {o.log_loss_empirical:.4f} | {o.log_loss_normal:.4f} "
                         f"| {o.predicted_win:.4f} | {o.observed_win:.4f} |")
        lines.append("")
    if devig_results:
        lines += ["## De-vig methods (closing moneyline vs results)", "",
                  "| method | N | log loss | Brier |", "|---|---|---|---|"]
        for m, r in devig_results.items():
            lines.append(f"| {m} | {r['n']} | {r['log_loss']:.5f} | {r['brier']:.5f} |")
        lines.append("")
    if model_results:
        lines += ["## Model (walk-forward)", "", "| phase | N | MAE spread | MAE total | Brier | log loss |",
                  "|---|---|---|---|---|---|"]
        for phase, r in model_results.items():
            lines.append(f"| {phase} | {r['n']} | {r['mae_spread']:.2f} | {r['mae_total']:.2f} "
                         f"| {r['brier']:.4f} | {r['log_loss']:.4f} |")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    cli.setup_output()
    parser = argparse.ArgumentParser(prog="python -m bethero_nba.validate", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    cli.add_root(parser)
    parser.add_argument("--history", type=Path, required=True)
    parser.add_argument("--holdout", required=True, help="comma-separated seasons, e.g. 2024-25,2025-26")
    parser.add_argument("--bandwidth", type=float, default=1.0)
    parser.add_argument("--k", type=float, default=10.0, help="model shrinkage, games per team")
    parser.add_argument("--out", type=Path)
    args = parser.parse_args(argv)
    cfg = cli.load_config(cli.resolve_root(args.root))
    rows = [r for r in load_history(args.history) if not excluded(r)]
    holdout_seasons = set(args.holdout.split(","))
    train = [r for r in rows if r.season not in holdout_seasons]
    holdout = [r for r in rows if r.season in holdout_seasons]
    dists = [distribution_check(train, holdout, m, bucket_width=cfg.get("distribution.bucket_width"),
                                bandwidth=args.bandwidth) for m in ("spreads", "totals")]
    text = markdown(dists, devig_check(holdout, tuple(cfg.get("anchor.devig_methods"))),
                    model_check(holdout, args.k), str(args.history))
    if args.out:
        args.out.write_text(text, encoding="utf-8", newline="\n")
        print(f"wrote {args.out}")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
