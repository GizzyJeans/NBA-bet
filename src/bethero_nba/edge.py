"""EV, gates G0-G12, Kelly, caps, confidence and reason codes.

RULES §12 (EV, gates, sizing), §13 (confidence) and §15 (codes). Every side of
every market on the board becomes a `Decision`, bet or not (P4). Gates run in
the RULES order and every failure is recorded; the first one is the primary
reason shown in the report. Data completeness is checked before the edge is
even computed into a decision, so a missing input cannot turn into a small
edge (MLB `policy.py`).

Probabilities always come from the US consensus (P1): Tier A reads the quoted
lines directly, Tier B translates through a VALIDATED distribution, and
everything else is Tier C. The model may only veto or downgrade.
"""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Callable

from . import context
from .consensus import GameConsensus
from .odds import (Leg, devig, effective_win_probability, expected_value, hk_to_decimal,
                   kelly_fraction, needed_points, ticket_outcomes)
from .oddsapi import Game
from .platform import (BoardGame, LineKind, Market, PlatformLine, moneyline_conflict,
                       notation_status, parse_line)
from .teams import team

# RULES §15, in gate order (G0 ... G12). The 說明 column is checked against RULES.md by a test.
CODES: dict[str, str] = {
    "NB-SCOPE": "不在 v1 範圍（更多玩法、季後賽等）",
    "NB-NOT-OFFERED": "平台沒開這個盤（顯示「-」）",
    "NB-PAUSED": "暫停規則啟動中，等待診斷",
    "NB-FORMAT": "盤口寫法或賠率格式讀不出來或未確認",
    "NB-SETTLEMENT": "這種寫法的結算規則未確認（目前沒有）",
    "NB-STALE": "平台與美盤快照不同步，報價或傷病報告過舊，或已開賽",
    "NB-DATA": "資料不足或互相矛盾（書商太少、隊名對不上、獨贏與讓分矛盾、API 額度不足）",
    "NB-SANITY": "與美盤公平線差太多或方向相反，推定是舊盤、抄錯或未反映的消息",
    "NB-TIER-C": "需要的換算超出範圍，或分布尚未驗證",
    "NB-STATUS": "關鍵球員出賽未定、當日傷病報告或裁判名單未出，或拿不到傷病報告",
    "NB-EV": "期望值未達門檻，或扣掉雜訊後不為正",
    "NB-DIVERGENCE": "公平機率與平台無水機率的差距不夠",
    "NB-MODEL-VETO": "獨立模型明顯站在另一邊",
    "NB-CORR": "同場已選讓分或獨贏其中之一",
    "NB-CAP": "單日或單場上限已滿",
    "NB-MIN-STAKE": "算出的注額低於平台最低注額",
}
ORDER = {code: i for i, code in enumerate(CODES)}
US_MARKET = {"handicap": "spreads", "total": "totals", "moneyline": "h2h"}
LEVELS = ("Low", "Medium", "High")


@dataclass
class PassContext:
    """Everything about one analysis pass that is not specific to a market."""

    cfg: Any
    analysis_ts: datetime
    platform_ts: datetime | None
    ts_source: str
    us_ts: datetime | None
    final_eligible: dict[str, bool] | None = None    # game label -> RULES R-4.5; None = unknown
    injury_report_ts: datetime | None = None
    blocking: dict[str, list[str]] | None = None      # game label -> key players Q/D; None = no data
    tier_b: Any | None = None                         # VALIDATED distribution provider, else None
    model: Callable[[BoardGame], dict | None] | None = None   # {"home_margin", "total"}
    lag: Callable[[BoardGame, str], bool] | None = None       # RULES R-9.5 holds
    bias: Callable[["Decision"], bool] | None = None          # matches a USABLE bias
    flags: dict[str, list[str]] = field(default_factory=dict)


