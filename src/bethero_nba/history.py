"""Historical lines and results: the source adapter to the canonical history CSV.

    python -m bethero_nba.history --sqlite <path to OddsData.sqlite>

One source so far (VALIDATION.md D1): `Data/OddsData.sqlite` of
kyleskom/NBA-Machine-Learning-Sports-Betting, pinned to one commit and one
SHA-256 because the table choices below were checked on that file only. The
repository has no licence file, so the file and everything derived from it per
game stay on this machine (`data/history/`, gitignored, D5).

What the file holds, per season table: date, home, away, total (OU), spread,
both moneylines, final total (Points) and home margin (Win_Margin). Two
spread conventions:

- 2022-23 onward come from SBR's scoreboard through `sbrscrape`, whose script
  stores the away spread (`Get_Odds_Data.py`), so the home line is -Spread.
  The script's default book is FanDuel; the book is not recorded per row.
- 2007-08 to 2021-22 store the favourite's points without a sign (the
  sportsbookreviewsonline archive layout). The side laying them is the
  moneyline favourite. In the signed tables that rule picks the spread
  favourite in 3,874 of 3,884 games; in the unsigned ones about 1% of
  moneylines contradict the spread outright, and those games are dropped.

The source does not say whether its lines are closing lines; every result
built on it says so (D1).
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sqlite3
from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path

from . import cli
from .dist import HISTORY_COLUMNS, OPTIONAL_COLUMNS, HistoryRow
from .odds import american_to_decimal, devig_multiplicative, overround
from .teams import team

SOURCE = {
    "repo": "https://github.com/kyleskom/NBA-Machine-Learning-Sports-Betting",
    "commit": "8e36b0b72ecc5082aa8976dff742cdf910b3aa36",
    "commit_date": "2026-01-08",
    "file": "Data/OddsData.sqlite",
    "sha256": "4a803d41cd4597c1d898c0b131a58763dee8b64140be8f40c29b73c852e162d9",
    "licence": "none stated in the repository",
    "timing": "not stated by the source",
}
UNSIGNED, AWAY_SIGNED = "unsigned_favourite_points", "away_spread"
SBR_ARCHIVE = "sportsbookreviewsonline archive (per the dataset's notes; book not stated)"
SBR_SCOREBOARD = "SBR scoreboard via sbrscrape (script default FanDuel; book not recorded per row)"


@dataclass(frozen=True)
class Table:
    name: str
    convention: str
    lines: str


TABLES: dict[str, Table] = {
    **{f"{y}-{(y + 1) % 100:02d}": Table(f"odds_{y}-{(y + 1) % 100:02d}_new", UNSIGNED, SBR_ARCHIVE)
       for y in range(2007, 2022)},
    "2022-23": Table("odds_2022-23_new", AWAY_SIGNED, SBR_SCOREBOARD),
    # `2023-24` has 1,255 rows; `odds_2023-24_new` has 1,195, a different Clippers
    # name and four wrong final scores on the games the two share.
    "2023-24": Table("2023-24", AWAY_SIGNED, SBR_SCOREBOARD),
    "2024-25": Table("2024-25", AWAY_SIGNED, SBR_SCOREBOARD),
    "2025-26": Table("odds_2025-26", AWAY_SIGNED, SBR_SCOREBOARD),
}

# Former names of current franchises, as this dataset spells them
FORMER_NAMES = {"LA Clippers": "LAC", "Charlotte Bobcats": "CHA", "New Jersey Nets": "BKN",
                "Seattle SuperSonics": "OKC"}

MAX_ABS_SPREAD, TOTAL_RANGE, TEAM_SCORE_RANGE = 30.0, (150.0, 300.0), (50, 200)   # D2
MIN_GAMES_REGULAR_DAY = 10                                                     # D3
MARGIN_RANGE = (0.0, 0.15)             # a moneyline pair outside this is not a moneyline pair
CLEAR_SPREAD, CLEAR_FAVOURITE = 4.0, 0.55   # laying 4+ points with a near-even moneyline: contradiction
PICKEM_MAX_FAVOURITE = 0.60                 # a pick'em whose moneyline says more is a contradiction
COMPLETE_FROM_MONTH = 4                     # a season whose regular season reaches April is complete

DROP_REASONS = (
    "after regular season (D3)", "unknown team", "missing score", "impossible score",
    "missing line", "line out of range (D2)", "negative spread in an unsigned table",
    "spread side unresolved", "moneyline contradicts spread", "duplicate game",
)


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def connect_read_only(path: Path) -> sqlite3.Connection:
    """Third-party file: read-only, and no functions called from its schema."""
    con = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)
    con.execute("PRAGMA trusted_schema = OFF")
    return con


def _number(value) -> float | None:
    if isinstance(value, str) and value.strip().upper() == "PK":
        return 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _tricode(name: str) -> str | None:
    if name in FORMER_NAMES:
        return FORMER_NAMES[name]
    try:
        return team(name).tricode
    except KeyError:
        return None


def moneyline_pair(home: float | None, away: float | None) -> tuple[float, float] | None:
    """Both American prices, each at least 100 in size, with a believable margin."""
    if home is None or away is None or abs(home) < 100 or abs(away) < 100:
        return None
    decimals = [american_to_decimal(home), american_to_decimal(away)]
    if not MARGIN_RANGE[0] <= overround(decimals) <= MARGIN_RANGE[1]:
        return None
    return home, away


def home_line(convention: str, spread: float, ml: tuple[float, float] | None) -> tuple[float | None, str | None]:
    """(home spread, drop reason). The moneyline decides the side for unsigned tables
    and is checked against the spread for signed ones."""
    p_home = devig_multiplicative([american_to_decimal(ml[0]), american_to_decimal(ml[1])])[0] if ml else None
    if convention == AWAY_SIGNED:
        line = -spread + 0.0
    else:
        if spread < 0:
            return None, "negative spread in an unsigned table"
        if spread == 0:
            line = 0.0
        elif p_home is None or p_home == 0.5:
            return None, "spread side unresolved"
        else:
            line = -spread if p_home > 0.5 else spread
    if p_home is not None:
        p_fav = max(p_home, 1 - p_home)
        if line == 0 and p_fav > PICKEM_MAX_FAVOURITE:
            return None, "moneyline contradicts spread"
        if line != 0 and p_home != 0.5 and (line < 0) != (p_home > 0.5):
            return None, "moneyline contradicts spread"
        if abs(line) >= CLEAR_SPREAD and p_fav < CLEAR_FAVOURITE:
            return None, "moneyline contradicts spread"
    return line, None


def _scores(points, margin) -> tuple[int, int] | str:
    points, margin = _number(points), _number(margin)
    if not points or margin is None:
        return "missing score"
    if margin == 0 or points != int(points) or margin != int(margin) or (points + margin) % 2:
        return "impossible score"
    home, away = int((points + margin) // 2), int((points - margin) // 2)
    lo, hi = TEAM_SCORE_RANGE
    if not (lo <= home <= hi and lo <= away <= hi):
        return "impossible score"
    return home, away


@dataclass
class SeasonTally:
    table: str
    raw: int = 0
    last_regular_day: str | None = None
    complete: bool = False
    dropped: Counter = None
    kept: int = 0

    def __post_init__(self):
        self.dropped = self.dropped or Counter()


def convert_season(con: sqlite3.Connection, season: str, table: Table) -> tuple[list[HistoryRow], SeasonTally]:
    rows = con.execute(f'SELECT Date, Home, Away, OU, Spread, ML_Home, ML_Away, Points, Win_Margin '
                       f'FROM "{table.name}"').fetchall()
    tally = SeasonTally(table.name, raw=len(rows))
    per_day = Counter(str(r[0])[:10] for r in rows)
    regular_days = [d for d, n in per_day.items() if n >= MIN_GAMES_REGULAR_DAY]
    last_day = date.fromisoformat(max(regular_days)) if regular_days else None
    tally.last_regular_day = last_day.isoformat() if last_day else None
    tally.complete = bool(last_day) and last_day.month >= COMPLETE_FROM_MONTH and last_day.month < 10
    out: list[HistoryRow] = []
    seen: set[tuple] = set()
    for raw_date, home, away, ou, spread, ml_home, ml_away, points, margin in rows:
        day = date.fromisoformat(str(raw_date)[:10])
        reason = None
        if last_day is None or day > last_day:
            reason = "after regular season (D3)"
        h, a = _tricode(str(home)), _tricode(str(away))
        scores = _scores(points, margin)
        total, spread = _number(ou), _number(spread)
        ml = moneyline_pair(_number(ml_home), _number(ml_away))
        if reason is None and (h is None or a is None or h == a):
            reason = "unknown team"
        if reason is None and isinstance(scores, str):
            reason = scores
        if reason is None and (total is None or spread is None):
            reason = "missing line"
        if reason is None and (abs(spread) > MAX_ABS_SPREAD or not TOTAL_RANGE[0] <= total <= TOTAL_RANGE[1]):
            reason = "line out of range (D2)"
        line = None
        if reason is None:
            line, reason = home_line(table.convention, spread, ml)
        if reason is None and (day, h, a) in seen:
            reason = "duplicate game"
        if reason:
            tally.dropped[reason] += 1
            continue
        seen.add((day, h, a))
        out.append(HistoryRow(season, day, h, a, scores[0], scores[1], line, total,
                              f"kyleskom@{SOURCE['commit'][:7]}:{table.name}",
                              ml[0] if ml else None, ml[1] if ml else None))
    tally.kept = len(out)
    return out, tally


def write_csv(rows: list[HistoryRow], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh, lineterminator="\n")
        writer.writerow(HISTORY_COLUMNS + OPTIONAL_COLUMNS)
        for r in rows:
            writer.writerow([r.season, r.date.isoformat(), r.home, r.away, r.home_score, r.away_score,
                             _fmt(r.close_spread_home), _fmt(r.close_total), r.source,
                             _fmt(r.close_ml_home), _fmt(r.close_ml_away)])


def _fmt(value: float | None) -> str:
    return "" if value is None else f"{value:g}"


def provenance_path(history_csv: Path) -> Path:
    return history_csv.with_suffix(".provenance.json")


def load_provenance(history_csv: Path | str) -> dict:
    path = provenance_path(Path(history_csv))
    if not path.exists():
        raise FileNotFoundError(f"{path} is missing: a history file needs its provenance (VALIDATION.md D1)")
    return json.loads(path.read_text(encoding="utf-8"))


def convert(sqlite_path: Path, out: Path, *, expected_sha256: str = SOURCE["sha256"]) -> dict:
    digest = sha256_of(sqlite_path)
    if digest != expected_sha256:
        raise SystemExit(f"{sqlite_path} has SHA-256 {digest}; this adapter was checked on "
                         f"{expected_sha256} ({SOURCE['repo']} at {SOURCE['commit'][:7]}). "
                         "Re-check the table choices before using another version.")
    con = connect_read_only(sqlite_path)
    try:
        everything: list[HistoryRow] = []
        seasons = {}
        for season, table in TABLES.items():
            rows, tally = convert_season(con, season, table)
            everything += rows
            seasons[season] = {"table": tally.table, "convention": table.convention, "lines": table.lines,
                               "raw": tally.raw, "last_regular_day": tally.last_regular_day,
                               "complete": tally.complete, "kept": tally.kept,
                               "dropped": {k: tally.dropped[k] for k in DROP_REASONS if tally.dropped[k]}}
    finally:
        con.close()
    write_csv(everything, out)
    provenance = {
        "schema": "bethero-nba-history/1",
        "converted_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source": {**SOURCE, "sha256_checked": digest},
        "rules": {
            "D2": f"|spread| <= {MAX_ABS_SPREAD:g}, total in {TOTAL_RANGE[0]:g}-{TOTAL_RANGE[1]:g}, "
                  f"each team score in {TEAM_SCORE_RANGE[0]}-{TEAM_SCORE_RANGE[1]}, no tied final",
            "D3": f"regular season ends on the last date with at least {MIN_GAMES_REGULAR_DAY} games",
            "moneyline": f"both prices, bookmaker margin {MARGIN_RANGE[0]:.0%}-{MARGIN_RANGE[1]:.0%}; "
                         "otherwise the moneyline columns are left empty",
            "spread side": "signed tables: home line = -away spread; unsigned tables: the moneyline "
                           "favourite lays the points, and without a usable moneyline the game is dropped",
            "contradiction": f"dropped when the moneyline favours the other side, when a side lays "
                             f"{CLEAR_SPREAD:g}+ points with a favourite below {CLEAR_FAVOURITE:.0%}, "
                             f"or when a pick'em has a favourite above {PICKEM_MAX_FAVOURITE:.0%}",
            "complete": "a season is complete when its regular season reaches April",
        },
        "seasons": seasons,
    }
    provenance_path(out).write_text(json.dumps(provenance, indent=2) + "\n", encoding="utf-8", newline="\n")
    return provenance


def summary(provenance: dict) -> str:
    lines = ["| season | table | raw | kept | last regular day | complete | dropped |", "|---|---|---|---|---|---|---|"]
    for season, s in provenance["seasons"].items():
        dropped = "; ".join(f"{k} {v}" for k, v in s["dropped"].items()) or "none"
        lines.append(f"| {season} | `{s['table']}` | {s['raw']} | {s['kept']} | {s['last_regular_day']} "
                     f"| {'yes' if s['complete'] else 'no'} | {dropped} |")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    cli.setup_output()
    parser = argparse.ArgumentParser(prog="python -m bethero_nba.history", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    cli.add_root(parser)
    parser.add_argument("--sqlite", type=Path, required=True,
                        help=f"{SOURCE['file']} from {SOURCE['repo']} at {SOURCE['commit'][:7]}")
    parser.add_argument("--out", type=Path, default=None, help="default: data/history/games.csv")
    args = parser.parse_args(argv)
    root = cli.resolve_root(args.root)
    out = args.out or root / "data" / "history" / "games.csv"
    provenance = convert(args.sqlite, out)
    print(summary(provenance))
    print(f"\nwrote {out} and {provenance_path(out).name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
