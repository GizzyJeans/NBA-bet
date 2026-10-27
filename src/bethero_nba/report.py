"""Traditional Chinese report, mobile-first (RULES §16).

Header, a bets table of exactly seven columns with one detail line per bet,
every game's EV by market and side (R-16.5), a no-bet table with one row per
evaluated market, what would change each recommendation (including markets
held only by listed players, R-16.6), and a transcription check that repeats
every board line as read.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

from .edge import CODES, ORDER, Decision
from .platform import Board, BoardGame

TAIPEI = ZoneInfo("Asia/Taipei")
MARKET_ZH = {"handicap": "讓分", "total": "大小", "moneyline": "獨贏"}
LEVEL_ZH = {"High": "高", "Medium": "中", "Low": "低"}
TS_SOURCE_ZH = {"screenshot_clock": "手機時間", "received": "收到時間", "unknown": "時間不明"}
# short tags for a market stopped by something other than its EV (R-16.5)
STOP_TAG = {"NB-SCOPE": "範圍", "NB-PAUSED": "暫停", "NB-FORMAT": "寫法", "NB-SETTLEMENT": "結算",
            "NB-STALE": "過時", "NB-DATA": "家數", "NB-SANITY": "差距", "NB-TIER-C": "換算",
            "NB-STATUS": "傷病", "NB-MODEL-VETO": "模型", "NB-CORR": "同場", "NB-CAP": "上限",
            "NB-MIN-STAKE": "最低"}


@dataclass
class ReportMeta:
    board: Board
    analysis_ts: datetime
    us_ts: datetime | None
    injury_report_ts: datetime | None
    mode: str
    bankroll: float
    daily_cap: float
    exposure_used: float
    key_rule: tuple[int, float] | None = None     # R-9.3: (window games, minimum average minutes)


def _hm(moment: datetime | None) -> str:
    return moment.astimezone(TAIPEI).strftime("%H:%M") if moment else "—"


def _game_label(game: BoardGame) -> str:
    return f"{game.away.zh}@{game.home.zh}"


def _platform_cell(d: Decision) -> str:
    text = d.line.raw.lstrip("大小") if d.line else "獨贏"
    return f"{text} / {d.price:g}"


def _pct(x: float | None, signed: bool = False) -> str:
    if x is None:
        return "—"
    return f"{x * 100:+.1f}%" if signed else f"{x * 100:.1f}%"


def _detail(d: Decision) -> str:
    tier = f"Tier {d.tier}"
    if d.tier == "B" and d.l_ref is not None:
        tier += f"（美盤 {d.l_ref:+g} 換算）"
    flags = "、".join(d.flags) if d.flags else "無"
    return (f"- {_game_label(d.game)}：{tier}｜{d.edge_label or '—'}｜情境：{flags}"
            f"｜最差可接受：{d.worst_line or '—'}")


def _ev(d: Decision | None) -> str:
    if d is None or d.ev_worst is None:
        return "—"
    text = f"{d.ev_worst * 100:+.1f}".replace("-", "−")
    return f"★{text}" if d.is_bet else text


def _ev_cell(sides: list[Decision]) -> str:
    """Both sides of one market: EV in %, the better side's noise, and why it stopped."""
    if not sides or all(d.primary == "NB-NOT-OFFERED" for d in sides):
        return "未開"
    best = max(sides, key=lambda o: (o.is_bet, o.ev_worst is not None, o.ev_worst or -9))
    by_side = {d.side: d for d in sides}

    def part(label: str, d: Decision | None) -> str:
        noise = (f" (±{d.sigma['ev'] * 100:.1f})" if d is best and d.ev_worst is not None
                 and d.sigma.get("ev") is not None else "")
        return f"{label} {_ev(d)}{noise}"

    game, market = sides[0].game, sides[0].market
    if market == "handicap":
        giver = next((d for d in sides if d.laying), sides[0])
        laying = game.home if giver.side == "home" else game.away
        taking = game.away if giver.side == "home" else game.home
        raw = giver.line.raw if giver.line else "—"
        cell = (f"{part(f'{laying.zh}讓 {raw}', giver)} ／ "
                f"{part(taking.zh, by_side.get('away' if giver.side == 'home' else 'home'))}")
    elif market == "total":
        raw = sides[0].line.raw.lstrip("大小") if sides[0].line else "—"
        cell = f"{raw}：{part('大', by_side.get('over'))} ／ {part('小', by_side.get('under'))}"
    else:
        cell = f"{part(game.home.zh, by_side.get('home'))} ／ {part(game.away.zh, by_side.get('away'))}"
    tag = None if best.is_bet else STOP_TAG.get(best.primary or "")
    return cell + (f"〔{tag}〕" if tag else "")