@dataclass
class Decision:
    game: BoardGame
    market: str                 # handicap | total | moneyline
    side: str                   # home | away | over | under
    laying: bool
    price: float | None
    other_price: float | None
    line: PlatformLine | None
    codes: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    flags: list[str] = field(default_factory=list)
    tier: str | None = None
    l_ref: float | None = None
    n_books: int | None = None
    fair_line: float | None = None          # giving / over orientation
    fair_source: str | None = None
    ev: dict[str, float] = field(default_factory=dict)
    p_eff: dict[str, float] = field(default_factory=dict)
    masses: dict[str, dict[str, float]] = field(default_factory=dict)
    worst_method: str | None = None
    sigma: dict[str, float] = field(default_factory=dict)
    platform_novig: float | None = None
    agreement: float | None = None
    kelly: float | None = None
    stake: float | None = None
    confidence: str | None = None
    edge_label: str | None = None
    model_d: float | None = None
    downgrade: bool = False
    worst_line: str | None = None

    def fail(self, code: str, note: str | None = None) -> None:
        if code not in self.codes:
            self.codes.append(code)
        if note:
            self.notes.append(note)

    @property
    def primary(self) -> str | None:
        return min(self.codes, key=ORDER.__getitem__) if self.codes else None

    @property
    def is_bet(self) -> bool:
        return not self.codes and bool(self.stake)

    @property
    def priced(self) -> bool:
        return self.worst_method is not None

    @property
    def ev_worst(self) -> float | None:
        return self.ev.get(self.worst_method) if self.worst_method else None

    @property
    def p_worst(self) -> float | None:
        return self.p_eff.get(self.worst_method) if self.worst_method else None

    @property
    def divergence(self) -> float | None:
        if self.p_worst is None or self.platform_novig is None:
            return None
        return self.p_worst - self.platform_novig

    def ev_lower(self, z: float) -> float | None:
        if self.ev_worst is None:
            return None
        return self.ev_worst - z * self.sigma.get("ev", 0.0)

    def selection(self) -> str:
        """The bet in Chinese: 巫師 讓 5+50 / 公鹿 受讓 5+50 / 大 238.5 / 巫師 獨贏."""
        side_team = self.game.home if self.side == "home" else self.game.away
        text = (self.line.raw.lstrip("大小") if self.line else "")
        if self.market == "total":
            return f"{'大' if self.side == 'over' else '小'} {text}"
        if self.market == "moneyline":
            return f"{side_team.zh} 獨贏"
        return f"{side_team.zh} {'讓' if self.laying else '受讓'} {text}"

    def to_record(self, ctx: PassContext) -> dict:
        iso = lambda t: t.isoformat() if t else None      # noqa: E731
        return {
            "record_type": "decision",
            "schema": "bethero-nba-decision/1",
            "config_version": ctx.cfg.version,
            "mode": ctx.cfg.get("mode"),
            "analysis_ts": iso(ctx.analysis_ts),
            "platform_ts": iso(ctx.platform_ts),
            "ts_source": ctx.ts_source,
            "us_ts": iso(ctx.us_ts),
            "injury_report_ts": iso(ctx.injury_report_ts),
            "game": {"home": self.game.home.tricode, "away": self.game.away.tricode,
                     "tip": self.game.tip.isoformat()},
            "market": self.market, "side": self.side, "laying": self.laying,
            "platform": {"text": self.line.raw if self.line else None,
                         "legs": [[leg.line, leg.weight] for leg in self.line.legs] if self.line else [],
                         "price": self.price, "other_price": self.other_price},
            "us": {"l_ref": self.l_ref, "n_books": self.n_books, "fair_line": self.fair_line,
                   "fair_source": self.fair_source},
            "tier": self.tier, "ev": self.ev, "p_eff": self.p_eff, "masses": self.masses,
            "worst_method": self.worst_method, "sigma": self.sigma,
            "platform_novig": self.platform_novig, "divergence": self.divergence,
            "agreement": self.agreement, "kelly": self.kelly, "stake": self.stake,
            "codes": self.codes, "primary": self.primary, "notes": self.notes,
            "flags": self.flags, "confidence": self.confidence, "edge_label": self.edge_label,
            "model_d": self.model_d, "worst_line": self.worst_line,
        }


# ------------------------------------------------------------------ helpers


def _other(side: str) -> str:
    return {"home": "away", "away": "home", "over": "under", "under": "over"}[side]


