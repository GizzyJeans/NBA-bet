"""NBA teams: tricode, The Odds API name, Chinese name, home-arena time zone.

Tricodes are the join key: the platform board prints them next to the Chinese
name (「ORL 魔術[主]」), and the US feed is mapped to them by full name.
Chinese names are display only. 魔術, 老鷹, 巫師 and 公鹿 are as seen on Eric's
board (2026-10-21); the rest are the usual Taiwanese names and get corrected
from later screenshots if the platform differs. Time zones are those of each
team's home city (IANA), used only for the TRAVEL_TZ flag.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Team:
    tricode: str
    name: str            # as The Odds API spells it
    zh: str
    tz: str
    aliases: tuple[str, ...] = ()


TEAMS: tuple[Team, ...] = (
    Team("ATL", "Atlanta Hawks", "老鷹", "America/New_York"),
    Team("BOS", "Boston Celtics", "塞爾提克", "America/New_York"),
    Team("BKN", "Brooklyn Nets", "籃網", "America/New_York"),
    Team("CHA", "Charlotte Hornets", "黃蜂", "America/New_York"),
    Team("CHI", "Chicago Bulls", "公牛", "America/Chicago"),
    Team("CLE", "Cleveland Cavaliers", "騎士", "America/New_York"),
    Team("DAL", "Dallas Mavericks", "獨行俠", "America/Chicago", ("小牛",)),
    Team("DEN", "Denver Nuggets", "金塊", "America/Denver"),
    Team("DET", "Detroit Pistons", "活塞", "America/Detroit"),
    Team("GSW", "Golden State Warriors", "勇士", "America/Los_Angeles"),
    Team("HOU", "Houston Rockets", "火箭", "America/Chicago"),
    Team("IND", "Indiana Pacers", "溜馬", "America/Indiana/Indianapolis"),
    Team("LAC", "Los Angeles Clippers", "快艇", "America/Los_Angeles", ("LA Clippers",)),   # NBA's own spelling
    Team("LAL", "Los Angeles Lakers", "湖人", "America/Los_Angeles"),
    Team("MEM", "Memphis Grizzlies", "灰熊", "America/Chicago"),
    Team("MIA", "Miami Heat", "熱火", "America/New_York"),
    Team("MIL", "Milwaukee Bucks", "公鹿", "America/Chicago"),
    Team("MIN", "Minnesota Timberwolves", "灰狼", "America/Chicago"),
    Team("NOP", "New Orleans Pelicans", "鵜鶘", "America/Chicago", ("NO",)),      # platform code
    Team("NYK", "New York Knicks", "尼克", "America/New_York"),
    Team("OKC", "Oklahoma City Thunder", "雷霆", "America/Chicago"),
    Team("ORL", "Orlando Magic", "魔術", "America/New_York"),
    Team("PHI", "Philadelphia 76ers", "76人", "America/New_York", ("七六人",)),
    Team("PHX", "Phoenix Suns", "太陽", "America/Phoenix"),
    Team("POR", "Portland Trail Blazers", "拓荒者", "America/Los_Angeles"),
    Team("SAC", "Sacramento Kings", "國王", "America/Los_Angeles"),
    Team("SAS", "San Antonio Spurs", "馬刺", "America/Chicago", ("SAN",)),       # platform code
    Team("TOR", "Toronto Raptors", "暴龍", "America/Toronto"),
    Team("UTA", "Utah Jazz", "爵士", "America/Denver"),
    Team("WAS", "Washington Wizards", "巫師", "America/New_York"),
)

_BY_KEY: dict[str, Team] = {}
for _team in TEAMS:
    for _key in (_team.tricode, _team.name, _team.zh, *_team.aliases):
        _BY_KEY[_key.casefold()] = _team


class UnknownTeam(KeyError):
    pass


def team(key: str) -> Team:
    """Look a team up by tricode, Odds API name, or Chinese name."""
    try:
        return _BY_KEY[key.strip().casefold()]
    except KeyError:
        raise UnknownTeam(key) from None


def zh(key: str) -> str:
    """Chinese name for display; unknown keys pass through unchanged."""
    try:
        return team(key).zh
    except UnknownTeam:
        return key
