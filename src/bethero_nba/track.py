"""Results and CLV of every priced side, by EV threshold (RULES R-14.6, R-14.8).

    python -m bethero_nba.track --live
    python -m bethero_nba.track --box-scores <player_box .csv.gz> <schedule .csv.gz>

Every side the ledger priced counts once: the latest decision for its game, market and
side, across all passes. It is settled on the final score from ESPN's box scores as
sportsdataverse publishes them (CC BY 4.0), for games whose two box scores pass both
checks (R-9.3). CLV_US comes from the last stored US snapshot within the close window
before tip (R-14.3); without one it is N/A, never imputed. The report goes to
reports/tracking/. It decides nothing: a side was a bet only if it carries no code.
"""

from __future__ import annotations

import argparse
import json
import math
from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from . import boxscores, cli, clv, consensus, ledger, net, oddsapi, settle
from .bias import bootstrap
from .teams import team

THRESHOLDS = (1.0, 0.0, -1.0)       # EV above these, in percent (Eric 2026-11-09)
TPE = ZoneInfo("Asia/Taipei")
Z = 1.96


@dataclass
class Side:
    record: dict
    slate: date
    ev: float                       # worst de-vig method, per unit, as the daily report shows it
    p: float                        # effective win probability under that method
    won: float | None = None        # share of the stake that won, once settled
    lost: float | None = None
    ret: float | None = None        # profit per unit staked
    clv_us: float | None = None

    @property
    def settled(self) -> bool:
        return self.ret is not None


def latest_sides(records: list[dict]) -> list[Side]:
    """The latest decision for each game, market and side across passes, if it has an EV."""
    latest: dict[tuple, tuple[dict, str]] = {}
    slate = None
    for r in records:
        if r.get("record_type") == "pass":
            slate = r["slate_et"]
        elif r.get("record_type") == "decision":
            g = r["game"]
            day = oddsapi.eastern_date(datetime.fromisoformat(g["tip"]))
            latest[(g["home"], g["away"], day, r["market"], r["side"])] = (r, slate or day.isoformat())
    return [Side(r, date.fromisoformat(s), r["ev"][r["worst_method"]], r["p_eff"][r["worst_method"]])
            for r, s in latest.values() if r.get("ev")]


def settle_sides(sides: list[Side], finals: dict[tuple[str, str, date], tuple[int, int]]) -> None:
    for s in sides:
        g = s.record["game"]
        score = finals.get((g["home"], g["away"], oddsapi.eastern_date(datetime.fromisoformat(g["tip"]))))
        if score is not None:
            s.won, s.lost, s.ret = settle.result(s.record, *score)


@dataclass
class Snapshot:
    retrieved_at: datetime
    path: Path
    _games: list | None = None

    def games(self) -> list:
        if self._games is None:
            self._games = oddsapi.normalise(net.load_cached(self.path).json())
        return self._games


def stored_snapshots(raw_dir: Path) -> list[Snapshot]:
    """The US odds pulls kept in data/raw on this machine, oldest first."""
    out = []
    for meta in (raw_dir / "api.the-odds-api.com").glob("*.meta.json"):
        m = json.loads(meta.read_text(encoding="utf-8"))
        body = meta.with_name(meta.name.removesuffix(".meta.json") + ".json.gz")
        if m.get("status") == 200 and urlsplit(m["url"]).path.rstrip("/").endswith("/odds") and body.exists():
            out.append(Snapshot(datetime.fromisoformat(m["retrieved_at"]), body))
    return sorted(out, key=lambda s: s.retrieved_at)


def add_clv(sides: list[Side], snapshots: list[Snapshot], cfg) -> None:
    """CLV_US from the US close: the last snapshot within the window before tip (R-14.3, R-14.5)."""
    window = cfg.get("snapshots.close_snapshot_window_min")
    methods = tuple(cfg.get("anchor.devig_methods"))
    for s in sides:
        r = s.record
        tip = datetime.fromisoformat(r["game"]["tip"])
        for snap in reversed(snapshots):
            if not tip - timedelta(minutes=window) <= snap.retrieved_at < tip:
                continue
            game = next((g for g in snap.games() if team(g.home_team).tricode == r["game"]["home"]
                         and team(g.away_team).tricode == r["game"]["away"]), None)
            if game is None or not settle.close_in_window(snap.retrieved_at, (tip, game.commence_time), window):
                continue
            gc = consensus.build(game, snap.retrieved_at, methods=methods,
                                 max_age_min=cfg.get("anchor.us_quote_max_age_min"))
            legs = settle._legs(r)
            s.clv_us = clv.clv_us(legs, r["platform"]["price"], r["laying"], settle.close_cover(gc, r, legs, cfg),
                                  None)[0]
            break


@dataclass(frozen=True)
class Summary:
    n: int
    won: float
    lost: float
    pushed: float
    hit: float | None
    hit_low: float | None
    hit_high: float | None
    predicted: float
    roi: float | None
    roi_low: float | None
    roi_high: float | None
    ev: float
    days: int
    clv_n: int
    clv: float | None
    clv_low: float | None
    clv_high: float | None