def _sides(market: Market) -> tuple[tuple[str, bool], tuple[str, bool]]:
    if market.kind == "handicap":
        return ((market.giver, True), (_other(market.giver), False))
    if market.kind == "total":
        return (("over", True), ("under", False))
    return (("home", True), ("away", False))


def _giver(market: Market) -> str:
    return {"handicap": market.giver, "total": "over", "moneyline": "home"}[market.kind]


def _scale(market: Market) -> str:
    return "total" if market.kind == "total" else "spread"


def _to_giving(us_market: str, giver: str, home_value: float) -> float:
    """A home-space point or line (home margin, home spread negated) in the giver's orientation."""
    if us_market == "spreads" and giver == "away":
        return -home_value
    return home_value


def _giving_cover(us_market: str, giver: str, home_cover: Callable[[float], float]) -> Callable[[float], float]:
    if us_market == "spreads" and giver == "away":
        return lambda x: 1.0 - home_cover(-x)
    return home_cover


def match_us_game(game: BoardGame, us_games: list[Game], hours: float = 3.0) -> tuple[Game | None, str | None]:
    """The US event for a board game: same teams, tip within `hours`.

    Swapped home/away is a data conflict except at the NBA Cup final, which is
    on a neutral site (RULES R-6.1)."""
    for g in us_games:
        try:
            home, away = team(g.home_team).tricode, team(g.away_team).tricode
        except KeyError:
            continue
        if abs(g.commence_time - game.tip) > timedelta(hours=hours):
            continue
        if (home, away) == (game.home.tricode, game.away.tricode):
            return g, None
        if (home, away) == (game.away.tricode, game.home.tricode):
            return None, "美盤主客隊與平台相反"
    return None, "美盤找不到這場"


# ---------------------------------------------------------------- evaluation


def evaluate_game(game: BoardGame, gc: GameConsensus | None, ctx: PassContext,
                  missing_note: str | None = None) -> list[Decision]:
    decisions = []
    for market in game.markets:
        for side, laying in _sides(market):
            decisions.append(_evaluate(game, market, side, laying, gc, ctx, missing_note))
    return decisions


