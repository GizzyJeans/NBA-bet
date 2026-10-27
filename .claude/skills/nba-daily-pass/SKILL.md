---
name: nba-daily-pass
description: Run one NBA slate end to end. Use when Eric sends a platform screenshot, an official injury report PDF or a referee-assignments screenshot, or asks to analyze, close or settle a slate. Covers transcribing the board, committing it before tip, the analysis pass, the close pull and settlement.
---

# NBA daily pass

Follow `CLAUDE.md` invariants throughout. The mode is shadow: every stake is a 影子注額 and is never presented as a bet to place.

## 1. Transcribe the board

Eric's screenshot is the only platform source (RULES §1, item 7).

- **Slate.** `slate_et` is the US Eastern date of the games. Tips on the board are Taipei times: subtract 12 hours until 2026-11-01, and 13 hours from 2026-11-02 to 2027-03-13.
- **`platform_ts`.**
  - If the phone clock is visible, use it, with `ts_source: screenshot_clock`.
  - Otherwise use the time the image arrived, with `received`.
  - If neither is known, use `unknown` and `null`; every market then becomes `NB-STALE`.
- **Each game.**
  - Map Chinese names to tricodes with `src/bethero_nba/teams.py`; `[主]` is home.
  - `handicap.row` is the team whose row shows the number.
  - Copy notation exactly as shown (`2.5`, `5平`, `5+50`, `大238.5`), and write prices as shown, in Hong Kong odds. `-` means not offered.
- **Anything not read with certainty goes into `unresolved`** (e.g. `"handicap.text"`). Never guess a digit and never flip a row to match the US market (R-6.6).
- **Save the file.** Write it to `data/boards/<slate_et>/<platform_ts as YYYYMMDDTHHMMSS+0800>.json` in the README format. Show Eric the 抄盤核對 lines from the report so he can catch misreads.
- **Commit and push the board before the first tip it covers** (R-14.2).

## 2. Injury report and referees

- **The report.** Eric saves the official PDF in his browser; never fetch NBA hosts.
  - Check it first with `python -m bethero_nba.injuries <pdf>`.
  - It must be at most `snapshots.injury_report_max_age_min` old at analysis time.
  - Game-day statuses count only from a report published at or after 1 p.m. local on game day (R-4.5).
- **Referees.** The time on Eric's referee-assignments screenshot becomes `--referees-posted-at` (ISO-8601, `+08:00`). Without it every game stops at `NB-STATUS`; tell Eric.
- **If `read_pdf` raises `ReportFormatError`.** The layout changed: stop, tell Eric, and do not hand-patch the reading. A JSON transcription (README) is the fallback.

## 3. Analysis pass

```powershell
py -m bethero_nba.analyze --board <board.json> --live --injury-pdf <pdf> --referees-posted-at <ISO time>
```

- **`--live` costs 6 credits.** The budget guard allows `us_odds.max_calls_per_day` odds pulls per UTC day and keeps a reserve. If it refuses, report that; never bypass it.
- **`--exposure-used`** is shadow stake already logged today on this slate.
- **Reply to Eric in 繁體中文** from the generated report (`reports/<slate>/`):
  - qualifying shadow bets with EV ± σ, stake and worst acceptable line;
  - then the report's 各場 EV table, every game and both sides of each market (R-16.5; Eric 2026-10-27: 「以後每天都列出各場ev」);
  - then each no-bet with its code;
  - then what would change the decision.

  Do not add opinions, trends or narratives (RULES §1).
- **Commit** the ledger rows and the report.

## 4. Close and settle

- **Close.** Near the main tip window, run `py -m bethero_nba.fetch odds --live`; it uses the day's second pull. Ask Eric for a last pre-tip screenshot if he can take one.
- **Settle within 3 days**, because the scores endpoint only reaches back 3 days:

  ```powershell
  py -m bethero_nba.fetch scores --live --days-from 3
  py -m bethero_nba.settle --slate <slate_et> --scores <scores .json.gz> --close-odds <close .json.gz> --close-board <last board>
  ```

  - Raw snapshots live only in `data/raw/` on the machine that pulled them. If the close snapshot is gone, CLV is N/A and is never imputed (R-14.3).
  - Relay `settle`'s pause line and go-live readiness line.
  - If the pause rule fires (R-14.7), set `mode: paused` through the `nba-rule-change` skill and tell Eric.
  - Readiness never switches the mode; only Eric's go-live message does (R-12.7).
