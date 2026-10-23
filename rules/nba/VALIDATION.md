# Validation

Phase 3 of the NBA rulebook (RULES §7, R-5.3, R-8.6). This file starts with the criteria, declared and committed **before any historical data was loaded**; results are appended below them and may not change them (RULES R-17.3, MLB `docs/prospective_test.md` convention).

## 0. Pre-declared criteria (2026-10-23)

### 0.1 Dataset

- **D1 Provenance.** Source, version or commit, retrieval date, SHA-256 of every file, and the book(s) behind the lines if the source says. A dataset whose lines are not closing lines is used only with that stated in every result.
- **D2 Row checks.** A row needs a date, both teams, final scores (overtime included), a spread and a total. Rows with |spread| > 30, a total outside 150–300, or a missing score are dropped and counted per season.
- **D3 Regular season only.** If the dataset has no playoff flag, a season's regular season ends on the last date with at least 10 games; later games (play-in, playoffs) are dropped.
- **D4 Exclusions.** 2019-20 games from 2020-07-30 (bubble) and the whole 2020-21 season (RULES R-7.3).
- **D5 Not committed.** Raw files and the derived game-level history stay out of the public repository; only aggregate tables (bucket counts) and results are committed.

### 0.2 Seasons

- **S1** Holdout: the two most recent complete regular seasons in the dataset. Training: all earlier usable regular seasons from 2014-15 on. A sensitivity run with every usable season is reported but decides nothing.

### 0.3 Distributions (RULES R-7.4)

Offsets O = {−2.0, −1.5, −1.0, −0.5, 0, +0.5, +1.0, +1.5, +2.0} points from the closing line, in the laying side's (or the over's) orientation. Each game contributes the win / push / lose outcome of a ticket at the closing line plus each offset.

- **V1 Bandwidth.** Chosen per market by leave-one-season-out cross-validation on the training seasons, minimising mean log loss over O, from {0.5, 1.0, 1.5, 2.0, 3.0} points.
- **V2 Selection.** On holdout, per market, the family (kernel-smoothed empirical or discretized normal) with the lower mean log loss over O becomes `distribution.selected_method`.
- **V3 Calibration.** For the selected family, at each offset, |observed − predicted cover rate| ≤ 1.96 × √(p(1 − p)/N) on holdout, with p the predicted rate and N the holdout games.
- **V4 Bug bands.** Holdout residual SD inside 10–15 (margin) and 15–23 (total). Outside → investigate; the market is not validated.
- **Status.** A market is validated when V3 holds at every offset up to its `tiers.tier_b_max_gap` and V4 holds; it is then listed in `distribution.validated_markets` and `distribution.status` becomes `VALIDATED`. Tier B is used only for validated markets.
- **Gap.** `tiers.tier_b_max_gap` stays at its placeholder (1.5 spread, 2.0 total) if V3 holds up to it; otherwise it drops to the largest offset at which V3 holds there and at every smaller offset. Phase 3 never raises it.

### 0.4 De-vig methods (RULES R-5.3)

- **DV1** If the dataset has closing moneylines for both sides: log loss and Brier of each method's home-win probability against results, on holdout and on all usable seasons. The lowest holdout log loss becomes `anchor.devig_display_method`. Gating stays worst-case. Without moneylines nothing changes.

### 0.5 Model (RULES R-8.6)

- **M1** Walk-forward within each season: refit every 50 games once 30 games exist; the shrinkage k is chosen from {5, 10, 20, 40} by training-season MAE against the closing spread.
- **M2** Report MAE against the closing spread and total, and Brier and log loss of the home-win probability against results, by phase: games 1–20, middle, last 20. The trade-deadline split of R-8.6 needs historical deadline dates the dataset does not carry; it is reported as not evaluated.
- **M3** `model.model_veto_pts` = 80th percentile and `model.model_downgrade_pts` = 60th percentile of |model − closing line| on holdout, per market. `model.status` stays `OFF`; turning it on is Eric's decision after reading M2.

### 0.6 What cannot be backtested

- There are no historical platform lines, so no historical EV, ROI or CLV of platform bets, no platform-bias history, and no test of the tail-line settlement against real tickets.
- There are no historical injury-report statuses, so the status gate (G7) cannot be replayed.
- These are measured only prospectively, in shadow mode (§ Shadow mode below, written with the results).

### 0.7 Addendum (2026-10-23, before any validation statistic was computed)

Written after the dataset was chosen and converted (`python -m bethero_nba.history`) and before `python -m bethero_nba.validate` first ran on it, and committed before that run. What had been seen by then: table sizes, date ranges and value ranges, and, while checking the spread sign, each season's mean and SD of final margin minus line (SD 11.2-13.9). Nothing below depends on those numbers.

- **A1 Dataset rules** (`src/bethero_nba/history.py`).
  - Signed tables (2022-23 on): home line = -(away spread), the convention of the dataset's own scraper. Unsigned tables (2007-08 to 2021-22): the moneyline favourite lays the points. In the signed tables that rule picks the spread favourite in 3,874 of 3,884 games.
  - A moneyline pair is usable when both prices are at least 100 in size and the bookmaker margin is 0-15%; otherwise the moneyline columns stay empty.
  - A game is dropped when the moneyline favours the other side; when a side lays 4+ points against a moneyline favourite below 55%; when a pick'em has a moneyline favourite above 60%; and, in unsigned tables, when no usable moneyline decides the side. In the unsigned tables 0.1-1.3% of games laying 4+ points have a near-even moneyline (2.5-3.5% in 2020-21 and 2021-22), so the moneyline column there is sometimes not a moneyline at all.
  - Under D2, a tied final or a team score outside 50-200 is an impossible score.
  - For 2023-24 the table `2023-24` (1,255 rows) is used, not `odds_2023-24_new` (1,195 rows, a different Clippers name, and four wrong final scores among the games the two share).
  - A repeated game (same date and teams) keeps its first row.
- **A2 Season roles.** S1 gives holdout 2023-24 and 2024-25. 2025-26 stops at 2026-01-07 and is not complete; it is scored descriptively and decides nothing.
- **A3 Support.** A game is scored only if its line has training history within the narrowest kernel's reach (4 x 0.5 = 2 points), so every bandwidth and both families are scored on the same games. The number left out is reported.
- **A4 Orientation.** A pick'em (line 0) is scored from the home side.
- **A5 Gap of zero.** If V3 fails at offset 0, the gap is 0 and the market is not validated: a gap of 0 translates nothing.
- **A6 Walk-forward.** A game is predicted from that season's games on earlier dates only (not from games earlier the same day), with no prior from the previous season. Its phase is that of the team with fewer games played.
- **A7 Production fit.** Tier B uses the families exactly as validated (fitted on the training seasons), saved as aggregate counts in `data/dist/`. Refitting on later seasons would be a separate, separately validated change.
- **A8 Rounding.** M3 thresholds are rounded down to 0.1 point: a lower veto distance blocks more.
- **A9 DV1 "all usable seasons"** is every season in the history file after D4, the partial 2025-26 included. Descriptive only.
- **A10 Context columns.** M2 also reports, on the same games, the closing moneyline's de-vigged home-win probability (DV1 method), and the model's and the closing line's MAE against results. Calibration is also tabulated by line bucket. None of this decides anything.
- **A11 Ties.** V1 takes the lowest log loss, a tie going to the smaller bandwidth; V2 selects the empirical family only if its log loss is strictly lower; M1 takes the lowest MAE, a tie going to the smaller k.
