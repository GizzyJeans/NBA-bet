"""Platform notation and board files (transcribed screenshots).

Settlement rules as in Codex-NPB `tests/test_platform_rules.py`
(GizzyJeans/Codex-NPB@d85a216) and cc_npb `bethero/lines.py` (@cfe74e9).

Notation (RULES §3.2), seen from the side laying the line, or the over:

    X.5     one leg at X.5; cannot push
    N平     one leg at N; exactly N pushes
    N+XX    XX% of the stake at N - 0.5, the rest at N
    N-XX    the rest at N, XX% of the stake at N + 0.5
    N       bare integer: not seen on the NBA board, UNCONFIRMED
    -       market not offered

`5+50` is therefore 4.75: if the giving team wins by exactly 5, half the stake
wins at 4.5 and half pushes at 5, which is Eric's confirmed case (100 on WAS
wins 47.5 at 0.95; 100 on MIL loses 50). The split reproduces the platform
rule exactly for integer scores, so EV, Kelly and CLV all work on legs and
never on the effective line itself.

Board files are Claude's transcriptions of Eric's screenshots
(`data/boards/<slate>/<platform_ts>.json`, RULES R-4.2). Anything that could not
be read with certainty is listed under `unresolved`, and that market is not
priced. Schema errors are transcription bugs and raise `BoardError`.
"""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date, datetime
from enum import Enum
from pathlib import Path
from zoneinfo import ZoneInfo

from .odds import Leg
from .teams import Team, UnknownTeam, team

SCHEMA = "bethero-nba-board/1"
TS_SOURCES = ("screenshot_clock", "received", "unknown")
EASTERN = ZoneInfo("America/New_York")


class LineKind(str, Enum):
    HALF = "half"
    FLAT = "flat"
    TAIL = "tail"
    BARE = "bare"
    NOT_OFFERED = "not_offered"
    UNREADABLE = "unreadable"


# config key under platform.notation that holds each kind's settlement status
NOTATION_KEYS = {
    LineKind.HALF: "half_line",
    LineKind.FLAT: "flat_line",
    LineKind.TAIL: "tail_line",
    LineKind.BARE: "bare_integer",
}

_HALF = re.compile(r"(\d+)\.5")
_FLAT = re.compile(r"(\d+)平")
_TAIL = re.compile(r"(\d+)([+-])(\d{2})")
_BARE = re.compile(r"\d+")
_SINGLE_DIGIT_TAIL = re.compile(r"\d+[+-]\d")
_NOT_OFFERED = {"-", "—", "–"}


@dataclass(frozen=True)
class PlatformLine:
    raw: str
    kind: LineKind
    legs: tuple[Leg, ...] = ()
    note: str = ""

    @property
    def effective(self) -> float | None:
        """N - s/2: the single number a split ticket is equivalent to on average."""
        if not self.legs:
            return None
        return sum(leg.line * leg.weight for leg in self.legs)


def parse_line(text: str) -> PlatformLine:
    """Decode one handicap or total cell; a leading 大 / 小 is ignored."""
    raw = text
    s = unicodedata.normalize("NFKC", text).strip().replace(" ", "")
    if s[:1] in ("大", "小"):
        s = s[1:]
    if s in _NOT_OFFERED:
        return PlatformLine(raw, LineKind.NOT_OFFERED)
    if m := _HALF.fullmatch(s):
        return PlatformLine(raw, LineKind.HALF, (Leg(int(m.group(1)) + 0.5, 1.0),))
    if m := _FLAT.fullmatch(s):
        return PlatformLine(raw, LineKind.FLAT, (Leg(float(m.group(1)), 1.0),))
    if m := _TAIL.fullmatch(s):
        base, sign, pct = int(m.group(1)), m.group(2), int(m.group(3))
        if pct == 0:
            return PlatformLine(raw, LineKind.UNREADABLE, note="tail of 00")
        share = pct / 100
        legs = ((Leg(base - 0.5, share), Leg(float(base), 1.0 - share)) if sign == "+"
                else (Leg(float(base), 1.0 - share), Leg(base + 0.5, share)))
        return PlatformLine(raw, LineKind.TAIL, legs)
    if _BARE.fullmatch(s):
        return PlatformLine(raw, LineKind.BARE, note="bare integer without 平")
    if _SINGLE_DIGIT_TAIL.fullmatch(s):
        return PlatformLine(raw, LineKind.UNREADABLE,
                            note="one-digit tail: 5% and 50% are different lines")
    return PlatformLine(raw, LineKind.UNREADABLE, note="unrecognised notation")


def notation_status(line: PlatformLine, cfg) -> str:
    """Settlement status of a line's notation from cfg:platform.notation."""
    key = NOTATION_KEYS.get(line.kind)
    if key is None:
        return "UNREADABLE" if line.kind is LineKind.UNREADABLE else "NOT_OFFERED"
    return cfg.status(f"platform.notation.{key}")


# --------------------------------------------------------------------- boards


class BoardError(ValueError):
    pass


@dataclass(frozen=True)
class Market:
    """One platform market of one game.

    `prices` is keyed by side: home/away for 讓分 and 獨贏, over/under for 大小.
    A price of None means the board showed 「-」.
    """

    kind: str
    prices: dict[str, float | None]
    line: PlatformLine | None = None
    giver: str | None = None          # 讓分 only: "home" or "away" lays the line
    unresolved: bool = False

    @property
    def offered(self) -> bool:
        if any(p is None for p in self.prices.values()):
            return False
        return self.line is None or self.line.kind is not LineKind.NOT_OFFERED