def _evaluate(game: BoardGame, market: Market, side: str, laying: bool, gc: GameConsensus | None,
              ctx: PassContext, missing_note: str | None) -> Decision:
    cfg = ctx.cfg
    d = Decision(game, market.kind, side, laying, market.prices.get(side),
                 market.prices.get(_other(side)), market.line,
                 flags=list(ctx.flags.get(game.label, [])))

    # G0
    if cfg.get("mode") == "paused":
        d.fail("NB-PAUSED")
    if not market.offered:
        d.fail("NB-NOT-OFFERED")
        return d

    # G1
    if market.unresolved:
        d.fail("NB-FORMAT", "抄盤有未確認的欄位")
    if market.line is not None:
        status = notation_status(market.line, cfg)
        if status == "UNREADABLE" or market.line.kind is LineKind.BARE:
            d.fail("NB-FORMAT", f"盤口「{market.line.raw}」無法確認寫法")
        elif status != "CONFIRMED":
            d.fail("NB-SETTLEMENT", f"「{market.line.raw}」結算規則未確認")
    if "NB-FORMAT" in d.codes:
        return d

    # G3
    skew = timedelta(minutes=cfg.get("snapshots.snapshot_max_skew_min"))
    if ctx.platform_ts is None:
        d.fail("NB-STALE", "截圖時間不明")
    elif ctx.us_ts is not None and abs(ctx.platform_ts - ctx.us_ts) > skew:
        minutes = abs(ctx.platform_ts - ctx.us_ts).total_seconds() / 60
        d.fail("NB-STALE", f"平台截圖與美盤快照相差 {minutes:.0f} 分鐘")
    if any(ts is not None and ts >= game.tip for ts in (ctx.platform_ts, ctx.us_ts, ctx.analysis_ts)):
        d.fail("NB-STALE", "已開賽或快照晚於開賽")
    report_age = timedelta(minutes=cfg.get("snapshots.injury_report_max_age_min"))
    if ctx.injury_report_ts is not None and ctx.analysis_ts - ctx.injury_report_ts > report_age:
        d.fail("NB-STALE", "傷病報告過舊")

    # G4
    us_market, giver = US_MARKET[market.kind], _giver(market)
    ref = None
    if gc is None:
        d.fail("NB-DATA", missing_note or "美盤找不到這場")
    else:
        d.l_ref = gc.l_ref(us_market) if us_market != "h2h" else None
        ref = gc.line(us_market, d.l_ref)
        d.n_books = ref.n_books if ref else 0
        if ref is None or ref.n_books < cfg.get("anchor.consensus_min_books"):
            d.fail("NB-DATA", f"美盤主盤只有 {d.n_books} 家（需 {cfg.get('anchor.consensus_min_books')}）")
    if market.kind in ("handicap", "moneyline"):
        conflict = moneyline_conflict(game)
        if conflict:
            d.fail("NB-DATA", "平台獨贏熱門與讓分方向矛盾")
    if ref is None:
        return d

    # G5
    _fair_line(d, market, us_market, giver, gc, ctx)
    if market.kind != "moneyline" and d.fair_line is not None and market.line is not None:
        gap = abs(market.line.effective - d.fair_line)
        explained = bool(ctx.lag and ctx.lag(game, market.kind))
        if gap > cfg.get(f"tiers.sanity_gap.{_scale(market)}") and not explained:
            d.fail("NB-SANITY", f"平台盤口與美盤公平線差 {gap:.1f} 分")
        if market.kind == "handicap" and d.l_ref:
            us_favourite = "home" if d.l_ref < 0 else "away"
            if us_favourite != market.giver and abs(d.l_ref) >= cfg.get("tiers.direction_check_min_pts"):
                d.fail("NB-SANITY", "平台讓分方向與美盤熱門相反")

    # G6 and pricing
    reason = _price(d, market, us_market, giver, gc, ref, ctx)
    if d.tier is None:
        d.fail("NB-TIER-C", reason or ("需要換算，分布尚未驗證" if _tier_b(ctx, us_market) is None
                                      else "換算距離超出範圍"))

    # G7
    eligible = ctx.final_eligible.get(game.label) if ctx.final_eligible is not None else None
    if not eligible:
        d.fail("NB-STATUS", "當日傷病報告或裁判名單未確認")
    if ctx.blocking is None:
        d.fail("NB-STATUS", "拿不到傷病報告")
    elif ctx.blocking.get(game.label):
        d.fail("NB-STATUS", "關鍵球員出賽未定：" + "、".join(ctx.blocking[game.label]))

    if d.priced:
        _gate_edge(d, cfg)
        _veto(d, market, ctx)
        _label_and_confidence(d, market, ctx)
    return d


def _tier_b(ctx: PassContext, us_market: str):
    """The distribution provider, only while cfg:distribution.status is VALIDATED and only
    for the markets VALIDATION.md validated (RULES R-6.4)."""
    if ctx.tier_b is None or ctx.cfg.get("distribution.status") != "VALIDATED":
        return None
    if us_market not in (ctx.cfg.get("distribution.validated_markets") or ()):
        return None
    return ctx.tier_b


def _fair_line(d: Decision, market: Market, us_market: str, giver: str, gc: GameConsensus,
               ctx: PassContext) -> None:
    if us_market == "h2h":
        return
    display = ctx.cfg.get("anchor.devig_display_method")
    tb = _tier_b(ctx, us_market)
    if tb is not None:
        ref = gc.line(us_market, d.l_ref)
        try:
            anchored, _ = tb.anchored(us_market, d.l_ref, ref.probs[display])
        except ValueError:                  # the family has no history near this line
            anchored = None
        if anchored is not None:
            d.fair_line, d.fair_source = _to_giving(us_market, giver, anchored.fair_point()), "distribution"
            return
    home_value = -d.l_ref if us_market == "spreads" else d.l_ref
    d.fair_line, d.fair_source = _to_giving(us_market, giver, home_value), "l_ref"


