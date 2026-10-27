"""Builders shared by the gate-engine tests."""

from __future__ import annotations

import copy
import csv
import io
import math
from datetime import date, datetime, timedelta, timezone

from bethero_nba import consensus, oddsapi
from bethero_nba.config import Config
from bethero_nba.dist import Anchored
from bethero_nba.edge import PassContext
from bethero_nba.platform import parse_board

TPE = timezone(timedelta(hours=8))
TIP = datetime(2026, 11, 3, 8, 30, tzinfo=TPE)
PLATFORM_TS = datetime(2026, 11, 3, 7, 10, tzinfo=TPE)
US_TS = datetime(2026, 11, 3, 7, 12, tzinfo=TPE)
ANALYSIS_TS = datetime(2026, 11, 3, 7, 14, tzinfo=TPE)
REPORT_TS = datetime(2026, 11, 3, 6, 45, tzinfo=TPE)

# RULES §18: eight books at home -5.5.
WORKED_SPREADS = [(-120, 100), (-118, -102), (-122, 102), (-115, -105),
                  (-120, 100), (-125, 105), (-119, -101), (-121, 101)]
HOME, AWAY = "Boston Celtics", "New York Knicks"


def with_values(cfg: Config, **changes) -> Config:
    """A copy of the config with some values replaced, e.g. {"distribution.status": "VALIDATED"}."""
    data = copy.deepcopy(cfg.data)
    for key, value in changes.items():
        node = data
        parts = key.replace("__", ".").split(".")
        for part in parts:
            node = node[part]
        node["value"] = value
    return Config(data)


def board(handicap=("4.5", "home", 0.95, 0.95), total=("大228.5", 0.94, 0.94),
          moneyline=(0.45, 1.75), platform_ts=PLATFORM_TS, ts_source="screenshot_clock",
          unresolved=()):
    text, row, ph, pa = handicap
    return parse_board({
        "schema": "bethero-nba-board/1", "slate_et": "2026-11-02",
        "platform_ts": platform_ts.isoformat() if platform_ts else None, "ts_source": ts_source,
        "source": "test", "games": [{
            "tip": TIP.isoformat(), "home": "BOS", "away": "NYK",
            "handicap": {"text": text, "row": row, "price_home": ph, "price_away": pa},
            "total": {"text": total[0], "price_over": total[1], "price_under": total[2]},
            "moneyline": {"price_home": moneyline[0], "price_away": moneyline[1]},
            "unresolved": list(unresolved)}]})


def us_game(spreads=WORKED_SPREADS, spread_point=-5.5, totals=((228.5, -110, -110),) * 8,
            h2h=((-250, 205),) * 8, age_min=2):
    updated = (US_TS - timedelta(minutes=age_min)).isoformat()
    books = []
    n = max(len(spreads), len(totals), len(h2h))
    for i in range(n):
        markets = []
        if i < len(spreads):
            hp, ap = spreads[i]
            markets.append({"key": "spreads", "last_update": updated, "outcomes": [
                {"name": HOME, "price": hp, "point": spread_point},
                {"name": AWAY, "price": ap, "point": -spread_point}]})
        if i < len(totals):
            point, op, up = totals[i]
            markets.append({"key": "totals", "last_update": updated, "outcomes": [
                {"name": "Over", "price": op, "point": point},
                {"name": "Under", "price": up, "point": point}]})
        if i < len(h2h):
            markets.append({"key": "h2h", "last_update": updated, "outcomes": [
                {"name": HOME, "price": h2h[i][0]}, {"name": AWAY, "price": h2h[i][1]}]})
        books.append({"key": f"B{i + 1}", "title": f"B{i + 1}", "last_update": updated, "markets": markets})
    return oddsapi.normalise([{"id": "g1", "commence_time": TIP.astimezone(timezone.utc).isoformat(),
                               "home_team": HOME, "away_team": AWAY, "bookmakers": books}])[0]


def game_consensus(game, cfg):
    return consensus.build(game, US_TS, methods=tuple(cfg.get("anchor.devig_methods")),
                           max_age_min=cfg.get("anchor.us_quote_max_age_min"))


