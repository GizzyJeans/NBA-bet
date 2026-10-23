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

## 1. Summary (2026-10-23)

Written after the results below; it restates them and changes no criterion. R-numbers refer to the generated sections.

- **Dataset (R1, R2).** 21,691 regular-season games, 2007-08 to 2025-26, from a public GitHub dataset with no licence file, used on this machine only. The source does not say when its lines were taken. Holdout 2023-24 and 2024-25 (N = 2,441); training 2014-15 to 2022-23 without 2020-21 (N = 9,400).
- **Distributions (R3).** The discretized normal beats the kernel-smoothed empirical family on holdout log loss for both markets, so `selected_method` is normal for both.
  - Spreads: V3 holds from -2.0 to +1.5 and fails at +2.0, beyond the 1.5 gap. V4 residual SD is 13.55.
  - Totals: V3 holds at every offset (largest error 0.6 pp). V4 residual SD is 17.54.
  - Both markets are validated and both gaps keep their Phase 1 values (spread 1.5, total 2.0). Tier B is on for both.
- **What to keep in mind about the spread normal.**
  - Its cover prediction for the side laying points is 0.2 to 2.2 pp too high at all nine offsets.
  - Part of the cause is that it spreads the tied-regulation mass over all margins, while overtime games end close. A check run after the results moved that mass to margins ±1 to ±5 instead: it removed about 1 pp of the error and lowered log loss from 0.75262 to 0.75247. It decides nothing. It is a candidate for a later version, which would need its own validation.
  - Anchoring to the consensus removes the error shared by all offsets. What is left is at most 1.25 pp on holdout (R4, "What anchoring leaves").
  - It was fitted when games were less spread out: sigma 12.55 on training against 13.55 on holdout. V3 still passes because the offsets are small.
  - In the first 551 games of 2025-26 (descriptive only), laying sides covered 4.7 to 6.5 pp less than the normal predicted at every offset. The part anchoring leaves was at most 0.9 pp.
- **De-vig (R5).** Shin has the lowest holdout log loss (0.57959). Power (0.57972) and multiplicative (0.57993) are within one standard error, and over all seasons multiplicative is lowest. The display method stays shin; gating stays worst-case.
- **Model (R6).** k = 5, the edge of the declared grid.
  - On holdout the model is 3.43 points from the closing spread and 4.50 from the closing total on average.
  - Its home-win Brier score is 0.2151, against the market's 0.1985.
  - It is a poorer forecaster than the market, as expected, which is why it may only veto.
  - Veto at 5.4 (spread) and 7.0 (total) points of disagreement; downgrade at 3.5 and 4.5. `model.status` stays OFF until Eric decides.

## 2. What cannot be backtested

Stated plainly: nothing below has any historical test. Each item is measured only prospectively, in shadow mode (§3).

1. **The platform itself.** There are no historical platform lines: the record starts with Eric's screenshot of 2026-10-21. So there is no history of:
   - how often the platform hangs a line the US market makes a +EV bet;
   - realised ROI or CLV on platform tickets;
   - the platform's lag, bias and rounding (RULES §11);
   - stake sizing over time.

   Every EV in a report rests on P1, that the US no-vig consensus is the fair price.
2. **Tail-line settlement.** The `N+XX` / `N-XX` rule comes from Eric's statement and his worked case (WAS `5+50`). It has not been checked against settled tickets.
3. **The injury gate (G7).** There are no historical injury-report statuses, so how often G7 blocks, and whether it blocks the right games, is unknown.
4. **The consensus.** The history has one line per game from one source, not a multi-book snapshot: historical Odds API snapshots are paid. These were all validated only by construction, never on history:
   - the median-of-books consensus;
   - `consensus_min_books` and `tier_a_min_books`;
   - the quote-age rule and σ_books.
5. **Line timing.** The dataset does not say when its lines were taken, while live passes use a snapshot taken when Eric's screenshot arrives. The distribution's shape is assumed to carry over between the two. §1 shows the shape is the stable part, but this is an assumption.
6. **Translation in production.** V3 checks each family at the closing line plus an offset. Tier B instead anchors the family to the consensus at `L_ref` and reads the needed points off it. The anchored error is estimated above from the same games but has not been checked against prices the US market later quoted at those points.
7. **The model as a veto.** Its thresholds come from holdout, but whether its vetoes remove losing bets can only be seen in CLV of vetoed against non-vetoed candidates (RULES R-14.6).
8. **Everything after the 2026-27 rule changes.** This covers the lottery reform (RULES R-7.6), and any rule or style change that moves scoring variance. Variance has already risen: the spread residual SD was 12.55 on the training seasons and 13.55 on holdout.

