"""Traditional Chinese report, mobile-first (RULES §16).

Header, a bets table of exactly seven columns with one detail line per bet,
a no-bet table with one row per evaluated market, what would change each
recommendation, and a transcription check that repeats every board line as
read.
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
    lines += ["", "## 不下注", "| 比賽 | 市場 | 代碼 | 說明 |", "|---|---|---|---|"]
    for d, code in _no_bet_rows(decisions):
        lines.append(f"| {_game_label(d.game)} | {MARKET_ZH[d.market]} | {code} | {_explain(d)} |")
    lines += ["", "## 什麼會改變建議"]
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
