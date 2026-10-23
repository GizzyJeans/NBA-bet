"""Settle a slate's shadow (or live) bets and measure CLV.

    python -m bethero_nba.settle --slate 2026-11-02 --scores <scores.json.gz> \
        [--close-odds <odds.json.gz>] [--close-board <board.json>]

Bets are the decision rows of the latest pass for each market that passed
every gate. Each gets its realised return from the final score (overtime
included), CLV_US from the US close when the needed lines are quoted there
(Tier A at the close), and CLV_line when Eric's last pre-tip screenshot is
given. Anything missing stays None (RULES R-14.3). Results are appended to the
ledger and the pause rule is re-checked (R-14.7).
"""

from __future__ import annotations

import argparse
import subprocess
from datetime import date, datetime
from pathlib import Path

from . import cli, clv, consensus, ledger, net, oddsapi
from .odds import Leg, expected_value, needed_points, ticket_outcomes
from .platform import load_board
from .teams import team

US_MARKET = {"handicap": "spreads", "total": "totals", "moneyline": "h2h"}


def first_commit_time(root: Path, path: str) -> datetime | None:
    """When the board file was first committed: the evidence of pricing time (RULES R-14.2)."""
    try:
        out = subprocess.run(["git", "-C", str(root), "log", "--diff-filter=A", "--format=%cI", "--", path],
                             capture_output=True, text=True, timeout=10).stdout.split()
    except (OSError, subprocess.SubprocessError):
        return None
    return datetime.fromisoformat(out[-1]) if out else None


def latest_bets(records: list[dict], slate: date) -> list[dict]:
    """Bets of the latest pass per market, each with the pass record it came from."""
    latest: dict[tuple, dict] = {}
    current_pass = None
    for r in records:
        if r.get("record_type") == "pass":
            current_pass = r
            continue
        if r.get("record_type") != "decision":
            continue
        r = {**r, "pass": current_pass}
        if oddsapi.eastern_date(datetime.fromisoformat(r["game"]["tip"])) != slate:
            continue
        key = (r["game"]["home"], r["game"]["away"], r["market"], r["side"])
        latest[key] = r
    settled = {r["decision_sequence"] for r in records if r.get("record_type") == "settlement"}
    return [r for r in latest.values() if not r["codes"] and r.get("stake") and r["sequence"] not in settled]


def _legs(record: dict) -> tuple[Leg, ...]:
    legs = record["platform"]["legs"]
    return tuple(Leg(line, weight) for line, weight in legs) if legs else (Leg(0.5, 1.0),)


def _giver(record: dict) -> str:
    if record["market"] == "total":
        return "over"
    if record["market"] == "moneyline":
        return "home"
    return record["side"] if record["laying"] else ("away" if record["side"] == "home" else "home")


def realised(record: dict, home_score: int, away_score: int) -> float:
    """Profit per unit staked, from the final score."""
    giver = _giver(record)
    if record["market"] == "total":
        x = home_score + away_score
    else:
        x = home_score - away_score if giver == "home" else away_score - home_score
    outcome = ticket_outcomes(_legs(record), record["platform"]["price"], lambda p: 1.0 if x > p else 0.0,
                              record["laying"])
    return expected_value(outcome)


def close_cover(gc: consensus.GameConsensus, record: dict, legs, cfg):
    """US close cover function if every needed point is quoted at the close, else None."""
    market, giver = US_MARKET[record["market"]], _giver(record)
    method = record["worst_method"]
    cover = gc.cover(market, giver, method, cfg.get("tiers.tier_a_min_books"))
    return cover if all(cover(x) is not None for x in needed_points(legs)) else None