## 3. Shadow mode (proposal; Eric decides when to go live)

`cfg:mode` is `shadow` and stays so until Eric's explicit go-live message (RULES R-12.7). Stakes are computed and logged as 影子注額, never placed.

**Daily procedure.**

1. Eric sends a screenshot with the phone clock visible. It should be taken after the day's official injury report and referee assignments are out (RULES R-4.5).
2. Claude transcribes it to `data/boards/<slate>/` and commits it before the first tip (R-14.2).
3. The injury report enters as Eric's official PDF or a transcription. Without it every market stops at `NB-STATUS`, and is still logged with all its other gate results.
4. `analyze --live` makes one US pull (6 credits).
5. A second pull near the main tip window gives the US close (6 credits), plus Eric's last pre-tip screenshot if he has one.
6. `settle` runs the next day with a scores pull.

The budget guard allows two odds pulls per UTC day and keeps 50 credits in reserve; 410 credits were left on 2026-10-23.

**Measured** (declared here, before any shadow data):

- **SM1** (primary) Mean `CLV_US` of shadow bets, with a date-block bootstrap CI (`cfg:clv.pause_ci`).
- **SM2** Mean `CLV_line` where a platform close exists.
- **SM3** Translation check. For each Tier B ticket whose needed points the US close quotes with at least `tier_a_min_books` books, the translated probability minus the quoted one, with N.
- **SM4** Gate counts per market, by primary code. Also the share of markets whose only failure is `NB-STATUS`: the bets the injury report would decide.
- **SM5** The bias monitor (RULES §11) with its unchanged USABLE rule.
- **SM6** Realised shadow P&L, reported, never deciding (R-14.8).

**Go-live, proposed.** Each condition is Eric's to accept or change.

1. At least `cfg:clv.pause_min_n` (30) shadow bets with `CLV_US`, over at least 20 slate days.
2. Mean `CLV_US` above 0, with its CI excluding 0. This is the stricter of two candidates; the looser one only asks that the pause rule never fired. Flagged for Eric's choice.
3. Every one of those bets is `prospective`: the board was committed before tip.
4. No open ERRATA item affecting a stake; tests green; every market used is validated.
5. Eric's explicit go-live message.

**Going live does not change:**

- the pause rule (R-14.7), which still applies;
- the model, which stays OFF unless Eric turns it on separately;
- the caps of 1% per bet, 5% per day and 1% per game.

**How often a bet will appear is unknown** (§2.1). At the platform's 0.95 price a ticket needs a fair cover probability of 1.04 / 1.95 = 53.3% for EV ≥ 4%. Near the middle of the spread distribution (sigma about 13.5) that takes a platform line roughly one point better than the US fair line. On the 2026-10-21 sample every priced market had negative EV.

<!-- Everything below is generated by `python -m bethero_nba.validate` and replaced on every run. The criteria above are not. -->

## Results (2026-10-23)

Every line below was produced by `python -m bethero_nba.validate` from the history file described in R1. **The source does not say whether its lines are closing lines; read every "closing" below as "the source's line, timing not stated" (D1).**

### R1 Dataset (D1-D5)