def wilson(k: float, n: float, z: float = Z) -> tuple[float, float]:
    centre = (k / n + z * z / (2 * n)) / (1 + z * z / n)
    half = z * math.sqrt(k / n * (1 - k / n) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return centre - half, centre + half


def _by_day(sides: list[Side], value) -> dict[date, list[float]]:
    out: dict[date, list[float]] = {}
    for s in sides:
        if value(s) is not None:
            out.setdefault(s.slate, []).append(value(s))
    return out


def summarize(sides: list[Side], cfg) -> Summary | None:
    """Settled sides only. Win rate = W / (W + L) with a Wilson interval; the mean return
    and CLV_US carry a date-block bootstrap interval (RULES R-14.6, cfg:bias.bootstrap)."""
    done = [s for s in sides if s.settled]
    if not done:
        return None
    won, lost = sum(s.won for s in done), sum(s.lost for s in done)
    boot = cfg.get("bias.bootstrap")

    def interval(by_day):
        if not by_day:
            return None, None, None
        return bootstrap(by_day, resamples=boot["resamples"], ci=boot["ci"])

    roi = interval(_by_day(done, lambda s: s.ret))
    clv_days = _by_day(done, lambda s: s.clv_us)
    clv_mean = interval(clv_days)
    hit = (won / (won + lost), *wilson(won, won + lost)) if won + lost else (None, None, None)
    return Summary(len(done), won, lost, len(done) - won - lost, *hit,
                   sum(s.p for s in done) / len(done), *roi, sum(s.ev for s in done) / len(done),
                   len({s.slate for s in done}), sum(len(v) for v in clv_days.values()), *clv_mean)


def _pct(x: float | None, sign: bool = False) -> str:
    if x is None:
        return "—"
    return (f"{x * 100:+.1f}%" if sign else f"{x * 100:.1f}%").replace("-", "−")


def _range(x, low, high, sign=False) -> str:
    if x is None:
        return "—"
    return f"{_pct(x, sign)}（{_pct(low, sign)}～{_pct(high, sign)}）"


def _row(label: str, s: Summary | None) -> str:
    if s is None:
        return f"| {label} | 0 | — | — | — | — | — | 0 | — |"
    return (f"| {label} | {s.n} | {s.won:g}–{s.lost:g}–{s.pushed:g} | {_range(s.hit, s.hit_low, s.hit_high)} | "
            f"{_pct(s.predicted)} | {_range(s.roi, s.roi_low, s.roi_high, True)} | {_pct(s.ev, True)} | "
            f"{s.clv_n} | {_range(s.clv, s.clv_low, s.clv_high, True)} |")


HEADER = ("| 門檻 | 盤口數 | 贏–輸–走 | 勝率（95% 範圍） | 模型預測 | 實際報酬（95% 範圍） | 預測 EV | CLV 樣本 "
          "| 平均 CLV_US（95% 範圍） |\n|---|---|---|---|---|---|---|---|---|")


def _label(t: float) -> str:
    return (f"EV > {t:+g}%" if t else "EV > 0%").replace("-", "−")


def _describe(s: Side) -> str:
    r = s.record
    tri = r["game"]["home"] if r["side"] == "home" else r["game"]["away"]
    if r["market"] == "handicap":
        return f"{team(tri).zh}{'讓' if r['laying'] else '受讓'} {r['platform']['text']}"
    if r["market"] == "total":
        return f"{'大' if r['side'] == 'over' else '小'} {r['platform']['text'].lstrip('大')}"
    return f"{team(tri).zh} 獨贏"


def _result(s: Side) -> str:
    if not s.settled:
        return "未結算"
    if s.won == 1:
        return "贏"
    if s.lost == 1:
        return "輸"
    if s.won == 0 and s.lost == 0:
        return "走"
    return "贏半" if s.won > s.lost else "輸半"


def render(sides: list[Side], scores: boxscores.BoxScores, thresholds: list[float], cfg, now: datetime,
           snapshots: int) -> str:
    thresholds = sorted(thresholds, reverse=True)
    done = [s for s in sides if s.settled]
    slates = sorted({s.slate for s in sides})
    span = f"{slates[0]:%m-%d}～{slates[-1]:%m-%d}" if slates else "—"
    boot = cfg.get("bias.bootstrap")
    out = [f"# 追蹤統計｜{span} 賽程",
           f"產生 {now.astimezone(TPE):%Y-%m-%d %H:%M}（台北）｜影子模式；只描述，不改任何規則或門檻", "",
           "## 依 EV 門檻",
           "EV 取三種去水方法中最差者（與每日報告相同）。門檻累加：低門檻包含高門檻的盤口。", "", HEADER]
    out += [_row(_label(t), summarize([s for s in sides if s.ev > t / 100], cfg)) for t in thresholds]
    out.append(_row("全部（參考）", summarize(sides, cfg)))
    low = thresholds[-1]
    out += ["", f"## 分市場（{_label(low)}）", "", HEADER.replace("門檻", "市場", 1)]
    for market, name in (("handicap", "讓分"), ("total", "大小"), ("moneyline", "獨贏")):
        out.append(_row(name, summarize([s for s in sides if s.record["market"] == market and s.ev > low / 100],
                                        cfg)))
    top = thresholds[0]
    listed = sorted((s for s in sides if s.ev > top / 100), key=lambda s: (s.slate, s.record["game"]["tip"]))
    out += ["", f"## {_label(top)} 的盤口", "", "| 賽程 | 比賽 | 盤口 | EV | 結果 | CLV_US |", "|---|---|---|---|---|---|"]
    for s in listed:
        g = s.record["game"]
        out.append(f"| {s.slate:%m/%d} | {team(g['away']).zh}@{team(g['home']).zh} | {_describe(s)} | "
                   f"{_pct(s.ev, True)} | {_result(s)} | {_pct(s.clv_us, True)} |")
    primary = Counter(s.record.get("primary") or "合格影子注" for s in sides)
    tiers = Counter(s.record.get("tier") or "—" for s in sides)
    out += ["", "## 代碼與層級（有 EV 的盤口，各取最後一次分析）", "",
            "- 主要代碼：" + "、".join(f"{c} {n}" for c, n in primary.most_common()),
            "- 層級：" + "、".join(f"{t} {n}" for t, n in sorted(tiers.items())), "",
            "## 說明",
            "- 勝率 = 贏 ÷（贏＋輸），走盤不算；0.5 是 +50、−75 這類盤的贏半或輸半。賠率 0.95 損益兩平要 51.3%。",
            f"- 實際報酬與 CLV 的範圍，是以賽程日為單位重抽 {boot['resamples']} 次的 bootstrap（R-14.6）。",
            f"- CLV_US：開賽前 {cfg.get('snapshots.close_snapshot_window_min'):g} 分鐘內最後一次美盤快照（R-14.3），"
            "用美盤收盤分布重算這張單在平台價格的 EV（R-14.5）。快照只存在當時抓取的那台機器，沒有就是 —，不補估計。",
            "- 只有沒有任何代碼的才是影子注；其餘是「如果下了」的追蹤。偏差監測與否決命中率（R-14.6）尚未納入，模型關閉，沒有否決。",
            "", "## 資料",
            f"- 帳本 logs/ledger.jsonl（雜湊鏈已驗證）：{len(sides)} 個有 EV 的盤口，{len(slates)} 個賽程，"
            f"已結算 {len(done)}，未結算 {len(sides) - len(done)}（比分未出，或該場數據未通過核對）。"]
    for src in scores.sources:
        out.append(f"- 比分：{src['url'].rsplit('/', 1)[-1]}，SHA-256 {src['sha256'][:12]}，"
                   f"{datetime.fromisoformat(src['retrieved_at']).astimezone(TPE):%m-%d %H:%M}（台北）下載。")
    out += [f"- {len(scores.finals)} 場終場比賽兩隊數據都通過核對（得分加總等於比分、上場時間填滿整場）。",
            f"- 美盤快照：本機 data/raw 有 {snapshots} 份；有 CLV_US 的盤口 {sum(s.clv_us is not None for s in done)} 個。",
            "", f"比分：{boxscores.CREDIT.replace('平均由本程式計算', '結算由本程式計算')}"]
    return "\n".join(out) + "\n"


def main(argv: list[str] | None = None) -> int:
    cli.setup_output()
    parser = argparse.ArgumentParser(prog="python -m bethero_nba.track", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    cli.add_root(parser)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--live", action="store_true", help="download the season's box scores now")
    source.add_argument("--box-scores", nargs=2, type=Path, metavar=("BOX", "SCHEDULE"),
                        help="stored box-score and schedule files (.csv.gz)")
    parser.add_argument("--thresholds", nargs="+", type=float, default=list(THRESHOLDS),
                        help="EV thresholds in percent (default: 1 0 -1)")
    parser.add_argument("--now", help="report time (ISO-8601)")
    parser.add_argument("--no-write", action="store_true", help="print only")
    args = parser.parse_args(argv)

    root = cli.resolve_root(args.root)
    cfg = cli.load_config(root)
    records = ledger.verify(root / "logs" / "ledger.jsonl")
    try:
        if args.live:
            scores = boxscores.fetch(net.HttpClient.from_config(cfg, root / "data" / "raw", live=True), cfg)
        else:
            scores = boxscores.load(*args.box_scores, cfg)
    except (OSError, net.FetchError, boxscores.BoxScoreError) as exc:
        print(f"box scores: {exc}")
        return 2
    sides = latest_sides(records)
    settle_sides(sides, scores.finals)
    snapshots = stored_snapshots(root / "data" / "raw")
    add_clv(sides, snapshots, cfg)
    now = datetime.fromisoformat(args.now) if args.now else datetime.now(timezone.utc)
    text = render(sides, scores, args.thresholds, cfg, now, len(snapshots))
    print(text, end="")
    if not args.no_write:
        path = root / "reports" / "tracking" / f"{now.astimezone(timezone.utc):%Y%m%dT%H%M%SZ}.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="\n")
        print(f"report: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
