# Bethero NBA

Prices an Asian platform's NBA lines against the US no-vig consensus and decides, market by market, whether a bet exists. It does not try to out-predict the market. The rules are in [`rules/nba/RULES.md`](rules/nba/RULES.md) and override this code; every threshold is in [`rules/nba/config.yaml`](rules/nba/config.yaml) with its status and source. Errors in Claude's own outputs are in [`ERRATA.md`](ERRATA.md).

Working with Claude Code: [`CLAUDE.md`](CLAUDE.md) holds the invariants. The project skills are `nba-daily-pass` (a slate from screenshot to settlement) and `nba-rule-change` (changing a rule, threshold or validation), in `.claude/skills/`.

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
2. **Injuries.** official.nba.com blocks the cloud environment (Akamai 403), and nothing fetches from NBA hosts automatically. Eric sends two things, saved in his browser:
   - the newest official injury report PDF. It is linked from official.nba.com's "NBA Injury Report" page; last season the page was `/nba-injury-report-2025-26/`. The files are named `https://ak-static.cms.nba.com/referee/injury/Injury-Report_YYYY-MM-DD_hh_mmAM.pdf` (or `PM`), in US Eastern time. In 2025-26 the file names ran in 15-minute steps.
   - a screenshot of official.nba.com/referee-assignments/ showing the day's referees, which are posted about 9 a.m. ET.

   `analyze --injury-pdf` reads the PDF directly, and the referee screenshot's clock goes into `--referees-posted-at`. A JSON transcription (format below) is the fallback. The report may be at most `snapshots.injury_report_max_age_min` (30) minutes old at analysis time. Without a report every game stops at `NB-STATUS`.

   The PDFs stay out of git: they are the NBA's documents and the repository is public. The ledger records each one's SHA-256. To check what a PDF says before a pass, run `py -m bethero_nba.injuries <pdf>`.

   **Minutes.** A player listed Questionable or Doubtful blocks his game unless his minutes show he is not a key player (RULES R-9.3: 10 games played this season, average under 28).
   - `analyze --live` gets them from ESPN's box scores as sportsdataverse publishes them on GitHub (CC BY 4.0). It downloads the season's two files when a listed player needs minutes, and checks every game first; nothing for Eric to do.
   - If a player still has no minutes (his name did not match, or the files were not yet updated), the report's 什麼會改變建議 section has a line starting 只差傷病 that asks for a screenshot. Eric then sends one of the player's game log this season, with the phone clock visible, taken that US Eastern day from 6 a.m. ET on, and not from Basketball-Reference: Sports Reference's terms forbid using its data with AI. Claude transcribes it to `data/minutes/<slate>.json` (format below), commits it, and re-runs with `--minutes`.
3. **Analyze.**
   ```powershell
   py -m bethero_nba.analyze --board data\boards\2026-11-02\20261103T071000+0800.json --live --injury-pdf $env:USERPROFILE\Downloads\Injury-Report_2026-11-02_06_30PM.pdf --referees-posted-at 2026-11-03T06:50:00+08:00
   ```
   `--live` pulls one US snapshot (6 credits with regions `us,us2`; the budget guard refuses pulls past `us_odds.max_calls_per_day` or into the reserve). Use `--odds <stored .json.gz>` to re-run on a stored snapshot, with `--box-scores <player_box .csv.gz> <schedule .csv.gz>` for the stored box scores, and add `--minutes data\minutes\2026-11-02.json` when there is a transcription. Output: the Traditional Chinese report in `reports/<slate>/`, and one hash-chained ledger row per market side in `logs/ledger.jsonl`.
4. **Settle** after the games, with a scores pull and, if available, a US close and Eric's last pre-tip screenshot:
   ```powershell
   py -m bethero_nba.fetch scores --live
   py -m bethero_nba.settle --slate 2026-11-02 --scores data\raw\api.the-odds-api.com\<file>.json.gz --close-odds <close .json.gz> --close-board <board.json>
   ```
   Settlement rows record the shadow P&L, `CLV_US`, `CLV_line`, and whether the board was committed before tip. The pause rule (RULES R-14.7) is re-checked on every run.

Other commands: `py -m bethero_nba.fetch odds --live`, `py -m bethero_nba.fetch participants --live`, `py -m bethero_nba.fetch show <stored .json.gz>`, and `py -m bethero_nba.boxscores --live --slate 2026-11-02 --team NYK --player "Brunson, Jalen"` to check the box scores and one player's minutes.

Nothing reaches the network without `--live` (RULES R-4.7). Raw responses stay in `data/raw/` and are not committed: The Odds API's terms forbid redistributing its data and this repository is public. The box-score files stay there too; reports credit them as their CC BY 4.0 licence asks.