def _us_cell(decisions: list[Decision]) -> str:
    """The US consensus main lines the pass compared against."""
    parts = []
    spread = next((d for d in decisions if d.market == "handicap" and d.l_ref is not None), None)
    total = next((d for d in decisions if d.market == "total" and d.l_ref is not None), None)
    if spread is not None:
        if spread.l_ref == 0:
            parts.append("pk")
        else:
            favourite = spread.game.home if spread.l_ref < 0 else spread.game.away
            parts.append(f"{favourite.zh}讓 {abs(spread.l_ref):g}")
    if total is not None:
        parts.append(f"{total.l_ref:g}")
    return "、".join(parts) or "—"


def _ev_table(decisions: list[Decision]) -> list[str]:
    """R-16.5: every game, every market, both sides (Eric 2026-10-27: 以後每天都列出各場ev)."""
    lines = ["## 各場 EV",
             "每 1 元注碼的期望值（%），取三種去水方法中最差者；括號是較佳一側的雜訊；★ 是合格影子注；〔〕是擋下原因。",
             "", "| 比賽 | 讓分 | 大小 | 獨贏 | 美盤主盤 |", "|---|---|---|---|---|"]
    labels = list(dict.fromkeys(d.game.label for d in decisions))
    for label in labels:
        ds = [d for d in decisions if d.game.label == label]
        cells = [_ev_cell([d for d in ds if d.market == m]) for m in ("handicap", "total", "moneyline")]
        lines.append(f"| {_game_label(ds[0].game)} | {' | '.join(cells)} | {_us_cell(ds)} |")
    return lines


def _no_bet_rows(decisions: list[Decision]) -> list[tuple[Decision, str]]:
    """One row per evaluated market: the side closest to a bet, with its primary code."""
    rows = []
    seen = set()
    for d in decisions:
        key = (d.game.label, d.market)
        if key in seen or any(o.is_bet for o in decisions if (o.game.label, o.market) == key):
            continue
        seen.add(key)
        sides = [o for o in decisions if (o.game.label, o.market) == key]
        best = max(sides, key=lambda o: (o.ev_worst is not None, o.ev_worst or -9))
        rows.append((best, best.primary or "—"))
    return rows


def _explain(d: Decision) -> str:
    code = d.primary
    if d.notes:
        return d.notes[0] if code != "NB-EV" or d.ev_worst is None else f"EV {_pct(d.ev_worst, True)}"
    return CODES.get(code, "")


def _held_lines(decisions: list[Decision], key_rule: tuple[int, float] | None) -> list[str]:
    """R-16.6: markets that pass every other gate and are held only by listed key
    players, one line per game, with what Eric can send to settle it."""
    by_game: dict[str, list[Decision]] = {}
    for d in decisions:
        if d.codes == ["NB-STATUS"] and d.held_by:
            by_game.setdefault(d.game.label, []).append(d)
    lines = []
    for ds in by_game.values():
        players = ds[0].held_by
        who, every = ("他", "") if len(players) == 1 else ("他們", "都")
        bench = (f"本季近 {key_rule[0]} 場平均上場{every}不到 {key_rule[1]:g} 分鐘" if key_rule
                 else f"{every}是替補")
        markets = "、".join(f"{d.selection()}（EV {_pct(d.ev_worst, True)}）" for d in ds)
        lines.append(f"- 只差傷病：{_game_label(ds[0].game)} {markets}，被 {'、'.join(players)} 擋下。"
                     f"若{who}{bench}，傳{who}本季逐場上場時間的截圖，我重算")
    return lines