- Source: [kyleskom/NBA-Machine-Learning-Sports-Betting](https://github.com/kyleskom/NBA-Machine-Learning-Sports-Betting) at commit `8e36b0b` (2026-01-08), file `Data/OddsData.sqlite`, SHA-256 `4a803d41cd4597c1d898c0b131a58763dee8b64140be8f40c29b73c852e162d9`. Licence: none stated in the repository; used locally only, game rows not committed (D5).
- Converted by `python -m bethero_nba.history` at 2026-10-23T10:17:17+00:00.
- Lines: 2007-08 to 2021-22 from the sportsbookreviewsonline archive (per the dataset's notes; book not stated); 2022-23 onward from the SBR scoreboard via sbrscrape (script default FanDuel; book not recorded per row).
- Rules applied: D2 |spread| <= 30, total in 150-300, each team score in 50-200, no tied final; D3 regular season ends on the last date with at least 10 games; moneyline: both prices, bookmaker margin 0%-15%; otherwise the moneyline columns are left empty; spread side: signed tables: home line = -away spread; unsigned tables: the moneyline favourite lays the points, and without a usable moneyline the game is dropped; contradictions: dropped when the moneyline favours the other side, when a side lays 4+ points with a favourite below 55%, or when a pick'em has a favourite above 60%.

| season | table | raw | kept | last regular day | complete | dropped |
|---|---|---|---|---|---|---|
| 2007-08 | `odds_2007-08_new` | 1316 | 1202 | 2008-04-16 | yes | after regular season (D3) 86; spread side unresolved 21; moneyline contradicts spread 7 |
| 2008-09 | `odds_2008-09_new` | 1315 | 1210 | 2009-04-15 | yes | after regular season (D3) 85; spread side unresolved 13; moneyline contradicts spread 7 |
| 2009-10 | `odds_2009-10_new` | 1312 | 1220 | 2010-04-14 | yes | after regular season (D3) 82; spread side unresolved 3; moneyline contradicts spread 7 |
| 2010-11 | `odds_2010-11_new` | 1311 | 1220 | 2011-04-13 | yes | after regular season (D3) 81; line out of range (D2) 3; spread side unresolved 4; moneyline contradicts spread 3 |
| 2011-12 | `odds_2011-12_new` | 1074 | 983 | 2012-04-26 | yes | after regular season (D3) 84; spread side unresolved 2; moneyline contradicts spread 5 |
| 2012-13 | `odds_2012-13_new` | 1314 | 1217 | 2013-04-17 | yes | after regular season (D3) 85; impossible score 1; line out of range (D2) 1; spread side unresolved 8; moneyline contradicts spread 2 |
| 2013-14 | `odds_2013-14_new` | 1319 | 1215 | 2014-04-16 | yes | after regular season (D3) 89; spread side unresolved 9; moneyline contradicts spread 6 |
| 2014-15 | `odds_2014-15_new` | 1311 | 1212 | 2015-04-15 | yes | after regular season (D3) 81; line out of range (D2) 1; spread side unresolved 4; moneyline contradicts spread 13 |
| 2015-16 | `odds_2015-16_new` | 1316 | 1213 | 2016-04-13 | yes | after regular season (D3) 86; spread side unresolved 10; moneyline contradicts spread 7 |
| 2016-17 | `odds_2016-17_new` | 1309 | 1198 | 2017-04-12 | yes | after regular season (D3) 79; impossible score 1; line out of range (D2) 1; spread side unresolved 16; moneyline contradicts spread 14 |
| 2017-18 | `odds_2017-18_new` | 1312 | 1216 | 2018-04-11 | yes | after regular season (D3) 82; spread side unresolved 9; moneyline contradicts spread 5 |
| 2018-19 | `odds_2018-19_new` | 1312 | 1207 | 2019-04-10 | yes | after regular season (D3) 82; spread side unresolved 12; moneyline contradicts spread 11 |
| 2019-20 | `odds_2019-20_new` | 1143 | 936 | 2020-03-08 | no | after regular season (D3) 188; line out of range (D2) 2; spread side unresolved 16; moneyline contradicts spread 1 |
| 2020-21 | `odds_2020-21_new` | 1171 | 1031 | 2021-05-16 | yes | after regular season (D3) 91; line out of range (D2) 4; spread side unresolved 17; moneyline contradicts spread 28 |
| 2021-22 | `odds_2021-22_new` | 1323 | 1191 | 2022-04-10 | yes | after regular season (D3) 93; line out of range (D2) 4; spread side unresolved 16; moneyline contradicts spread 19 |
| 2022-23 | `odds_2022-23_new` | 1319 | 1227 | 2023-04-09 | yes | after regular season (D3) 90; missing score 1; moneyline contradicts spread 1 |
| 2023-24 | `2023-24` | 1255 | 1213 | 2024-04-14 | yes | after regular season (D3) 36; moneyline contradicts spread 6 |
| 2024-25 | `2024-25` | 1326 | 1228 | 2025-04-13 | yes | after regular season (D3) 90; missing score 5; moneyline contradicts spread 3 |
| 2025-26 | `odds_2025-26` | 554 | 552 | 2026-01-07 | no | moneyline contradicts spread 2 |

D4 excluded 1031 games (2019-20 from 2020-07-30: 0; 2020-21: 1031). D3 had already cut the 2019-20 regular season at its last 10-game date before the suspension.

### R2 Seasons (S1)

- Training: 2014-15 to 2022-23 (8 seasons), N = 9400 games.
- Holdout: 2023-24, 2024-25, N = 2441 games.
- Sensitivity training (decides nothing): 2007-08 to 2022-23 (15 seasons), N = 17667.
- After the holdout (descriptive only, §0.7 A2): 2025-26, N = 552.

### R3 Spreads (home margin)

Training N = 9400; holdout N = 2441, of which 2441 have training history within reach (§0.7 A3) and are scored.

**V1 bandwidth** (leave one training season out, mean log loss over O):

| bandwidth | N scored | log loss |
|---|---|---|
| 0.5 | 9400 | 0.75487 |
| 1 | 9400 | 0.75224 |
| 1.5 | 9400 | 0.75185 |
| 2 | 9400 | 0.75180 |
| 3 | 9400 | 0.75188 |

Chosen: **2**.

**V2 families on holdout** (mean log loss over O; lower is better): empirical 0.75512, normal 0.75262 (normal fitted on training: mean residual -0.08, sigma 12.55). Outcomes given probability below 1e-12: empirical 0, normal 0. Selected: **normal**.

**V3 calibration of the normal family** (cover = the laying side or the over wins outright; tolerance 1.96 x sqrt(p(1-p)/N)):

| offset | N | predicted cover | observed cover | difference | tolerance | V3 | predicted push | observed push |
|---|---|---|---|---|---|---|---|---|
| -2.0 | 2441 | 0.5684 | 0.5629 | -0.0055 | 0.0196 | pass | 0.0125 | 0.0156 |
| -1.5 | 2441 | 0.5513 | 0.5481 | -0.0032 | 0.0197 | pass | 0.0171 | 0.0147 |
| -1.0 | 2441 | 0.5387 | 0.5367 | -0.0020 | 0.0198 | pass | 0.0126 | 0.0115 |
| -0.5 | 2441 | 0.5201 | 0.5125 | -0.0076 | 0.0198 | pass | 0.0186 | 0.0242 |
| +0.0 | 2441 | 0.5062 | 0.4965 | -0.0097 | 0.0198 | pass | 0.0139 | 0.0160 |
| +0.5 | 2441 | 0.4874 | 0.4728 | -0.0147 | 0.0198 | pass | 0.0188 | 0.0238 |
| +1.0 | 2441 | 0.4736 | 0.4588 | -0.0148 | 0.0198 | pass | 0.0138 | 0.0139 |
| +1.5 | 2441 | 0.4550 | 0.4400 | -0.0150 | 0.0198 | pass | 0.0186 | 0.0188 |
| +2.0 | 2441 | 0.4413 | 0.4191 | -0.0222 | 0.0197 | FAIL | 0.0137 | 0.0209 |

For comparison, the empirical family would fail V3 at: no offset.

**V4 residual SD on holdout**: 13.55 (mean -0.10); band 10-15: pass.

**Gap**: placeholder 1.5; V3 holds up to 1.5. **Validated**; `tiers.tier_b_max_gap.spread` = 1.5.

Calibration by line bucket (descriptive, decides nothing; max |observed - predicted| over O, and the tolerance at p = 0.5 for that N):

| line | N | log loss empirical | log loss normal | max dev. empirical | max dev. normal | tolerance |
|---|---|---|---|---|---|---|
| 0-2.5 | 447 | 0.73996 | 0.73816 | 0.0283 | 0.0100 | 0.0464 |
| 3-5.5 | 703 | 0.75666 | 0.75493 | 0.0521 | 0.0390 | 0.0370 |
| 6-8.5 | 572 | 0.75980 | 0.76036 | 0.0192 | 0.0325 | 0.0410 |
| 9-11.5 | 383 | 0.75858 | 0.75302 | 0.0647 | 0.0351 | 0.0501 |
| 12+ | 336 | 0.76015 | 0.75338 | 0.0324 | 0.0423 | 0.0535 |

### R3 Totals

Training N = 9400; holdout N = 2441, of which 2438 have training history within reach (§0.7 A3) and are scored.

**V1 bandwidth** (leave one training season out, mean log loss over O):

| bandwidth | N scored | log loss |
|---|---|---|
| 0.5 | 9397 | 0.75428 |
| 1 | 9397 | 0.74688 |
| 1.5 | 9397 | 0.74165 |
| 2 | 9397 | 0.74035 |
| 3 | 9397 | 0.73984 |

Chosen: **3**.

**V2 families on holdout** (mean log loss over O; lower is better): empirical 0.75169, normal 0.73466 (normal fitted on training: mean residual +0.48, sigma 18.19). Outcomes given probability below 1e-12: empirical 10, normal 0. Selected: **normal**.

**V3 calibration of the normal family** (cover = the laying side or the over wins outright; tolerance 1.96 x sqrt(p(1-p)/N)):

| offset | N | predicted cover | observed cover | difference | tolerance | V3 | predicted push | observed push |
|---|---|---|---|---|---|---|---|---|
| -2.0 | 2438 | 0.5498 | 0.5513 | +0.0014 | 0.0197 | pass | 0.0088 | 0.0049 |
| -1.5 | 2438 | 0.5369 | 0.5394 | +0.0025 | 0.0198 | pass | 0.0130 | 0.0119 |
| -1.0 | 2438 | 0.5280 | 0.5324 | +0.0044 | 0.0198 | pass | 0.0088 | 0.0070 |
| -0.5 | 2438 | 0.5150 | 0.5172 | +0.0022 | 0.0198 | pass | 0.0130 | 0.0152 |
| +0.0 | 2438 | 0.5061 | 0.5070 | +0.0009 | 0.0198 | pass | 0.0089 | 0.0103 |
| +0.5 | 2438 | 0.4931 | 0.4988 | +0.0057 | 0.0198 | pass | 0.0131 | 0.0082 |
| +1.0 | 2438 | 0.4842 | 0.4897 | +0.0055 | 0.0198 | pass | 0.0089 | 0.0090 |
| +1.5 | 2438 | 0.4712 | 0.4729 | +0.0018 | 0.0198 | pass | 0.0130 | 0.0168 |
| +2.0 | 2438 | 0.4623 | 0.4619 | -0.0005 | 0.0198 | pass | 0.0088 | 0.0111 |

For comparison, the empirical family would fail V3 at: -2.0, -1.5, -1.0, -0.5, +0.0, +0.5, +1.0, +1.5, +2.0.

**V4 residual SD on holdout**: 17.54 (mean +0.56); band 15-23: pass.

**Gap**: placeholder 2; V3 holds up to 2. **Validated**; `tiers.tier_b_max_gap.total` = 2.

Calibration by line bucket (descriptive, decides nothing; max |observed - predicted| over O, and the tolerance at p = 0.5 for that N):

| line | N | log loss empirical | log loss normal | max dev. empirical | max dev. normal | tolerance |
|---|---|---|---|---|---|---|
| <215 | 213 | 0.74755 | 0.74863 | 0.0292 | 0.0448 | 0.0671 |
| 215-224.5 | 768 | 0.73303 | 0.73217 | 0.0222 | 0.0157 | 0.0354 |
| 225-234.5 | 901 | 0.73587 | 0.73527 | 0.0175 | 0.0105 | 0.0326 |
| 235+ | 556 | 0.80470 | 0.73177 | 0.0770 | 0.0112 | 0.0416 |

### R4 Sensitivity and later seasons (decide nothing)

| market | training | N train | bandwidth | log loss empirical | log loss normal | selected | V3 holds up to |
|---|---|---|---|---|---|---|---|
| spreads | 2007-08 to 2022-23 (15 seasons) | 17667 | 3 | 0.75397 | 0.75252 | normal | 1.5 |
| totals | 2007-08 to 2022-23 (15 seasons) | 17667 | 3 | 0.75273 | 0.73469 | normal | 2 |

Training-season families scored on the seasons after the holdout:

| market | N | log loss empirical | log loss normal | max dev. empirical | max dev. normal | tolerance at p = 0.5 |
|---|---|---|---|---|---|---|
| spreads | 551 | 0.75316 | 0.74953 | 0.0591 | 0.0648 | 0.0417 |
| totals | 552 | 0.74551 | 0.73052 | 0.0185 | 0.0271 | 0.0417 |

**What anchoring leaves** (added after the first run; decides nothing). Tier B pins a family to the consensus at the reference line, which removes an error common to every offset; what is left is the deviation at each offset minus the deviation at offset 0.

| market | seasons | N | family | deviation at 0 | max deviation relative to 0 |
|---|---|---|---|---|---|
| spreads | holdout | 2441 | empirical | -0.0029 | 0.0047 |
| spreads | holdout | 2441 | normal | -0.0097 | 0.0125 |
| spreads | 2025-26 | 551 | empirical | -0.0487 | 0.0108 |
| spreads | 2025-26 | 551 | normal | -0.0561 | 0.0091 |
| totals | holdout | 2438 | empirical | +0.0239 | 0.0051 |
| totals | holdout | 2438 | normal | +0.0009 | 0.0048 |
| totals | 2025-26 | 552 | empirical | +0.0128 | 0.0098 |
| totals | 2025-26 | 552 | normal | -0.0214 | 0.0056 |

### R5 De-vig methods (DV1)

Home-win probability from the two moneylines against results; overtime decides every game.

| method | holdout N | holdout log loss | holdout Brier | vs lowest (mean, SE) | all seasons N | all log loss | all Brier |
|---|---|---|---|---|---|---|---|
| multiplicative | 2441 | 0.57993 | 0.19821 | +0.00035 (0.00051) | 20660 | 0.58552 | 0.20068 |
| power | 2441 | 0.57972 | 0.19817 | +0.00014 (0.00036) | 20660 | 0.58618 | 0.20086 |
| shin | 2441 | 0.57959 | 0.19813 | +0.00000 (0.00000) | 20660 | 0.58573 | 0.20075 |

Lowest holdout log loss: **shin** (becomes `anchor.devig_display_method`; gating stays worst-case).

### R6 Veto model (M1-M3)

**M1 shrinkage k** (training seasons, walk-forward, MAE of the model's home margin against the closing spread):

| k | N | MAE spread |
|---|---|---|
| 5 | 9125 | 2.684 |
| 10 | 9125 | 2.707 |
| 20 | 9125 | 2.979 |
| 40 | 9125 | 3.473 |

Chosen: **k = 5**.

**M2 holdout by phase** (k = 5; market = the closing moneyline de-vigged with shin):

| phase | N | MAE vs closing spread | MAE vs closing total | Brier model | Brier market | log loss model | log loss market |
|---|---|---|---|---|---|---|---|
| games 1-20 | 550 | 3.73 | 3.90 | 0.2210 | 0.2058 | 0.6341 | 0.5966 |
| middle | 1257 | 3.10 | 4.15 | 0.2169 | 0.2012 | 0.6198 | 0.5862 |
| last 20 | 564 | 3.89 | 5.88 | 0.2051 | 0.1853 | 0.5972 | 0.5510 |
| all | 2371 | 3.43 | 4.50 | 0.2151 | 0.1985 | 0.6178 | 0.5802 |

Against results (MAE in points):

| phase | N | margin: model | margin: closing spread | total: model | total: closing total |
|---|---|---|---|---|---|
| games 1-20 | 550 | 10.56 | 10.06 | 15.19 | 14.42 |
| middle | 1257 | 11.41 | 10.78 | 14.94 | 13.94 |
| last 20 | 564 | 11.44 | 10.57 | 14.74 | 14.02 |
| all | 2371 | 11.22 | 10.56 | 14.95 | 14.07 |

The trade-deadline split of R-8.6 is not evaluated: the dataset has no deadline dates.

**M3** on holdout (N = 2371): |model - closing| 80th percentile spread 5.42, total 7.09; 60th percentile spread 3.56, total 4.54. Rounded down to 0.1 (§0.7 A8). `model.status` stays OFF.

### R7 Values the pre-declared rules give

| key | value | rule |
|---|---|---|
| `distribution.train_seasons` | 2014-15, 2015-16, 2016-17, 2017-18, 2018-19, 2019-20, 2021-22, 2022-23 | S1 |
| `distribution.holdout_seasons` | 2023-24, 2024-25 | S1 |
| `distribution.smoothing_bandwidth` | spread 2, total 3 | V1 |
| `distribution.selected_method` | spread normal, total normal | V2 |
| `distribution.validated_markets` | spreads, totals | V3, V4 |
| `distribution.status` | VALIDATED | Status |
| `tiers.tier_b_max_gap.spread` | 1.5 | Gap |
| `tiers.tier_b_max_gap.total` | 2 | Gap |
| `anchor.devig_display_method` | shin | DV1 |
| `model.prior_shrinkage_k_games` | 5 | M1 |
| `model.model_veto_pts` | spread 5.4, total 7 | M3 |
| `model.model_downgrade_pts` | spread 3.5, total 4.5 | M3 |
| `model.status` | OFF | M3: Eric decides |
