"""One analysis pass: a transcribed board + a US snapshot -> decisions, ledger rows, report.

    python -m bethero_nba.analyze --board data/boards/2026-11-02/20261103T071000+0800.json --live
    python -m bethero_nba.analyze --board <board.json> --odds data/raw/api.the-odds-api.com/<file>.json.gz

`--live` pulls a fresh US snapshot (RULES R-4.7, budget R-5.8); `--odds` re-uses
a stored one. `--injury-pdf` takes the official injury report as Eric saved it,
and referee assignments count as posted from 10:00 ET on game day (R-4.5;
`--referees-posted-at` from a screenshot can show an earlier time);
`--injuries` takes a JSON transcription instead (format in README). Without
either, every game stops at NB-STATUS, which is the rule (R-9.2), not a bug.
With an injury source, listed players' minutes come from the ESPN box scores
that sportsdataverse publishes, downloaded by `--live` or re-used with
`--box-scores`; `--minutes` adds minutes transcribed from Eric's game-log
screenshots. Minutes clear bench players (R-9.3).
Every evaluated market goes to logs/ledger.jsonl and the Traditional Chinese
report to reports/<slate>/.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from . import boxscores, cli, consensus, context, dist, edge, injuries, ledger, net, oddsapi, report
from .platform import load_board


def code_commit(root: Path) -> str | None:
    try:
        out = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"], capture_output=True,
                             text=True, timeout=10)
        return out.stdout.strip() or None
    except (OSError, subprocess.SubprocessError):
        return None


@dataclass
class InjuryGates:
    """What G7 needs, by game label (RULES R-4.5, R-9.3, R-9.4), and where the minutes came from."""
    eligible: dict[str, bool]
    blocking: dict[str, list[str]]
    cleared: dict[str, list[str]]
    unsupplied: dict[str, list[str]]   # listed key players whose minutes were not supplied
    unmatched: list[str]               # transcribed minutes for a player the report does not list on that team
    not_supplied: dict[str, str]       # why the box scores could not supply a player's minutes
    box_scores: dict | None            # the files used, or why none were; None if no listed player needed them
    referees: dict | None = None       # when referee assignments counted as posted, and on what evidence


def referees_posted(seen: datetime | None, board, cfg) -> tuple[datetime, dict]:
    """R-4.5(b): assignments count as posted from the time rule (Eric 2026-10-27), or earlier when a
    screenshot of official.nba.com shows them."""
    rule = injuries.referees_posted_by_rule(board.slate_et, cfg)
    posted = min(seen, rule) if seen else rule
    return posted, {"referees_posted_at": posted.isoformat(),
                    "referees_evidence": "screenshot" if seen and seen < rule else "time_rule"}


def _by_game(timeline: injuries.Timeline, board, cfg, at: datetime, minutes: dict | None,
             box_scores: Callable[[], boxscores.BoxScores] | None) -> dict:
    """R-9.3 minutes for the listed players: from the box scores when a listed player still needs
    them, then from Eric's transcription, which wins for the players it names."""
    pairs = {game.label: (game.home.tricode, game.away.tricode) for game in board.games}
    need: dict[str, set[str]] = {}
    for pair in pairs.values():
        for tricode, players in injuries.listed(timeline, pair, cfg, at).items():
            need.setdefault(tricode, set()).update(players - set((minutes or {}).get(tricode, {})))
    supplied, not_supplied, record = {}, {}, None
    if box_scores is not None and any(need.values()):
        try:
            scores = box_scores()
        except (OSError, net.FetchError, boxscores.BoxScoreError) as exc:
            print(f"box scores not used: {exc}")
            record = {"error": str(exc)}
        else:
            supplied, not_supplied = scores.supply(need, board.slate_et, cfg.get("injuries.key_player_window_games"))
            record = {"season": scores.season, "files": scores.sources}
    combined = {tricode: dict(names) for tricode, names in supplied.items()}
    for tricode, names in (minutes or {}).items():
        combined.setdefault(tricode, {}).update(names)
    blocking, cleared, unsupplied = {}, {}, {}
    for label, pair in pairs.items():
        blocking[label], cleared[label], unsupplied[label] = injuries.listed_players(timeline, pair, combined,
                                                                                   cfg, at)
    unmatched = sorted(f"{t} {name}" for t, names in (minutes or {}).items() for name in names
                       if name not in timeline.players(t))
    return {"blocking": blocking, "cleared": cleared, "unsupplied": unsupplied, "unmatched": unmatched,
            "not_supplied": not_supplied, "box_scores": record}