def render(decisions: list[Decision], meta: ReportMeta) -> str:
    board = meta.board
    bets = [d for d in decisions if d.is_bet]
    lines = [
        f"# NBA 分析｜美東 {board.slate_et:%m-%d} 賽程",
        f"模式：{'影子（注額只記錄，不實際下注）' if meta.mode == 'shadow' else meta.mode}",
        (f"美盤快照 {_hm(meta.us_ts)}｜平台截圖 {_hm(board.platform_ts)}"
         f"（{TS_SOURCE_ZH[board.ts_source]}）｜傷病報告 {_hm(meta.injury_report_ts)}｜"
         f"報告 {_hm(meta.analysis_ts)}（台北）"),
        (f"本金 {meta.bankroll:,.0f}｜今日已用 {meta.exposure_used + sum(d.stake for d in bets):,.0f}"
         f" / {meta.daily_cap:,.0f}"),
    ]
    waived = [d for d in decisions if d.waivers]
    if waived:
        lines.append(f"⚠ 傷病關卡依 Eric 指示放行（{len(waived)} 個選項）；這些影子注不計入上線條件")
    cleared = {d.game.label: (d.game, d.cleared) for d in decisions if d.cleared}
    if cleared:
        lines.append("替補放行（上場時間來自截圖）：" + "；".join(
            f"{_game_label(game)} {'、'.join(players)}" for game, players in cleared.values()))
    lines += [
        "",
        "## 建議",
    ]
    if bets:
        lines += ["| 比賽 | 選項 | 平台盤/賠率 | 公平機率 | EV(±) | 注額 | 信心 |",
                  "|---|---|---|---|---|---|---|"]
        for d in bets:
            lines.append(
                f"| {_game_label(d.game)} {_hm(d.game.tip)} | {d.selection()} | {_platform_cell(d)} "
                f"| {_pct(d.p_worst)} | {_pct(d.ev_worst, True)} (±{d.sigma['ev'] * 100:.1f}) "
                f"| {d.stake:,.0f} | {LEVEL_ZH[d.confidence]} |")
        lines.append("")
        lines += [_detail(d) for d in bets]
    else:
        lines.append("今天沒有合格的注。")
    lines += [""] + _ev_table(decisions)
    lines += ["", "## 不下注", "| 比賽 | 市場 | 代碼 | 說明 |", "|---|---|---|---|"]
    for d, code in _no_bet_rows(decisions):
        lines.append(f"| {_game_label(d.game)} | {MARKET_ZH[d.market]} | {code} | {_explain(d)} |")
    lines += ["", "## 什麼會改變建議"]
    lines += _held_lines(decisions, meta.key_rule)
    if bets:
        for d in bets:
            worse = f"平台盤口比「{d.worst_line}」更差 → 取消；" if d.worst_line else ""
            lines.append(f"- {_game_label(d.game)}：{worse}關鍵球員狀態改變 → 重跑")
    else:
        blocking = Counter(code for d in decisions for code in set(d.codes) if code != "NB-NOT-OFFERED")
        if blocking:
            lines.append("每一項都至少擋住一個市場（括號內為市場數）：")
            lines += [f"- {code}：{CODES[code]}（{n}）"
                      for code, n in sorted(blocking.items(), key=lambda kv: ORDER[kv[0]])]
        else:
            lines.append("- 平台今天沒有開出可分析的盤")
    lines += ["", "## 抄盤核對"]
    for game in board.games:
        h, t, ml = game.handicap, game.total, game.moneyline
        giver = game.home if h.giver == "home" else game.away
        ml_text = (f"{ml.prices['home']:g} / {ml.prices['away']:g}" if ml.offered else "-")
        lines.append(
            f"- {_game_label(game)}[主 {game.home.tricode}]：讓 {giver.zh} {h.line.raw if h.line else '-'}"
            f" / {h.prices['home'] if h.prices['home'] is not None else '-'}｜大小 "
            f"{t.line.raw.lstrip('大小') if t.line else '-'} / {t.prices['over'] if t.prices['over'] is not None else '-'}"
            f"｜獨贏 {ml_text}")
    return "\n".join(lines) + "\n"