def _price(d: Decision, market: Market, us_market: str, giver: str, gc: GameConsensus, ref,
           ctx: PassContext) -> str | None:
    """Price the ticket at Tier A or B; returns why not when it cannot translate."""
    cfg = ctx.cfg
    methods = tuple(cfg.get("anchor.devig_methods"))
    legs = market.line.legs if market.line is not None else (Leg(0.5, 1.0),)
    points = needed_points(legs)
    min_a = cfg.get("tiers.tier_a_min_books")
    direct = {m: gc.cover(us_market, giver, m, min_a) for m in methods}
    sigma_books: dict[str, float] = {}
    sigma_translate = 0.0
    if all(direct[methods[0]](x) is not None for x in points):
        d.tier, covers = "A", direct
        for m in methods:
            sigma_books[m] = max(gc.line_for_point(us_market, giver, x)[0].sigma_books(m) for x in points)
    else:
        tb = _tier_b(ctx, us_market)
        if tb is None or us_market == "h2h":
            return None
        ref_giving = _to_giving(us_market, giver, -d.l_ref if us_market == "spreads" else d.l_ref)
        if max(abs(leg.line - ref_giving) for leg in legs) > cfg.get(f"tiers.tier_b_max_gap.{_scale(market)}"):
            return None
        d.tier, covers = "B", {}
        ref_point = -d.l_ref if us_market == "spreads" else d.l_ref
        for m in methods:
            try:
                anchored, alternative = tb.anchored(us_market, d.l_ref, ref.probs[m])
            except ValueError:              # the family has no history near this line
                d.tier = None
                return "換算失敗：分布對不上美盤機率"
            covers[m] = _giving_cover(us_market, giver, anchored.cover)
            sigma_books[m] = ref.sigma_books(m)
            for x in points:
                x_home = -x if (us_market == "spreads" and giver == "away") else x
                sigma_translate = max(sigma_translate,
                                      tb.sigma_translate(anchored, alternative, ref_point, x_home))
    outcomes = {}
    for m in methods:
        try:
            outcomes[m] = ticket_outcomes(legs, d.price, covers[m], d.laying)
        except ValueError:
            d.tier = None
            d.fail("NB-DATA", "美盤各條線互相矛盾")
            return
        d.ev[m] = expected_value(outcomes[m])
        d.p_eff[m] = effective_win_probability(outcomes[m])
        d.masses[m] = {"win": sum(o.prob * o.win for o in outcomes[m]),
                       "loss": sum(o.prob * o.loss for o in outcomes[m])}
        d.masses[m]["push"] = 1.0 - d.masses[m]["win"] - d.masses[m]["loss"]
    d.worst_method = min(methods, key=lambda m: d.ev[m])
    w = d.worst_method
    sigma_method = (max(d.p_eff.values()) - min(d.p_eff.values())) / 2
    sigma_p = math.sqrt(sigma_method ** 2 + sigma_books[w] ** 2 + sigma_translate ** 2)
    d.sigma = {"method": sigma_method, "books": sigma_books[w], "translate": sigma_translate,
               "p": sigma_p, "ev": (1 + d.price) * sigma_p}
    decimals = [hk_to_decimal(d.price), hk_to_decimal(d.other_price)]
    d.platform_novig = max(devig(decimals, m)[0] for m in methods)
    d.kelly = kelly_fraction(outcomes[w])
    if d.tier == "A":
        d.agreement = _agreement(d, legs, us_market, giver, gc, covers[w], w)


def _agreement(d: Decision, legs, us_market: str, giver: str, gc: GameConsensus,
               consensus_cover, method: str) -> float | None:
    """Share of books whose own price, swapped in for the consensus at the
    point(s) they quote, still leaves EV > 0 (MLB gate 2B)."""
    own: dict[str, dict[float, float]] = defaultdict(dict)
    for x in needed_points(legs):
        for book, p in gc.book_covers(us_market, giver, method, x).items():
            own[book][x] = p
    if not own:
        return None
    agree = 0
    for book, quoted in own.items():
        cover = lambda x, q=quoted: q.get(x, consensus_cover(x))       # noqa: E731
        try:
            agree += expected_value(ticket_outcomes(legs, d.price, cover, d.laying)) > 0
        except ValueError:
            pass
    return agree / len(own)