def load_injuries(path: Path, board, cfg, at: datetime, minutes: dict | None = None,
                  box_scores: Callable[[], boxscores.BoxScores] | None = None) -> tuple[InjuryGates, datetime]:
    """G7 inputs and the report time from a transcription; `minutes` adds to the transcription's own."""
    data = json.loads(path.read_text(encoding="utf-8"))
    report_time = datetime.fromisoformat(data["report_time"])
    refs, referees = referees_posted(datetime.fromisoformat(data["referees_posted_at"])
                                     if data.get("referees_posted_at") else None, board, cfg)
    submissions = {t: datetime.fromisoformat(v) for t, v in data.get("submissions", {}).items()}
    records = [injuries.StatusRecord(report_time, s["team"], s["player"], s["status"], s.get("reason", ""))
               for s in data.get("statuses", [])]
    timeline = injuries.Timeline(records)
    combined: dict[str, dict[str, list[float]]] = {}
    for given in (data.get("minutes") or {}, minutes or {}):
        for tricode, names in given.items():
            combined.setdefault(tricode, {}).update(names)
    b2b = set(data.get("back_to_back_second", []))
    eligible = {game.label: injuries.final_eligible(game.tip, (game.home.tricode, game.away.tricode),
                                                    submissions, refs, at, b2b) for game in board.games}
    return (InjuryGates(eligible, **_by_game(timeline, board, cfg, at, combined, box_scores), referees=referees),
            report_time)


