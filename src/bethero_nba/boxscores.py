"""Listed players' minutes from ESPN box scores, as sportsdataverse publishes them (RULES R-9.3).

    python -m bethero_nba.boxscores --live --slate 2026-11-02 --team NYK --player "Brunson, Jalen"
    python -m bethero_nba.boxscores --box <player_box .csv.gz> --schedule <schedule .csv.gz> --slate 2026-11-02

The sportsdataverse project (hoopR-nba-data) republishes ESPN's NBA player box
scores and schedule as one file per season on GitHub, refreshed daily in
season, under CC BY 4.0. Checked on 2026-10-27 (RULES Appendix B): all 52 games
final by then were present, and in all 104 team box scores the players' points
equalled the team's score and their minutes filled the game.

Nothing is taken on trust. A player's minutes are supplied only when every game
his team played before the slate date is final in the schedule and both of its
box-score checks pass; otherwise they are not supplied, and a listed player
whose minutes are not supplied stays key (R-9.3). The raw files stay in
data/raw/ like every response (R-4.7), and the pass records their SHA-256.
"""

from __future__ import annotations

import argparse
import csv
import io
import re
import unicodedata
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from .net import Fetched, HttpClient, load_cached
from .teams import UnknownTeam, team

BASE = "https://github.com/sportsdataverse/sportsdataverse-data/releases/download"
PLAYER_BOX = BASE + "/espn_nba_player_boxscores/player_box_{season}.csv"
SCHEDULE = BASE + "/espn_nba_schedules/nba_schedule_{season}.csv"
BOX_COLUMNS = ("game_id", "athlete_id", "athlete_display_name", "team_abbreviation", "minutes", "points",
               "did_not_play")
SCHEDULE_COLUMNS = ("game_id", "game_date", "status_type_name", "status_period", "format_regulation_periods",
                    "home_abbreviation", "away_abbreviation", "home_score", "away_score")
FINAL = "STATUS_FINAL"
SUFFIXES = frozenset({"jr", "sr", "ii", "iii", "iv"})
CREDIT = ("ESPN 逐場數據，經 sportsdataverse 整理"
          "（[CC BY 4.0](https://creativecommons.org/licenses/by/4.0/)）；平均由本程式計算")


class BoxScoreError(ValueError):
    """The files are not shaped as checked on 2026-10-27; refuse rather than guess."""


def season_key(cfg) -> int:
    """sportsdataverse names a season by the year it ends (2027 = 2026-27)."""
    return cfg.get("season.regular_season")[1].year


def normalise(name: str) -> str:
    """Case, accents, punctuation and generational suffixes removed: 'Dereck Lively II' -> 'dereck lively'."""
    plain = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii")
    words = re.sub(r"[.,'’\-]", " ", plain.casefold()).split()
    return " ".join(w for w in words if w not in SUFFIXES)


def report_name(player: str) -> str:
    """The injury report's 'Last, First' ('Lively II, Dereck', 'Udeh, Jr., Ernest'), normalised first-last."""
    last, _, first = player.partition(",")
    return normalise(f"{first} {last}")


@dataclass(frozen=True)
class TeamGame:
    game_id: str
    day: date                     # US Eastern date, as ESPN dates the game
    status: str
    checked: bool                 # final, and its box score passes both checks
    minutes: dict[str, float]     # athlete id -> minutes, for players who played


@dataclass
class BoxScores:
    season: int
    games: dict[str, list[TeamGame]]                # tricode -> its games by date
    names: dict[str, dict[str, set[str]]]           # tricode -> normalised name -> athlete ids
    sources: list[dict] = field(default_factory=list)

    def recent(self, tricode: str, player: str, before: date, window: int) -> tuple[list[float] | None, str]:
        """His minutes in his last `window` games played for this team before `before`, oldest first
        (fewer if he has played fewer), or None and why they cannot be supplied."""
        ids = self.names.get(tricode, {}).get(report_name(player), set())
        if len(ids) != 1:
            return None, "逐場數據找不到這個名字" if not ids else "逐場數據裡有同名球員"
        athlete = next(iter(ids))
        played: list[float] = []
        for game in reversed([g for g in self.games.get(tricode, []) if g.day < before]):
            if not game.checked:
                if game.status != FINAL:
                    return None, f"{game.day:%m/%d} 那場在數據裡不是終場（{game.status}）"
                return None, f"{game.day:%m/%d} 那場的逐場數據不完整"
            if athlete in game.minutes:
                played.append(game.minutes[athlete])
                if len(played) == window:
                    break
        return played[::-1], ""

    def supply(self, wanted: dict[str, set[str]], before: date,
               window: int) -> tuple[dict[str, dict[str, list[float]]], dict[str, str]]:
        """(minutes by tricode and report name, why the others could not be supplied)."""
        found: dict[str, dict[str, list[float]]] = {}
        missing: dict[str, str] = {}
        for tricode, players in sorted(wanted.items()):
            for player in sorted(players):
                minutes, reason = self.recent(tricode, player, before, window)
                if minutes is None:
                    missing[f"{tricode} {player}"] = reason
                else:
                    found.setdefault(tricode, {})[player] = minutes
        return found, missing

    def summary(self) -> str:
        team_games = [g for games in self.games.values() for g in games if g.status == FINAL]
        return (f"season {self.season}: {len(team_games) // 2} final games, "
                f"{sum(g.checked for g in team_games)}/{len(team_games)} team box scores pass both checks")


def _rows(text: str, columns: tuple[str, ...], what: str) -> list[dict]:
    rows = list(csv.DictReader(io.StringIO(text)))
    if not rows or any(c not in rows[0] for c in columns):
        raise BoxScoreError(f"{what}: expected the columns {', '.join(columns)}")
    return rows


