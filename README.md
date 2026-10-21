# Bethero NBA

Prices an Asian platform's NBA lines against the US no-vig consensus and decides, market by market, whether a bet exists. It does not try to out-predict the market. The rules are in [`rules/nba/RULES.md`](rules/nba/RULES.md) and override this code; every threshold is in [`rules/nba/config.yaml`](rules/nba/config.yaml) with its status and source. Errors in Claude's own outputs are in [`ERRATA.md`](ERRATA.md).

The default mode is **shadow**: stakes are computed and logged but are not to be placed until Eric says go live.

## Setup (Windows PowerShell)

```powershell
git clone https://github.com/GizzyJeans/NBA-bet.git
cd NBA-bet
py -m venv .venv
.venv\Scripts\Activate.ps1
py -m pip install -e .[dev]
py -m pytest
$env:ODDS_API_KEY = "<your key>"      # never committed, never printed
```

`tzdata` is installed as a dependency because Windows has no time-zone database for `zoneinfo`.

## Daily flow

1. **Board.** Eric sends a screenshot (keep the phone's clock visible). Claude transcribes it to `data/boards/<US slate date>/<platform time>.json` and commits it before the first tip; the commit time is the evidence of pricing time.
2. **Injuries.** Until the official report can be fetched (official.nba.com is blocked from the cloud environment), Claude transcribes it to JSON (format below). Without it every game stops at `NB-STATUS`.
3. **Analyze.**
   ```powershell
   py -m bethero_nba.analyze --board data\boards\2026-11-02\20261103T071000+0800.json --live --injuries data\injuries\2026-11-02.json
   ```
   `--live` pulls one US snapshot (3 credits; the budget guard refuses pulls past `us_odds.max_calls_per_day` or into the reserve). Use `--odds <stored .json.gz>` to re-run on a stored snapshot. Output: the Traditional Chinese report in `reports/<slate>/`, and one hash-chained ledger row per market side in `logs/ledger.jsonl`.
4. **Settle** after the games, with a scores pull and, if available, a US close and Eric's last pre-tip screenshot:
   ```powershell
   py -m bethero_nba.fetch scores --live
   py -m bethero_nba.settle --slate 2026-11-02 --scores data\raw\api.the-odds-api.com\<file>.json.gz --close-odds <close .json.gz> --close-board <board.json>
   ```
   Settlement rows record the shadow P&L, `CLV_US`, `CLV_line`, and whether the board was committed before tip. The pause rule (RULES R-14.7) is re-checked on every run.

Other commands: `py -m bethero_nba.fetch odds --live`, `py -m bethero_nba.fetch participants --live`, `py -m bethero_nba.fetch show <stored .json.gz>`, `py -m bethero_nba.validate --history <games.csv> --holdout 2024-25,2025-26 --out rules\nba\VALIDATION.md`.

Nothing reaches the network without `--live` (RULES R-4.7). Raw Odds API responses stay in `data/raw/` and are not committed: the API's terms forbid redistributing its data and this repository is public.

## Board file

```json
{
  "schema": "bethero-nba-board/1",
  "slate_et": "2026-10-21",
  "platform_ts": "2026-10-22T06:40:00+08:00",
  "ts_source": "screenshot_clock",
  "source": "Eric's screenshot",
  "games": [
    {
      "tip": "2026-10-22T07:05:00+08:00", "home": "WAS", "away": "MIL",
      "handicap": {"text": "5+50", "row": "home", "price_home": 0.95, "price_away": 0.95},
      "total": {"text": "大238.5", "price_over": 0.94, "price_under": 0.94},
      "moneyline": {"price_home": 0.56, "price_away": 1.4},
      "unresolved": []
    }
  ]
}
```

- `ts_source`: `screenshot_clock` (phone clock visible), `received` (time the screenshot arrived), or `unknown` (then `platform_ts` is null and every market is `NB-STALE`).
- `row`: which team's row shows the handicap number, i.e. who lays it. `home` is the `[主]` team.
- Prices are Hong Kong odds; `"-"` means not offered.
- `unresolved`: any field not read with certainty, e.g. `"total.text"`; that market is not priced.

## Injury transcription

```json
{
  "report_time": "2026-11-02T13:00:00-05:00",
  "referees_posted_at": "2026-11-02T09:00:00-05:00",
  "submissions": {"BOS": "2026-11-02T12:05:00-05:00", "NYK": "2026-11-02T12:10:00-05:00"},
  "back_to_back_second": [],
  "statuses": [{"team": "NYK", "player": "Brunson, Jalen", "status": "Questionable", "reason": "Ankle"}],
  "minutes": {"NYK": {"Brunson, Jalen": [35, 36, 34]}, "BOS": {}}
}
```

`submissions` is when each team's game-day status first appeared; `minutes` holds recent minutes per player and decides who is a key player (RULES R-9.3). Leave `minutes` out and the status gate cannot pass.

## Current limits

- Tier B (lines the US market does not quote exactly) stays off until the margin and total distributions are validated on historical closing lines (`distribution.status`), and that history is not reachable yet.
- Region `us` returns about 9 books; the most-quoted line often has fewer than `anchor.consensus_min_books` (8).
- The veto model is built but `OFF` until Phase 3 evaluates it; possession-based ratings need box scores from nba.com.