## Historical data and validation

Tier B (translating to lines the US market does not quote) uses the distributions validated in [`rules/nba/VALIDATION.md`](rules/nba/VALIDATION.md). They are stored as aggregate counts in `data/dist/`. To reproduce them:

```powershell
git clone --filter=blob:none --no-checkout https://github.com/kyleskom/NBA-Machine-Learning-Sports-Betting $env:TEMP\kyleskom
git -C $env:TEMP\kyleskom checkout 8e36b0b72ecc5082aa8976dff742cdf910b3aa36 -- Data/OddsData.sqlite
py -m bethero_nba.history --sqlite $env:TEMP\kyleskom\Data\OddsData.sqlite
py -m bethero_nba.validate --history data\history\games.csv --out rules\nba\VALIDATION.md --write-dist data\dist
```

- The dataset has no licence file, so it and the per-game history built from it (`data/history/`, gitignored) stay on your machine.
- `history` refuses any file whose SHA-256 differs from the one its table choices were checked on.
- Keep the clone outside this repository and never run code from it; the adapter only reads the SQLite file, read-only.
- `validate` rewrites only the results below the marker in `VALIDATION.md`; the pre-declared criteria above it are never touched.

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

## Injury transcription (fallback)

```json
{
  "report_time": "2026-11-02T13:00:00-05:00",
  "referees_posted_at": "2026-11-02T09:00:00-05:00",
  "submissions": {"BOS": "2026-11-02T12:05:00-05:00", "NYK": "2026-11-02T12:10:00-05:00"},
  "back_to_back_second": [],
  "statuses": [{"team": "NYK", "player": "Brunson, Jalen", "status": "Questionable", "reason": "Ankle"}],
  "minutes": {"NYK": {"Brunson, Jalen": [35, 36, 34, 33, 37, 35, 36, 34, 38, 35]}, "BOS": {}}
}
```

- `submissions`: when each team's game-day status first appeared. From a single PDF, this is that report's time for every team it shows as submitted.
- `minutes` is optional and works as in the minutes transcription below; `--minutes` adds to it.

## Minutes transcription

`data/minutes/<slate>.json`, from Eric's game-log screenshots (RULES R-9.3):

```json
{
  "schema": "bethero-nba-minutes/1",
  "slate_et": "2026-11-02",
  "seen_at": "2026-11-03T07:05:00+08:00",
  "source": "Eric's screenshot of Hart's game log, phone clock 7:05 (Taipei)",
  "players": {"NYK": {"Hart, Josh": [12, 9, 15, 11, 0.5, 14, 10, 13, 12, 16]}}
}
```

- The fallback for a player the box scores could not cover. It wins for the players it names. Never from a Sports Reference site (RULES Appendix B).
- Names are spelled as the injury report prints them. A name the report does not list on that team is printed as unmatched and recorded in the pass.
- Minutes are his games played this season, oldest first; preseason and games he did not play are left out. With fewer than 10 games he still counts as key.
- `seen_at` is when the screenshot was taken. It counts only if taken on the slate's US Eastern date at or after `injuries.minutes_screenshot_from_et` (06:00 ET) and before the pass; otherwise the pass ignores it and records `used: false`.

## Current limits

- **Shadow mode** until Eric's go-live message. The proposed go-live conditions are in `VALIDATION.md` §3.
- **Tier B** is validated for spreads and totals. A line farther than `tiers.tier_b_max_gap` from the US reference line (1.5 points for spreads, 2.0 for totals) still stops at `NB-TIER-C`.
- **Injury report.** official.nba.com answers this cloud environment with Akamai 403, so the report has to come from Eric: the PDF downloaded in his browser (read by `injuries.read_pdf`), or a transcription (RULES R-9.1). Without the report every market stops at `NB-STATUS`.
- **Player minutes** come from ESPN's box scores via sportsdataverse (RULES R-9.3, Appendix B). No team has played 10 games yet, so every listed player still counts as key; by the schedule, teams reach 10 games between 11-06 and 11-11. API-Sports' free plan, probed on 2026-10-27, serves only three days of games and left players out of 5 of its 10 team box scores.
- **Veto model.** Evaluated in `VALIDATION.md` R6, it is a poorer forecaster than the market and stays `OFF` until Eric decides. It is not a config switch yet. `analyze` runs without a model until this season's results are collected (a scores pull at least every 3 days) and the fit is wired in, and it predicts nothing before 30 games exist. Possession-based ratings need box scores from nba.com.
- **Cannot be backtested.** There are no historical platform lines, so the platform's edge, ROI and CLV are measured only in shadow mode (`VALIDATION.md` §2).
