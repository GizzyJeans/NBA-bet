"""Pull US odds, scores or the team list from The Odds API.

    python -m bethero_nba.fetch odds --live
    python -m bethero_nba.fetch scores --days-from 3 --live
    python -m bethero_nba.fetch participants --live
    python -m bethero_nba.fetch show data/raw/api.the-odds-api.com/<file>.json.gz

Nothing reaches the network without `--live` (RULES R-4.7). Every response is
stored under data/raw/ with its hash; the API key never leaves the
environment variable. `show` reads a stored snapshot offline.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from . import cli, consensus, net, oddsapi

TAIPEI = ZoneInfo("Asia/Taipei")


def summarise_odds(fetched: net.Fetched, cfg) -> str:
    games = oddsapi.normalise(fetched.json())
    methods = tuple(cfg.get("anchor.devig_methods"))
    lines = [f"US snapshot {fetched.retrieved_at.astimezone(TAIPEI):%Y-%m-%d %H:%M} (Taipei), "
             f"{len(games)} games, file {fetched.path}"]
    for game in sorted(games, key=lambda g: g.commence_time):
        gc = consensus.build(game, fetched.retrieved_at, methods=methods,
                             max_age_min=cfg.get("anchor.us_quote_max_age_min"))
        parts = []
        for market in ("spreads", "totals", "h2h"):
            key = gc.l_ref(market) if market != "h2h" else None
            lc = gc.line(market, key)
            if lc is None:
                parts.append(f"{market} -")
            else:
                label = f"{key:+g}" if market == "spreads" else (f"{key:g}" if key is not None else "")
                parts.append(f"{market} {label} {lc.n_books} books "
                             f"p={lc.probs[cfg.get('anchor.devig_display_method')]:.3f}")
        books = len({q.book for q in game.quotes})
        lines.append(f"  {game.commence_time.astimezone(TAIPEI):%m-%d %H:%M} "
                     f"{game.away_team} @ {game.home_team}: {books} books | " + " | ".join(parts)
                     + (f" | {gc.dropped_stale} stale quotes dropped" if gc.dropped_stale else ""))
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    cli.setup_output()
    parser = argparse.ArgumentParser(prog="python -m bethero_nba.fetch", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    cli.add_root(parser)
    sub = parser.add_subparsers(dest="what", required=True)
    for name in ("odds", "scores", "participants"):
        p = sub.add_parser(name)
        p.add_argument("--live", action="store_true", help="allow the network request")
        if name == "scores":
            p.add_argument("--days-from", type=int, default=3, choices=(1, 2, 3))
    show = sub.add_parser("show")
    show.add_argument("path")
    args = parser.parse_args(argv)

    root = cli.resolve_root(args.root)
    cfg = cli.load_config(root)
    if args.what == "show":
        fetched = net.load_cached(args.path)
        print(summarise_odds(fetched, cfg))
        return 0

    sport = cfg.get("anchor.sport_key")
    client = net.HttpClient.from_config(cfg, root / "data" / "raw", live=args.live)
    budget = oddsapi.Budget.from_config(cfg, root / "logs" / "odds_api_usage.jsonl")
    regions, markets = cfg.get("anchor.regions"), cfg.get("anchor.markets")
    cost = {"odds": oddsapi.odds_cost(regions, markets), "scores": 2, "participants": 1}[args.what]
    try:
        budget.check(datetime.now(timezone.utc), cost, kind=args.what)
        if args.what == "odds":
            fetched = oddsapi.fetch_odds(client, cli.api_key(), sport, regions, markets)
        elif args.what == "scores":
            fetched = oddsapi.fetch_scores(client, cli.api_key(), sport, args.days_from)
        else:
            fetched = oddsapi.fetch_participants(client, cli.api_key(), sport)
    except (net.LiveRequestsDisabled, oddsapi.BudgetRefused, net.FetchError) as exc:
        print(f"not fetched: {exc}")
        return 2
    usage = budget.record(fetched, args.what)
    print(f"saved {fetched.path} (sha256 {fetched.sha256[:12]}); credits remaining {usage.remaining}, "
          f"this call {usage.last}")
    if args.what == "odds":
        print(summarise_odds(fetched, cfg))
    elif args.what == "participants":
        names = sorted(p.get("full_name", "?") for p in fetched.json())
        print(f"{len(names)} participants: " + ", ".join(names))
    else:
        done = oddsapi.completed_scores(fetched.json())
        print(f"{len(done)} completed games")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
