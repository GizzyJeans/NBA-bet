"""One analysis pass: a transcribed board + a US snapshot -> decisions, ledger rows, report.

    python -m bethero_nba.analyze --board data/boards/2026-11-02/20261103T071000+0800.json --live
    python -m bethero_nba.analyze --board <board.json> --odds data/raw/api.the-odds-api.com/<file>.json.gz

`--live` pulls a fresh US snapshot (RULES R-4.7, budget R-5.8); `--odds` re-uses
a stored one. `--injury-pdf` takes the official injury report as Eric saved it,
with `--referees-posted-at` from his referee-assignments screenshot;
`--injuries` takes a JSON transcription instead (format in README). Without
either, every game stops at NB-STATUS, which is the rule (R-9.2), not a bug.
Every evaluated market goes to logs/ledger.jsonl and the Traditional Chinese
report to reports/<slate>/.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from . import cli, consensus, context, dist, edge, injuries, ledger, net, oddsapi, report
from .platform import load_board


def code_commit(root: Path) -> str | None:
    try:
        out = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"], capture_output=True,
                             text=True, timeout=10)
        return out.stdout.strip() or None
    except (OSError, subprocess.SubprocessError):
        return None


def load_injuries(path: Path, board, cfg, at: datetime) -> tuple[dict, dict, datetime | None]:
    """(final_eligible by game, blocking players by game, report time) from a transcription."""
    data = json.loads(path.read_text(encoding="utf-8"))
    report_time = datetime.fromisoformat(data["report_time"])
    refs = datetime.fromisoformat(data["referees_posted_at"]) if data.get("referees_posted_at") else None
    submissions = {t: datetime.fromisoformat(v) for t, v in data.get("submissions", {}).items()}
    records = [injuries.StatusRecord(report_time, s["team"], s["player"], s["status"], s.get("reason", ""))
               for s in data.get("statuses", [])]
    timeline = injuries.Timeline(records)
    minutes = data.get("minutes")
    b2b = set(data.get("back_to_back_second", []))
    eligible, blocking = {}, {}
    for game in board.games:
        teams = (game.home.tricode, game.away.tricode)
        eligible[game.label] = injuries.final_eligible(game.tip, teams, submissions, refs, at, b2b)
        blocking[game.label] = injuries.blocking_players(timeline, teams, minutes, cfg, at)
    return eligible, blocking, report_time


def injury_gates(report_: injuries.Report, referees_posted_at: datetime | None, board, cfg,
                 at: datetime) -> tuple[dict, dict]:
    """(final_eligible by game, blocking players by game) from the official report."""
    games = {game.label: (injuries.report_date_et(game.tip), game.away.tricode, game.home.tricode)
             for game in board.games}
    submissions = injuries.gameday_submissions(report_, list(games.values()))
    timeline = injuries.Timeline(report_.records({day for day, _, _ in games.values()}))
    eligible, blocking = {}, {}
    for game in board.games:
        teams = (game.home.tricode, game.away.tricode)
        eligible[game.label] = injuries.final_eligible(game.tip, teams, submissions, referees_posted_at, at)
        blocking[game.label] = injuries.blocking_players(timeline, teams, None, cfg, at)
    return eligible, blocking


def main(argv: list[str] | None = None) -> int:
    cli.setup_output()
    parser = argparse.ArgumentParser(prog="python -m bethero_nba.analyze", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    cli.add_root(parser)
    parser.add_argument("--board", type=Path, required=True)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--odds", type=Path, help="stored US snapshot (.json.gz)")
    source.add_argument("--live", action="store_true", help="pull a fresh US snapshot")
    injury = parser.add_mutually_exclusive_group()
    injury.add_argument("--injury-pdf", type=Path, help="official injury report PDF, as saved from official.nba.com")
    injury.add_argument("--injuries", type=Path, help="injury-report transcription (JSON)")
    parser.add_argument("--referees-posted-at",
                        help="when the day's referee assignments were seen posted (ISO-8601), with --injury-pdf")
    parser.add_argument("--exposure-used", type=float, default=0.0,
                        help="stakes already placed on this slate")
    parser.add_argument("--now", help="analysis time (ISO-8601), for re-running a past pass")
    parser.add_argument("--no-ledger", action="store_true")
    args = parser.parse_args(argv)

    root = cli.resolve_root(args.root)
    cfg = cli.load_config(root)
    board = load_board(args.board)
    now = datetime.fromisoformat(args.now) if args.now else datetime.now(timezone.utc)

    if args.live:
        client = net.HttpClient.from_config(cfg, root / "data" / "raw", live=True)
        budget = oddsapi.Budget.from_config(cfg, root / "logs" / "odds_api_usage.jsonl")
        regions, markets = cfg.get("anchor.regions"), cfg.get("anchor.markets")
        try:
            budget.check(now, oddsapi.odds_cost(regions, markets))
            fetched = oddsapi.fetch_odds(client, cli.api_key(), cfg.get("anchor.sport_key"), regions, markets)
        except (oddsapi.BudgetRefused, net.FetchError) as exc:
            print(f"no US snapshot: {exc}")
            return 2
        budget.record(fetched, "odds")
    else:
        fetched = net.load_cached(args.odds)
    us_ts = fetched.retrieved_at
    us_games = oddsapi.normalise(fetched.json())

    eligible = blocking = report_ts = injury_source = None
    if args.injuries:
        eligible, blocking, report_ts = load_injuries(args.injuries, board, cfg, now)
        injury_source = {"kind": "transcription", "file": args.injuries.as_posix(),
                         "sha256": hashlib.sha256(args.injuries.read_bytes()).hexdigest()}
    elif args.injury_pdf:
        official = injuries.read_pdf(args.injury_pdf)
        refs = datetime.fromisoformat(args.referees_posted_at) if args.referees_posted_at else None
        eligible, blocking = injury_gates(official, refs, board, cfg, now)
        report_ts = official.report_time
        injury_source = {"kind": "official_pdf", "file": args.injury_pdf.name, "sha256": official.sha256,
                         "referees_posted_at": refs.isoformat() if refs else None}

    tier_b = None
    if cfg.get("distribution.status") == "VALIDATED":
        try:
            tier_b = dist.load_tier_b(root / "data" / "dist", cfg.get("distribution.validated_markets"),
                                      cfg.get("distribution.selected_method"),
                                      cfg.get("distribution.smoothing_bandwidth"))
        except (OSError, ValueError) as exc:          # fail closed: no Tier B, every gap is NB-TIER-C
            print(f"Tier B off: {exc}")
    ctx = edge.PassContext(cfg=cfg, analysis_ts=now, platform_ts=board.platform_ts,
                           ts_source=board.ts_source, us_ts=us_ts, final_eligible=eligible,
                           injury_report_ts=report_ts, blocking=blocking, tier_b=tier_b, model=None)
    methods = tuple(cfg.get("anchor.devig_methods"))
    decisions, consensuses = [], {}
    for game in board.games:
        ctx.flags[game.label] = context.flags_for(game.home.tricode, game.away.tricode, game.tip, [], cfg)
        us_game, note = edge.match_us_game(game, us_games)
        gc = (consensus.build(us_game, us_ts, methods=methods,
                              max_age_min=cfg.get("anchor.us_quote_max_age_min")) if us_game else None)
        consensuses[game.label] = gc
        decisions += edge.evaluate_game(game, gc, ctx, note)
    edge.allocate(decisions, cfg, args.exposure_used)
    for d in decisions:
        if d.is_bet:
            d.worst_line = edge.worst_acceptable(d, consensuses[d.game.label], ctx)

    board_sha = hashlib.sha256(args.board.read_bytes()).hexdigest()
    if not args.no_ledger:
        pass_record = {
            "record_type": "pass", "schema": "bethero-nba-pass/1", "slate_et": board.slate_et.isoformat(),
            "analysis_ts": now.isoformat(), "config_version": cfg.version, "code_commit": code_commit(root),
            "board": {"path": args.board.as_posix(), "sha256": board_sha, "platform_ts":
                      board.platform_ts.isoformat() if board.platform_ts else None, "ts_source": board.ts_source},
            "us_snapshot": {"url": fetched.url, "retrieved_at": us_ts.isoformat(), "sha256": fetched.sha256},
            "injury_report_ts": report_ts.isoformat() if report_ts else None,
            "injury_source": injury_source,
            "decisions": len(decisions), "bets": sum(d.is_bet for d in decisions),
        }
        ledger.append(root / "logs" / "ledger.jsonl", [pass_record] + [d.to_record(ctx) for d in decisions])

    text = report.render(decisions, report.ReportMeta(
        board, now, us_ts, report_ts, cfg.get("mode"), cfg.get("risk.bankroll"),
        cfg.get("risk.daily_cap_pct") * cfg.get("risk.bankroll"), args.exposure_used))
    out_dir = root / "reports" / board.slate_et.isoformat()
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"{now.astimezone(timezone.utc):%Y%m%dT%H%M%SZ}.md"
    out.write_text(text, encoding="utf-8", newline="\n")
    print(text)
    print(f"report: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