@dataclass(frozen=True)
class BoardGame:
    tip: datetime
    home: Team
    away: Team
    handicap: Market
    total: Market
    moneyline: Market
    unresolved: tuple[str, ...] = ()

    @property
    def markets(self) -> tuple[Market, Market, Market]:
        return (self.handicap, self.total, self.moneyline)

    @property
    def label(self) -> str:
        return f"{self.away.tricode}@{self.home.tricode}"


@dataclass(frozen=True)
class Board:
    slate_et: date
    platform_ts: datetime | None
    ts_source: str
    source: str
    games: tuple[BoardGame, ...]
    path: Path | None = field(default=None, compare=False)


def _price(value, where: str) -> float | None:
    if isinstance(value, str) and value.strip() in _NOT_OFFERED:
        return None
    if isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0:
        return float(value)
    raise BoardError(f"{where}: price must be a positive number or \"-\", got {value!r}")


def _timestamp(value, where: str) -> datetime:
    try:
        moment = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        raise BoardError(f"{where}: not an ISO-8601 timestamp: {value!r}") from None
    if moment.tzinfo is None:
        raise BoardError(f"{where}: timestamp needs an offset: {value!r}")
    return moment


def _require(mapping: dict, key: str, where: str):
    if key not in mapping:
        raise BoardError(f"{where}: missing {key!r}")
    return mapping[key]


def _game(raw: dict, where: str) -> BoardGame:
    try:
        home, away = team(_require(raw, "home", where)), team(_require(raw, "away", where))
    except UnknownTeam as exc:
        raise BoardError(f"{where}: unknown team {exc.args[0]!r}") from None
    unresolved = tuple(raw.get("unresolved", ()))

    def flagged(name: str) -> bool:
        return any(u == name or u.startswith(name + ".") for u in unresolved)

    h = _require(raw, "handicap", where)
    giver = _require(h, "row", f"{where}.handicap")
    if giver not in ("home", "away"):
        raise BoardError(f"{where}.handicap.row must be 'home' or 'away', got {giver!r}")
    handicap = Market(
        "handicap",
        {"home": _price(_require(h, "price_home", f"{where}.handicap"), f"{where}.handicap"),
         "away": _price(_require(h, "price_away", f"{where}.handicap"), f"{where}.handicap")},
        parse_line(str(_require(h, "text", f"{where}.handicap"))), giver, flagged("handicap"))

    t = _require(raw, "total", where)
    total = Market(
        "total",
        {"over": _price(_require(t, "price_over", f"{where}.total"), f"{where}.total"),
         "under": _price(_require(t, "price_under", f"{where}.total"), f"{where}.total")},
        parse_line(str(_require(t, "text", f"{where}.total"))), None, flagged("total"))

    ml = _require(raw, "moneyline", where)
    moneyline = Market(
        "moneyline",
        {"home": _price(_require(ml, "price_home", f"{where}.moneyline"), f"{where}.moneyline"),
         "away": _price(_require(ml, "price_away", f"{where}.moneyline"), f"{where}.moneyline")},
        None, None, flagged("moneyline"))

    return BoardGame(_timestamp(_require(raw, "tip", where), f"{where}.tip"),
                     home, away, handicap, total, moneyline, unresolved)


def parse_board(data: dict, path: Path | None = None) -> Board:
    where = str(path or "board")
    if data.get("schema") != SCHEMA:
        raise BoardError(f"{where}: schema must be {SCHEMA!r}")
    ts_source = _require(data, "ts_source", where)
    if ts_source not in TS_SOURCES:
        raise BoardError(f"{where}: ts_source must be one of {TS_SOURCES}")
    raw_ts = _require(data, "platform_ts", where)
    platform_ts = None if raw_ts is None else _timestamp(raw_ts, f"{where}.platform_ts")
    if (platform_ts is None) != (ts_source == "unknown"):
        raise BoardError(f"{where}: platform_ts is null exactly when ts_source is 'unknown'")
    try:
        slate = date.fromisoformat(_require(data, "slate_et", where))
    except (TypeError, ValueError):
        raise BoardError(f"{where}: slate_et must be YYYY-MM-DD") from None
    games = tuple(_game(g, f"{where}.games[{i}]") for i, g in enumerate(_require(data, "games", where)))
    for game in games:
        if game.tip.astimezone(EASTERN).date() != slate:
            raise BoardError(f"{where}: {game.label} tips on another US Eastern date than {slate}")
    return Board(slate, platform_ts, ts_source, str(data.get("source", "")), games, path)


def load_board(path: Path | str) -> Board:
    path = Path(path)
    return parse_board(json.loads(path.read_text(encoding="utf-8")), path)


def moneyline_conflict(game: BoardGame) -> str | None:
    """RULES R-3.4: the board's moneyline favourite must be the team laying the handicap."""
    ml, h = game.moneyline, game.handicap
    if not (ml.offered and h.offered) or h.line is None or not h.line.legs:
        return None
    if ml.prices["home"] == ml.prices["away"]:
        return None
    favourite = "home" if ml.prices["home"] < ml.prices["away"] else "away"
    if favourite != h.giver:
        return (f"board moneyline favours {favourite} but the handicap is printed "
                f"in the {h.giver} row")
    return None