def _number(text: str) -> float:
    return float(text) if text not in ("", "NA") else 0.0


def _known(code: str) -> bool:
    try:
        team(code)
    except UnknownTeam:
        return False
    return True


def _tricode(code: str) -> str:
    try:
        return team(code).tricode
    except UnknownTeam:
        raise BoxScoreError(f"unknown team code {code!r}") from None


def parse(box_text: str, schedule_text: str, season: int, cfg) -> BoxScores:
    """Check each final game's two box scores (RULES R-9.3):

    - the points of the players who played add up to the team's score in the schedule;
    - their minutes fill the game: players on court x (regulation periods x period
      minutes + overtime periods x overtime minutes), within the per-player tolerance,
      since ESPN gives whole minutes.

    A player with 0 minutes (on for seconds) has not played a game here: leaving
    such games out can only make his window reach further back."""
    check = cfg.get("injuries.box_score_check")
    tolerance = cfg.get("injuries.box_score_minutes_tolerance_per_player")
    lines: dict[tuple[str, str], list[dict]] = defaultdict(list)
    names: dict[str, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
    for r in _rows(box_text, BOX_COLUMNS, "player box scores"):
        tricode = _tricode(r["team_abbreviation"])
        lines[(r["game_id"], tricode)].append(r)
        names[tricode][normalise(r["athlete_display_name"])].add(r["athlete_id"])
    games: dict[str, list[TeamGame]] = defaultdict(list)
    for g in _rows(schedule_text, SCHEDULE_COLUMNS, "schedule"):
        if g["status_type_name"] != FINAL and not all(_known(g[f"{side}_abbreviation"]) for side in ("home", "away")):
            continue          # teams not set yet (NBA Cup knockout "TBD"): not played, so in no window
        day = date.fromisoformat(g["game_date"])
        regulation = int(_number(g["format_regulation_periods"]))
        overtime = max(0, int(_number(g["status_period"])) - regulation)
        full = check["players_on_court"] * (regulation * check["period_minutes"]
                                            + overtime * check["overtime_minutes"])
        for side in ("home", "away"):
            tricode = _tricode(g[f"{side}_abbreviation"])
            rows = lines.get((g["game_id"], tricode), [])
            played = {r["athlete_id"]: _number(r["minutes"]) for r in rows
                      if r["did_not_play"] != "true" and _number(r["minutes"]) > 0}
            points = sum(_number(r["points"]) for r in rows)
            checked = (g["status_type_name"] == FINAL and bool(played)
                       and points == _number(g[f"{side}_score"])
                       and abs(sum(played.values()) - full) <= tolerance * len(played))
            games[tricode].append(TeamGame(g["game_id"], day, g["status_type_name"], checked, played))
    for team_games in games.values():
        team_games.sort(key=lambda t: t.day)
    return BoxScores(season, dict(games), {t: dict(n) for t, n in names.items()})


def _source(fetched: Fetched) -> dict:
    return {"url": fetched.url, "sha256": fetched.sha256, "retrieved_at": fetched.retrieved_at.isoformat(),
            "file": fetched.path.name if fetched.path else None}


def from_fetched(box: Fetched, schedule: Fetched, cfg) -> BoxScores:
    scores = parse(box.text(), schedule.text(), season_key(cfg), cfg)
    scores.sources = [_source(box), _source(schedule)]
    return scores


def fetch(client: HttpClient, cfg) -> BoxScores:
    season = season_key(cfg)
    return from_fetched(client.get(PLAYER_BOX.format(season=season)),
                        client.get(SCHEDULE.format(season=season)), cfg)


def load(box_path: Path | str, schedule_path: Path | str, cfg) -> BoxScores:
    return from_fetched(load_cached(box_path), load_cached(schedule_path), cfg)


# ---------------------------------------------------------------------- CLI


def main(argv: list[str] | None = None) -> int:
    from . import cli, net

    cli.setup_output()
    parser = argparse.ArgumentParser(prog="python -m bethero_nba.boxscores",
                                     description="Check the box-score files and show a player's recent minutes.")
    cli.add_root(parser)
    stored = parser.add_mutually_exclusive_group(required=True)
    stored.add_argument("--live", action="store_true", help="download the season's files now")
    stored.add_argument("--box", type=Path, help="stored player box scores (.csv.gz)")
    parser.add_argument("--schedule", type=Path, help="stored schedule (.csv.gz), with --box")
    parser.add_argument("--slate", type=date.fromisoformat, help="US Eastern slate date, with --team and --player")
    parser.add_argument("--team")
    parser.add_argument("--player", help="as the injury report prints it, e.g. 'Brunson, Jalen'")
    args = parser.parse_args(argv)
    root = cli.resolve_root(args.root)
    cfg = cli.load_config(root)
    try:
        if args.live:
            scores = fetch(net.HttpClient.from_config(cfg, root / "data" / "raw", live=True), cfg)
        elif args.schedule:
            scores = load(args.box, args.schedule, cfg)
        else:
            parser.error("--box needs --schedule")
    except (OSError, net.FetchError, BoxScoreError) as exc:
        print(f"box scores: {exc}")
        return 2
    print(scores.summary())
    for source in scores.sources:
        print(f"  {source['url']} sha256 {source['sha256'][:12]} -> {source['file']}")
    if args.team and args.player and args.slate:
        window = cfg.get("injuries.key_player_window_games")
        minutes, reason = scores.recent(team(args.team).tricode, args.player, args.slate, window)
        print(f"{args.player}: {reason}" if minutes is None else
              f"{args.player}: {len(minutes)} games before {args.slate}: {minutes}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