def main(argv: list[str] | None = None) -> int:
    cli.setup_output()
    parser = argparse.ArgumentParser(prog="python -m bethero_nba.settle", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    cli.add_root(parser)
    parser.add_argument("--slate", required=True, type=date.fromisoformat)
    parser.add_argument("--scores", type=Path, required=True, help="stored Odds API scores (.json.gz)")
    parser.add_argument("--close-odds", type=Path)
    parser.add_argument("--close-board", type=Path)
    parser.add_argument("--no-ledger", action="store_true")
    args = parser.parse_args(argv)

    root = cli.resolve_root(args.root)
    cfg = cli.load_config(root)
    ledger_path = root / "logs" / "ledger.jsonl"
    records = ledger.verify(ledger_path)
    bets = latest_bets(records, args.slate)
    scores = oddsapi.completed_scores(net.load_cached(args.scores).json())
    close_games, close_ts = [], None
    if args.close_odds:
        fetched = net.load_cached(args.close_odds)
        close_games, close_ts = oddsapi.normalise(fetched.json()), fetched.retrieved_at
    close_board = load_board(args.close_board) if args.close_board else None

    rows, clv_values = [], []
    for bet in bets:
        home, away = bet["game"]["home"], bet["game"]["away"]
        score = next((s for s in scores if team(s.home_team).tricode == home
                      and team(s.away_team).tricode == away
                      and oddsapi.eastern_date(s.commence_time) == args.slate), None)
        if score is None:
            print(f"{away}@{home}: no final score yet")
            continue
        legs = _legs(bet)
        ret = realised(bet, score.home_score, score.away_score)
        clv_us = clv_line = None
        game = next((g for g in close_games if team(g.home_team).tricode == home
                     and team(g.away_team).tricode == away), None)
        if game is not None:
            gc = consensus.build(game, close_ts, methods=tuple(cfg.get("anchor.devig_methods")),
                                 max_age_min=cfg.get("anchor.us_quote_max_age_min"))
            cover = close_cover(gc, bet, legs, cfg)
            if cover is not None:
                clv_us, _ = clv.clv_us(legs, bet["platform"]["price"], bet["laying"], cover,
                                       bet["ev"].get(bet["worst_method"]))
                if close_board is not None:
                    match = next((g for g in close_board.games
                                  if (g.home.tricode, g.away.tricode) == (home, away)), None)
                    market = getattr(match, bet["market"], None) if match else None
                    if market is not None and market.line is not None and market.line.legs:
                        close_legs = market.line.legs
                        cover_both = close_cover(gc, {**bet, "platform": {**bet["platform"], "legs":
                                                      [[l.line, l.weight] for l in close_legs]}}, close_legs, cfg)
                        if cover_both is not None:
                            clv_line = clv.clv_line(legs, close_legs, bet["platform"]["price"], bet["laying"], cover)
        board_path = (bet.get("pass") or {}).get("board", {}).get("path")
        committed = first_commit_time(root, board_path) if board_path else None
        tip = datetime.fromisoformat(bet["game"]["tip"])
        rows.append({"record_type": "settlement", "schema": "bethero-nba-settlement/1",
                     "decision_sequence": bet["sequence"], "slate_et": args.slate.isoformat(),
                     "board_committed_at": committed.isoformat() if committed else None,
                     "prospective": committed is not None and committed < tip,
                     "home_score": score.home_score, "away_score": score.away_score,
                     "return_per_unit": ret, "stake": bet["stake"], "mode": bet["mode"],
                     "pnl": ret * bet["stake"], "clv_us": clv_us, "clv_line": clv_line})
        if clv_us is not None:
            clv_values.append((args.slate, clv_us))
        print(f"{away}@{home} {bet['market']} {bet['side']}: return {ret:+.3f}/unit, "
              f"P&L {ret * bet['stake']:+,.0f} ({bet['mode']}), CLV_US {clv_us}, CLV_line {clv_line}")
    if rows and not args.no_ledger:
        ledger.append(ledger_path, rows)
    history = [(date.fromisoformat(r["slate_et"]), r["clv_us"]) for r in records
               if r.get("record_type") == "settlement" and r.get("clv_us") is not None] + clv_values
    check = clv.pause_check(history, cfg)
    print(f"settled {len(rows)} bet(s); CLV_US sample {check.n}; pause: {'YES' if check.paused else 'no'}")
    counted = [(date.fromisoformat(r["slate_et"]), r["clv_us"]) for r in records + rows
               if r.get("record_type") == "settlement" and r.get("clv_us") is not None
               and r.get("mode") == "shadow" and (r.get("prospective") or not cfg.get("golive.require_prospective"))]
    ready = clv.golive_check(counted, cfg)
    interval = (f"mean {ready.mean:+.4f}, CI [{ready.low:+.4f}, {ready.high:+.4f}]" if ready.mean is not None
                else f"needs {cfg.get('golive.min_bets')} bets over {cfg.get('golive.min_slate_days')} slate days")
    print(f"go-live readiness (strict): {ready.n} prospective shadow bets over {ready.days} days; {interval}; "
          f"{'conditions met; going live still needs Eric' if ready.ready else 'not yet'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