def _gate_edge(d: Decision, cfg) -> None:
    ev = d.ev_worst
    if ev < cfg.get("gates.min_ev"):
        d.fail("NB-EV", f"EV {ev * 100:+.1f}%（門檻 +{cfg.get('gates.min_ev') * 100:.0f}%）")
    elif d.ev_lower(cfg.get("gates.ev_noise_z")) < 0:
        d.fail("NB-EV", "扣掉雜訊後 EV 不為正")
    if d.tier == "A" and d.agreement is not None and d.agreement < cfg.get("gates.tier_a_book_agreement_min"):
        d.fail("NB-EV", f"只有 {d.agreement:.0%} 書商同意")
    if d.divergence < cfg.get("gates.min_divergence_pp") / 100:
        d.fail("NB-DIVERGENCE", f"差距 {d.divergence * 100:+.1f}pp")


def _veto(d: Decision, market: Market, ctx: PassContext) -> None:
    if ctx.model is None:
        return
    view = ctx.model(d.game)
    if not view:
        return
    cfg = ctx.cfg
    if market.kind == "total":
        x = market.line.effective
        d.model_d = (view["total"] - x) if d.laying else (x - view["total"])
    else:
        margin = view["home_margin"]
        if market.kind == "moneyline":
            d.model_d = margin if d.side == "home" else -margin
        else:
            giver_margin = margin if market.giver == "home" else -margin
            x = market.line.effective
            d.model_d = (giver_margin - x) if d.laying else (x - giver_margin)
    scale = _scale(market)
    if d.model_d < -cfg.get(f"model.model_veto_pts.{scale}"):
        d.fail("NB-MODEL-VETO", f"模型偏向另一邊 {-d.model_d:.1f} 分")
    elif d.model_d < -cfg.get(f"model.model_downgrade_pts.{scale}"):
        d.downgrade = True


def _label_and_confidence(d: Decision, market: Market, ctx: PassContext) -> None:
    cfg = ctx.cfg
    if ctx.lag and ctx.lag(d.game, market.kind):
        d.edge_label = "LAG"
    elif ctx.bias and ctx.bias(d):
        d.edge_label = "BIAS"
    elif (market.kind != "moneyline" and d.fair_line is not None and market.line is not None
          and abs(market.line.effective - d.fair_line) <= cfg.get(f"tiers.rounding_max_pts.{_scale(market)}")):
        d.edge_label = "ROUNDING"
    else:
        d.edge_label = "UNEXPLAINED"

    level = 2
    material = context.material(d.flags, cfg)
    medium = (d.tier == "B" or ctx.ts_source == "received" or ctx.model is None
              or d.sigma["ev"] > cfg.get("confidence.sigma_ev_medium") or len(material) >= 1)
    low = (d.edge_label == "UNEXPLAINED" or d.sigma["ev"] > cfg.get("confidence.sigma_ev_low")
           or len(material) >= cfg.get("confidence.material_flags_low"))
    if medium:
        level = min(level, 1)
    if low:
        level = min(level, 0)
    if d.downgrade:
        level = max(level - 1, 0)
    d.confidence = LEVELS[level]


# ------------------------------------------------------- worst acceptable line


def notation_for(effective: float) -> PlatformLine | None:
    """Board notation for an effective line on the 0.005 grid (XX in steps of 1)."""
    e = round(effective * 200) / 200
    if e < 0:
        return None
    n = round(e)
    if abs(e - n) < 1e-9:
        return parse_line(f"{n}平")
    if abs(abs(e - n) - 0.5) < 1e-9:
        return parse_line(f"{math.floor(e)}.5")
    share = 2 * (n - e)                       # N - s/2 = e
    return parse_line(f"{n}{'+' if share > 0 else '-'}{round(abs(share) * 100):02d}")