class HypotheticalTierB:
    """The RULES §18 distribution: P(margin = 5) = 0.034 (bucket N = 1,800), P(margin = 6) = 0.033,
    normal comparison 0.031. Invented numbers for the worked example only."""

    PI5, PI6, N, PI5_NORMAL = 0.034, 0.033, 1800, 0.031

    def anchored(self, market, ref_line, p_ref):
        if market == "totals":                          # only used for the fair total here
            return Anchored({int(ref_line + 0.5): p_ref, int(ref_line - 0.5): 1 - p_ref}, ref_line, self.N), None
        assert market == "spreads" and ref_line == -5.5
        pmf = {7: p_ref - self.PI6, 6: self.PI6, 5: self.PI5, 0: 1 - p_ref - self.PI5}
        return Anchored(pmf, ref_line, self.N), None

    def sigma_translate(self, primary, alternative, ref_point, x):
        se = math.sqrt(self.PI5 * (1 - self.PI5) / self.N)
        return math.sqrt(se ** 2 + (abs(self.PI5 - self.PI5_NORMAL) / 2) ** 2)


def context(cfg, game_board, **overrides):
    label = game_board.games[0].label
    base = dict(cfg=cfg, analysis_ts=ANALYSIS_TS, platform_ts=game_board.platform_ts,
                ts_source=game_board.ts_source, us_ts=US_TS, final_eligible={label: True},
                injury_report_ts=REPORT_TS, blocking={label: []}, tier_b=None,
                model=lambda g: {"home_margin": 5.0, "total": 228.0},
                lag=lambda g, market: market == "handicap", flags={})
    base.update(overrides)
    return PassContext(**base)


# ------------------------------------------------- box scores (RULES R-9.3)

BOX_HEADER = ["game_id", "athlete_id", "athlete_display_name", "team_abbreviation", "minutes", "points",
              "did_not_play"]
SCHEDULE_HEADER = ["game_id", "game_date", "status_type_name", "status_period", "format_regulation_periods",
                   "home_abbreviation", "away_abbreviation", "home_score", "away_score"]
# Nine Knicks who fill 240 minutes when Brunson plays 35; 10 points each. ESPN codes, as in the files.
KNICKS = [("1", "Jalen Brunson", 35), ("2", "Josh Hart", 30), ("3", "OG Anunoby", 34),
          ("4", "Karl-Anthony Towns", 33), ("5", "Mikal Bridges", 36), ("6", "Miles McBride", 24),
          ("7", "Mitchell Robinson", 18), ("8", "Cameron Payne", 12), ("9", "Landry Shamet", 18)]


def _csv(header, rows):
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(header)
    writer.writerows(rows)
    return out.getvalue()


def box_season(games=12, brunson=35, start=date(2026, 10, 20), change=None):
    """(player box CSV, schedule CSV) for NY@BOS on consecutive days, every box score consistent.
    Robinson absorbs Brunson's minutes so the Knicks always fill 240. `change(i, knicks, row)` may
    edit game i's Knicks rows (lists) and schedule row (dict) before they are written."""
    def played(aid, m):
        return brunson if aid == "1" else m + 35 - brunson if aid == "7" else m

    box, schedule = [], []
    for i in range(games):
        game_id, day = str(100 + i), start + timedelta(days=i)
        knicks = [[game_id, aid, name, "NY", f"{played(aid, m):.1f}", "10", "false"] for aid, name, m in KNICKS]
        celtics = [[game_id, f"9{k}", f"Celtic {k}", "BOS", "48.0", "20", "false"] for k in range(5)]
        row = {"game_id": game_id, "game_date": day.isoformat(), "status_type_name": "STATUS_FINAL",
               "status_period": "4.0", "format_regulation_periods": "4.0", "home_abbreviation": "BOS",
               "away_abbreviation": "NY", "home_score": "100", "away_score": "90"}
        if change:
            change(i, knicks, row)
        box += knicks + celtics
        schedule.append([row[k] for k in SCHEDULE_HEADER])
    return _csv(BOX_HEADER, box), _csv(SCHEDULE_HEADER, schedule)