def injury_gates(report_: injuries.Report, referees_posted_at: datetime | None, board, cfg,
                 at: datetime, minutes: dict | None = None,
                 box_scores: Callable[[], boxscores.BoxScores] | None = None) -> InjuryGates:
    """G7 inputs from the official report, with minutes from the box scores and Eric's screenshots."""
    games = {game.label: (injuries.report_date_et(game.tip), game.away.tricode, game.home.tricode)
             for game in board.games}
    submissions = injuries.gameday_submissions(report_, list(games.values()))
    timeline = injuries.Timeline(report_.records({day for day, _, _ in games.values()}))
    eligible = {game.label: injuries.final_eligible(game.tip, (game.home.tricode, game.away.tricode),
                                                    submissions, referees_posted_at, at) for game in board.games}
    return InjuryGates(eligible, **_by_game(timeline, board, cfg, at, minutes, box_scores))


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
                        help="when a screenshot showed the day's referee assignments posted (ISO-8601), "
                             "if before the 10:00 ET time rule")
    parser.add_argument("--minutes", type=Path,
                        help="listed players' minutes from Eric's game-log screenshots (JSON, format in README)")
    parser.add_argument("--box-scores", nargs=2, type=Path, metavar=("BOX", "SCHEDULE"),
                        help="stored box-score and schedule files (.csv.gz) to re-use; --live downloads them")
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

    box_scores = None
    if args.box_scores:
        box_scores = lambda: boxscores.load(*args.box_scores, cfg)        # noqa: E731
    elif args.live:
        box_scores = lambda: boxscores.fetch(client, cfg)                 # noqa: E731

    minutes = transcription = None
    if args.minutes:
        if not (args.injuries or args.injury_pdf):
            parser.error("--minutes needs --injury-pdf or --injuries")
        try:
            given = injuries.load_minutes(args.minutes)
        except (OSError, injuries.MinutesError) as exc:
            print(f"minutes: {exc}")
            return 2
        fresh = given.fresh_for(board.slate_et, now, cfg)
        minutes = given.players if fresh else None
        transcription = {"file": args.minutes.as_posix(), "sha256": given.sha256,
                         "seen_at": given.seen_at.isoformat(), "source": given.source, "used": fresh}
        if not fresh:
            print(f"minutes not used: {args.minutes} must be for the {board.slate_et} ET slate, taken that day "
                  f"at or after {cfg.get('injuries.minutes_screenshot_from_et')} ET and before this pass")

    gates = report_ts = injury_source = None
    if args.injuries:
        gates, report_ts = load_injuries(args.injuries, board, cfg, now, minutes, box_scores)
        injury_source = {"kind": "transcription", "file": args.injuries.as_posix(),
                         "sha256": hashlib.sha256(args.injuries.read_bytes()).hexdigest(), **gates.referees}
    elif args.injury_pdf:
        official = injuries.read_pdf(args.injury_pdf)
        refs, referees = referees_posted(datetime.fromisoformat(args.referees_posted_at)
                                         if args.referees_posted_at else None, board, cfg)
        gates = injury_gates(official, refs, board, cfg, now, minutes, box_scores)
        gates.referees = referees
        report_ts = official.report_time
        injury_source = {"kind": "official_pdf", "file": args.injury_pdf.name, "sha256": official.sha256,
                         **referees}
    if transcription is not None:
        transcription["unmatched"] = gates.unmatched if minutes else []
        if transcription["unmatched"]:
            print("minutes given for players the report does not list on that team: "
                  + ", ".join(transcription["unmatched"]))
    for player, reason in (gates.not_supplied if gates else {}).items():
        print(f"no box-score minutes for {player}: {reason}")

    tier_b = None
    if cfg.get("distribution.status") == "VALIDATED":
        try:
            tier_b = dist.load_tier_b(root / "data" / "dist", cfg.get("distribution.validated_markets"),
                                      cfg.get("distribution.selected_method"),
                                      cfg.get("distribution.smoothing_bandwidth"),
                                      cfg.get("distribution.comparison_fallback"))
        except (OSError, ValueError) as exc:          # fail closed: no Tier B, every gap is NB-TIER-C
            print(f"Tier B off: {exc}")
    ctx = edge.PassContext(cfg=cfg, analysis_ts=now, platform_ts=board.platform_ts,
                           ts_source=board.ts_source, us_ts=us_ts,
                           final_eligible=gates.eligible if gates else None, injury_report_ts=report_ts,
                           blocking=gates.blocking if gates else None,
                           cleared=gates.cleared if gates else None,
                           unsupplied=gates.unsupplied if gates else None, tier_b=tier_b, model=None)
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
            "minutes_source": {"box_scores": gates.box_scores, "not_supplied": gates.not_supplied,
                               "transcription": transcription} if gates else None,
            "decisions": len(decisions), "bets": sum(d.is_bet for d in decisions),
        }
        ledger.append(root / "logs" / "ledger.jsonl", [pass_record] + [d.to_record(ctx) for d in decisions])

    text = report.render(decisions, report.ReportMeta(
        board, now, us_ts, report_ts, cfg.get("mode"), cfg.get("risk.bankroll"),
        cfg.get("risk.daily_cap_pct") * cfg.get("risk.bankroll"), args.exposure_used,
        (cfg.get("injuries.key_player_window_games"), cfg.get("injuries.key_player_min_minutes")),
        "；".join(credit for used, credit in (
            (gates is not None and bool((gates.box_scores or {}).get("files")), boxscores.CREDIT),
            (bool(transcription and transcription["used"]), "Eric 的出賽紀錄截圖")) if used) or None))
    out_dir = root / "reports" / board.slate_et.isoformat()
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"{now.astimezone(timezone.utc):%Y%m%dT%H%M%SZ}.md"
    out.write_text(text, encoding="utf-8", newline="\n")
    print(text)
    print(f"report: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