def _passes(d: Decision, market: Market, gc: GameConsensus, ctx: PassContext) -> bool:
    probe = Decision(d.game, d.market, d.side, d.laying, d.price, d.other_price, market.line,
                     l_ref=d.l_ref)
    ref = gc.line(US_MARKET[d.market], d.l_ref)
    _price(probe, market, US_MARKET[d.market], _giver(market), gc, ref, ctx)
    if probe.tier is None or probe.codes:
        return False
    _gate_edge(probe, ctx.cfg)
    return not probe.codes


def worst_acceptable(d: Decision, gc: GameConsensus, ctx: PassContext,
                     step: float = 0.025, reach: float = 3.0) -> str | None:
    """The worst platform line (or 獨贏 price) at which G8 and G9 still pass
    (RULES R-16.2). Lines move in tail steps of 5 (0.025 points), prices in
    steps of 0.01; the search stops where the ticket can no longer be priced."""
    market = {"handicap": d.game.handicap, "total": d.game.total, "moneyline": d.game.moneyline}[d.market]
    if d.market == "moneyline":
        best, price = None, d.price
        while price > 0.01:
            probe = Decision(d.game, d.market, d.side, d.laying, round(price, 2), d.other_price, None,
                             l_ref=d.l_ref)
            _price(probe, market, "h2h", "home", gc, gc.line("h2h", None), ctx)
            if probe.tier is None:
                break
            _gate_edge(probe, ctx.cfg)
            if probe.codes:
                break
            best, price = round(price, 2), price - 0.01
        return f"獨贏不低於 {best:.2f}" if best is not None else None
    direction = 1.0 if d.laying else -1.0     # a higher line is worse for the side laying it
    best = None
    for i in range(int(reach / step) + 1):
        line = notation_for(d.line.effective + direction * i * step)
        if line is None:
            break
        candidate = Market(market.kind, market.prices, line, market.giver)
        if not _passes(d, candidate, gc, ctx):
            break
        best = line
    if best is None:
        return None
    text = best.raw
    if d.market == "total":
        return f"{'大' if d.laying else '小'} {text}"
    return f"{'讓' if d.laying else '受讓'} {text}"


# ---------------------------------------------------------------- allocation


def allocate(decisions: list[Decision], cfg, exposure_used: float = 0.0) -> None:
    """G11 and G12: one side market per game, then caps in order of EV lower bound."""
    z = cfg.get("gates.ev_noise_z")
    bankroll = cfg.get("risk.bankroll")
    live = [d for d in decisions if not d.codes and d.priced]

    by_game: dict[str, list[Decision]] = defaultdict(list)
    for d in live:
        if d.market in ("handicap", "moneyline"):
            by_game[d.game.label].append(d)
    for ds in by_game.values():
        keep = max(ds, key=lambda d: d.ev_lower(z))
        for d in ds:
            if d is not keep:
                d.fail("NB-CORR", "同場只保留讓分或獨贏其一")

    daily_cap = cfg.get("risk.daily_cap_pct") * bankroll
    remaining_day = daily_cap - exposure_used
    game_cap = cfg.get("risk.per_game_cap_pct") * bankroll
    used_game: dict[str, float] = defaultdict(float)
    increment, minimum = cfg.get("platform.stake_increment"), cfg.get("platform.min_stake")
    stake_allowed = cfg.status("risk.bankroll") == "CONFIRMED"
    for d in sorted((d for d in live if not d.codes), key=lambda d: -d.ev_lower(z)):
        room = min(remaining_day, game_cap - used_game[d.game.label])
        raw = cfg.get("risk.kelly_fraction") * d.kelly * bankroll
        stake = math.floor(min(raw, cfg.get("risk.max_bet_pct") * bankroll, room) / increment) * increment
        if stake < minimum:
            # A cap counts as exhausted only when earlier bets used it up.
            used = remaining_day < daily_cap or used_game[d.game.label] > 0
            if room < minimum and used:
                d.fail("NB-CAP", "單日或單場上限已滿")
            else:
                d.fail("NB-MIN-STAKE", f"注額 {stake:,.0f}（凱利 {raw:,.0f}）低於最低注額 {minimum:,.0f}")
            continue
        if stake_allowed:
            d.stake = float(stake)
            remaining_day -= stake
            used_game[d.game.label] += stake
