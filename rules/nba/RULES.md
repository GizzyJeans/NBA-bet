# Bethero NBA Rulebook

**Version 0.1.0 · 2026-10-21 · Phase 1 draft, awaiting Eric's approval**

Config: [`config.yaml`](config.yaml), cited as `cfg:section.key`. Changes: [`CHANGELOG.md`](CHANGELOG.md). Errors in Claude's own outputs: [`ERRATA.md`](../../ERRATA.md).

This file overrides code. If code and this file disagree, the code is wrong and is fixed to match (convention from `cc_npb/AGENT.md`).

## 0. Conventions

### 0.1 Status labels

Every number in this file and in `config.yaml` carries one label.

| Label | Meaning | Allowed effect |
|---|---|---|
| `CONFIRMED` | Stated by Eric, or visible in Eric's platform screenshot; the source names the message date | any |
| `CONFIRM` | Eric's decision; the value shown is the stricter default until he decides | any (policy limit) |
| `VALIDATED` | Evidence `{source, N, date range, method}` recorded in `VALIDATION.md` | any |
| `UNVALIDATED` | Placeholder with a one-line rationale; data decides later | may only make a gate stricter; never the reason a bet exists |
| `UNCONFIRMED` | Platform semantics not yet confirmed | forces `NB-FORMAT` or `NB-SETTLEMENT` |
| `FACT` | External fact; source and access date in Appendix A | calendar and flags only |
| `RULE` | Design choice defined in this file | changes need a CHANGELOG entry |

### 0.2 Identifiers

Rules are numbered `R-<section>.<n>`. Each rule is a condition a test can check. Lines starting with *Why:* explain a rule; they are not rules.

## 1. Invariants

| ID | Invariant |
|---|---|
| P1 | **Anchor first.** Every leg's fair probability comes from the US-consensus no-vig market (§5). The independent model (§8) may block or downgrade a bet. It never creates a bet, never raises a stake or a confidence level, and is never averaged with the anchor. |
| P2 | **Provenance.** Every number carries a §0.1 label, and every computed number in a report or ledger row traces to stored raw inputs (R-4.7, R-14.1). |
| P3 | **Synchronized snapshots.** Platform and US prices are compared only within `cfg:snapshots.snapshot_max_skew_min` (R-4.4). |
| P4 | **No bet is first-class.** Every evaluated game × market × side gets a decision and a reason code (§15). |
| P5 | **Scenario variables are flags.** They never adjust EV or stake until a backtest with stated N supports an adjustment (§10). |
| P6 | **Platform bias is measured separately** from game-level edges, with confidence intervals (§11). |
| P7 | **Disclose noise.** Every EV ships with σ_EV and the age of its inputs (R-12.3, R-4.6). |

Prohibited in v1:

1. Textbook NBA constants (home-court points, a fixed σ, a fixed back-to-back penalty). Estimate them from data or leave them out.
2. Averaging the model with the market, or letting model agreement raise a stake.
3. Importing MLB/NPB platform biases without NBA evidence. They are hypotheses H-MLB-1 and H-MLB-2 in §11.
4. ATS or over/under trend records, and narratives, as signals.
5. Parlays, props, live bets, futures.
6. Any stake output for a market whose format, settlement, or bankroll is not `CONFIRMED`.
7. Automated access to the betting platform. Platform data comes only from Eric's screenshots (`CONFIRMED` 2026-10-21).

## 2. Scope (v1)

- **R-2.1** Markets: full-game 讓分 (handicap), 大小 (total), and 獨贏 (moneyline) when the platform shows a price. `cfg:platform.markets_v1`
- **R-2.2** Games: NBA regular season 2026-10-20 → 2027-04-11, including every Emirates NBA Cup game (group play, knockout rounds, final). `cfg:season.regular_season`
- **R-2.3** Out of scope → `NB-SCOPE`: everything behind 「更多玩法」 (halves, quarters, others), player props, live, parlays, futures, preseason, play-in, playoffs.
- **R-2.4** A market shown as `-` → `NB-NOT-OFFERED`. It is still logged.

## 3. Platform

### 3.1 Facts

| Item | Value | Label · source |
|---|---|---|
| Platform | Same as MLB/NPB | `CONFIRMED` · Eric 2026-10-21 |
| Platform data | Eric's screenshots only; no automated access | `CONFIRMED` · Eric 2026-10-21 |
| Odds format | Hong Kong (net) odds | `CONFIRMED` · Eric 2026-10-21 (「賠率格式如附圖」). The screenshot's moneyline 0.56 / 1.4 fits only HK: Malay odds cannot exceed 1, decimal odds cannot be below 1 |
| Markets shown | 獨贏 · 讓分 · 大小, plus 「更多玩法」 | `CONFIRMED` · screenshot 2026-10-21 |
| Observed prices | 讓分 0.95 / 0.95 · 大小 0.94 / 0.94 · 獨贏 0.56 / 1.4 or `-` | screenshot 2026-10-21, N = 2 games; informational only (R-3.6) |
| Overtime | Counts in every market | `CONFIRMED` · Eric 2026-10-21 (「含延長」) |
| Postponement or suspension | Does not occur; no special rules | `CONFIRMED` · Eric 2026-10-21 |
| Bankroll | 100,000, separate from baseball | `CONFIRMED` · Eric 2026-10-21 |
| Platform bet limit | None (「無上限」) | `CONFIRMED` · Eric 2026-10-21. Read as the platform's limit, not Bethero's caps (R-12.5) |
| Minimum stake, increment | 100, 100 | `CONFIRM` · assumed, not stated |
| Paid data | Not allowed | `CONFIRMED` · Eric 2026-10-21 (「只用免費資料」) |

### 3.2 Line notation

| Board text | Legs | Settlement | Label |
|---|---|---|---|
| `X.5` (`2.5`, `大238.5`) | one leg at X.5 | win or lose; cannot push | `CONFIRMED` |
| `N平` (`大235平`) | one leg at N | exactly N → push, stake refunded | `CONFIRMED` (same-platform rule: `Codex-NPB tests/test_platform_rules.py`, confirmed by the platform 2026-08-26) |
| `N+XX`, `N-XX` (`5+50`) | — | — | `UNCONFIRMED` → `NB-SETTLEMENT` |
| bare `N` | — | — | `UNCONFIRMED` → `NB-FORMAT` |
| `N+X` (one digit), anything else | — | — | unreadable → `NB-FORMAT` |
| `-` | — | — | `NB-NOT-OFFERED` |

*Why `N±XX` is unconfirmed:* on this platform's NPB board, `N+XX` settles partially when the result lands exactly on N: the side laying N (or the over) wins XX% of the payout and the other side loses XX% of the stake. Under that rule `5+50` equals the standard Asian line 4.75 (half the stake at 4.5, half at 5). Eric's answer of 2026-10-21 says the NBA board has 「沒有部份輸贏」 (no partial win or loss). The two conflict, so `N±XX` stays `UNCONFIRMED` until Eric settles one concrete case; the answer goes into CHANGELOG.

- **R-3.1** Odds are Hong Kong odds h: decimal = 1 + h. A stake s risks s to win s·h, so amount at risk = stake. `cfg:platform.odds_format`
- **R-3.2** Each market is decoded with the table above. One leg that is `UNCONFIRMED` or unreadable makes the whole market `NB-FORMAT` or `NB-SETTLEMENT`. `cfg:platform.notation`
- **R-3.3** The handicap number is printed in the giving team's row; that team lays the line. The row marked `[主]` is home. Internally every handicap is stored as `home_line` (negative = home gives).
- **R-3.4** When the board shows a moneyline, its favourite (the lower HK price) must be the giving team. A conflict → `NB-DATA` for that game's 讓分 and 獨贏.
- **R-3.5** Overtime counts in settlement for every market. `cfg:platform.settles_overtime`
- **R-3.6** Prices are transcribed per snapshot and per side. The observed 0.95 / 0.94 are never assumed.
- **R-3.7** If a game is not completed on its scheduled date, its ledger rows become `VOID_PENDING`, are excluded from CLV and ROI, and stay so until Eric reports how the platform settled them. `cfg:platform.postponement`
- **R-3.8** Stakes are multiples of `cfg:platform.stake_increment` and at least `cfg:platform.min_stake`.

## 4. Time, snapshots, data access

- **R-4.1** Timestamps are stored in UTC (ISO-8601 with offset), displayed in Asia/Taipei, and converted with `zoneinfo`; fixed offsets are forbidden. A slate is keyed by its US Eastern date (MLB `eastern_date` convention); its games tip the next Taipei morning. US DST ends 2026-11-01 and resumes 2027-03-14 (tzdata, checked 2026-10-21): a 19:30 ET tip is 07:30 Taipei before 11-01, 08:30 from 11-01, and 07:30 again from 03-14. `cfg:time`
- **R-4.2** A platform snapshot is one screenshot from Eric. `platform_ts` is the phone clock visible in the screenshot (`ts_source = screenshot_clock`). Without a visible clock it is the time the screenshot reached the session (`ts_source = received`, an upper bound). Each screenshot is transcribed to `data/boards/<slate>/<platform_ts>.json`; fields that cannot be read with certainty are listed under `unresolved`, and a market with an unresolved field gets `NB-FORMAT`. Screenshots themselves are not committed, because the repository is public.
- **R-4.3** A US snapshot is one Odds API pull, taken when a screenshot arrives, plus the close pulls of R-14.3. Per-book `last_update` is kept. A quote older than `cfg:anchor.us_quote_max_age_min` at pull time is dropped.
- **R-4.4** `|platform_ts − us_ts| ≤ cfg:snapshots.snapshot_max_skew_min`, and both before tip; otherwise `NB-STALE`.
- **R-4.5** Passes are keyed to events, not clock times. A pass is FINAL-eligible for a game when (a) the official game-day injury report covering both teams has been published (for the second game of a back-to-back: the 1 p.m. local game-day status) and (b) that day's referee assignments are posted. `cfg:snapshots.require_gameday_report`, `cfg:snapshots.require_referee_assignments`. Before that, the pass is PRELIMINARY: everything is logged and no stake is output (`NB-STATUS`). The final pass for CLV is the last one within `cfg:snapshots.close_snapshot_window_min` of tip (R-14.3).

  *Why, in Taipei time from 2026-11-01 (US standard time):* referee assignments are posted around 22:00 the evening before; game-day reports arrive 00:00–05:00 (Eastern teams first, Pacific teams last); evening tips are 08:00–11:30. Subtract one hour before 11-01 and from 03-14. For tips at 5 p.m. local or earlier, game-day reports come 8–10 a.m. local, which is 21:00–23:00 Taipei the evening before for Eastern teams.

- **R-4.6** Every report states, at report time, the age of the US snapshot, the platform snapshot, and the injury report.
- **R-4.7** Data access. Code makes live requests only through one HTTP helper, and only when a run passes an explicit live flag; tests never touch the network. The helper waits at least `cfg:data_access.min_interval_s` between requests to the same host, sends `cfg:data_access.user_agent`, and stores every raw response with its URL, retrieval time, and SHA-256 so each number can be traced and re-run offline. Each source's terms are checked before first use (Appendix B). *Why:* this is the role the brief gave `pilot.py`, which does not exist; a repository URL identifies the client without publishing a personal email.

## 5. Step ①: Anchor

- **R-5.1** Conversions between HK, Malay, decimal, and American odds are exact and round-trip tested. Malay is supported for completeness; the platform uses HK.
- **R-5.2** De-vig methods: multiplicative, power, and Shin. Shin is the textbook version: solve for z > 0 such that the probabilities sum to 1, with no z = 0 shortcut. The MLB `devig_shin` is not reused: it always returns the multiplicative result (documented in `MLB/docs/gate_2b.md`; at −400/+320 it gives 77.06% where Shin gives 78.10%). Additive is computed for diagnostics only. `cfg:anchor.devig_methods`
- **R-5.3** Gating and Kelly use, for each leg, the lowest probability across `cfg:anchor.devig_methods` (precedent: MLB gate 2B requires the edge under every method). Reports show the `cfg:anchor.devig_display_method` value and the method spread. Every output records the methods used. `cfg:anchor.devig_gate_mode`
- **R-5.4** US consensus, per game, market, and line: de-vig each book that quotes both sides, then take the median across books (`cfg:anchor.consensus_statistic`, MLB `market.summarise_line`). No sharp-book weights (`cfg:anchor.sharp_weighting`): weights would be unvalidated inputs able to create bets; revisit only with Phase 3 calibration evidence. Fewer than `cfg:anchor.consensus_min_books` books → `NB-DATA`.
- **R-5.5** Spreads are keyed to the home team (MLB `line_key`): home −5.5 / away +5.5 is one market, home +5.5 / away −5.5 is another. The reference line `L_ref` is the line most books quote. A book at another line `L_b` with `|L_b − L_ref| ≤ cfg:anchor.consensus_translate_max_gap` is converted to `L_ref` through §7 before the median; books farther away are dropped. While `cfg:distribution.status` ≠ `VALIDATED`, only books at `L_ref` count.
- **R-5.6** The fair line is where a leg's win and loss probabilities are equal under the consensus distribution (§7 anchored at `L_ref`). It is used for sanity (R-6.6), bias (§11), and display, never to create a bet.
- **R-5.7** Moneyline vs. spread: the moneyline consensus implies a fair margin through §7. If it differs from the spread's fair line by more than `cfg:anchor.ml_spread_max_gap_pts` → `NB-DATA` for that game's 讓分 and 獨贏 (a data flag, never an edge). Likewise, a Tier A line whose own consensus differs from the §7 distribution by more than `cfg:anchor.consensus_consistency_max_pp` → `NB-DATA`. While §7 is unavailable, both checks are logged as `CHECK_SKIPPED`.
- **R-5.8** Odds API budget: no pull when the month's remaining credits (read from the response headers) would drop below `cfg:us_odds.min_remaining_reserve`, or when the day already has `cfg:us_odds.max_calls_per_day` pulls. Regions `cfg:anchor.regions`, markets `cfg:anchor.markets`, sport `cfg:anchor.sport_key`. A refused pull → `NB-DATA`.

## 6. Step ②: Platform lines and translation tiers

- **R-6.1** Teams are matched by abbreviation and Chinese name to the US feed's names. Home comes from `[主]`. A home/away mismatch with the US feed → `NB-DATA`, except at the NBA Cup final (neutral site: match by name and flag `NEUTRAL_SITE`).
- **R-6.2** **Tier A** (model-free), half-point leg: the leg's line is quoted by at least `cfg:tiers.tier_a_min_books` US books. Its probability is that line's consensus.
- **R-6.3** **Tier A**, integer leg at k: both neighbouring half-point lines, k − 0.5 and k + 0.5, are quoted by at least `cfg:tiers.tier_a_min_books` books. Then P(win) = P(cover at k + 0.5) and P(push) = P(cover at k − 0.5) − P(cover at k + 0.5), all from the market (the logic of MLB gate 2B). Otherwise the leg is Tier B.
- **R-6.4** **Tier B** (translated): the leg's line is within `cfg:tiers.tier_b_max_gap` of `L_ref`. Its probabilities come from §7 anchored to the consensus at `L_ref`. Translation noise enters σ_EV (R-12.3) and confidence is at most Medium. While `cfg:distribution.status` ≠ `VALIDATED`, Tier B is disabled and such legs get `NB-TIER-C`.
- **R-6.5** **Tier C**: any other leg → `NB-TIER-C`. The row is still logged for the bias and lag trackers.
- **R-6.6** **Sanity.** `|platform line − US fair line| > cfg:tiers.sanity_gap` → `NB-SANITY`, unless a timestamped, sourced explanation exists (R-9.5); with one, evaluation continues and usually stops at R-6.5. If the platform's giving team is not the US favourite and `|US fair line| ≥ cfg:tiers.direction_check_min_pts` → `NB-SANITY`. A reading is never flipped to match the market. *Why:* in MLB the screenshot row reading was wrong 6 times out of 6 (`MLB/docs/board_reading.md`); a flipped reading would bet the side nobody checked.
- **R-6.7** The moneyline is always Tier A: same market, two-way, overtime included on both sides.

## 7. Empirical margin and total distributions

- **R-7.1** Targets: P(final margin = k | closing spread bucket) and P(final total = k | closing total bucket), as integer masses, from final scores including overtime (`cfg:distribution.include_overtime`, because the platform settles with overtime). Margin = home − away (`cfg:distribution.margin_definition`).
- **R-7.2** Data: historical US closing lines and final scores with documented provenance (source, N, seasons, retrieval date). Free sources only. Candidates and access status are in Appendix B. Gaps are reported, never filled with invented data.
- **R-7.3** The season split (`cfg:distribution.train_seasons`, `cfg:distribution.holdout_seasons`) is fixed before fitting, with the most recent complete seasons as holdout. The 2019-20 bubble games and the 2020-21 season are excluded from the primary fit (`cfg:distribution.exclude`) and appear only in a sensitivity check.
- **R-7.4** Method: empirical masses per `cfg:distribution.bucket_width`-point bucket, kernel-smoothed across neighbouring buckets with `cfg:distribution.smoothing_bandwidth` chosen by cross-validation on the training seasons. It is compared on the holdout with a discretized normal fitted to the same data. Criterion: holdout log loss of win / push / lose at the lines the platform hangs, with N per bucket. The winner (`cfg:distribution.selected_method`) and its numbers go into `VALIDATION.md`; only then does `cfg:distribution.status` become `VALIDATED`.
- **R-7.5** Bug-detection bands only, never inputs: a fitted residual σ outside 10–15 points (margin) or 15–23 points (total) means investigate before use. The bands come from the brief and are unverified. `cfg:distribution.bug_bands`
- **R-7.6** Late-season behaviour from before 2026-27 is not used to estimate any late-season effect: the 3-2-1 lottery reform (Appendix A) is a regime break.

## 8. Independent model (veto only)

- **R-8.1** The model only vetoes or downgrades (P1).
- **R-8.2** Components, built in Phase 2: possession-based, opponent-adjusted team ratings from official box scores; home-court, rest, travel, and altitude effects estimated from data; and an injury adjustment (player impact × projected minutes) only once an impact metric with documented source and licence exists. `cfg:model.injury_impact_metric` is `none`, so the injury adjustment is off.
- **R-8.3** Early season: ratings shrink toward a prior (prior-season ratings regressed to the mean; market win totals only if a free source is found), with weight g / (g + k) after g games and k = `cfg:model.prior_shrinkage_k_games` chosen by backtest.
- **R-8.4** For side S at platform line X, let d = model expectation − X, oriented so that d > 0 favours S. If d < −`cfg:model.model_veto_pts` → `NB-MODEL-VETO`. If −`model_veto_pts` ≤ d < −`cfg:model.model_downgrade_pts` → confidence one level lower (minimum Low). d ≥ 0 changes nothing. For the moneyline, X = 0.
- **R-8.5** `cfg:model.status` is `OFF` until the model is built. A built but unvalidated model may veto, because that is stricter; its output is labelled `UNVALIDATED`. While `OFF`, confidence is at most Medium.
- **R-8.6** Evaluation (Phase 3): MAE against the closing spread and total; Brier score and log loss against results; split by season phase (games 1–20, game 21 to the trade deadline, post-deadline, last 20), with N per split.

## 9. Injuries and news

- **R-9.1** Source of truth: the official NBA injury report (`cfg:injuries.source`), parsed into a per-player status timeline (report time, status, reason).
- **R-9.2** At analysis time the newest stored injury report must be at most `cfg:snapshots.injury_report_max_age_min` old; otherwise `NB-STALE`. If the report cannot be fetched → `NB-STATUS`: missing data is not "no injuries".
- **R-9.3** A key player averaged at least `cfg:injuries.key_player_min_minutes` minutes over his last `cfg:injuries.key_player_window_games` games played. *Why minutes:* no licensed impact metric exists yet, and this proxy can only block.
- **R-9.4** A key player listed in `cfg:injuries.blocking_statuses` → `NB-STATUS` for that game, unless both EV ≥ 0 under the adverse resolution and EV ≥ `cfg:gates.min_ev` in expectation can be computed. That needs a validated impact metric, which v1 does not have, so in v1 it always blocks.
- **R-9.5** A news-lag edge requires all of: a sourced trigger with timestamp T; the US consensus moved after T; a platform screenshot taken after T that still shows the pre-move line; and synchronized snapshots (R-4.4). It is labelled `LAG`, and Eric weighs account-limitation risk separately.

## 10. Scenario flags

Every flag starts with evidence status `UNTESTED`. Flags never change EV or stake (P5).

| Flag | Definition | Config |
|---|---|---|
| `B2B` | team played on the previous US date | — |
| `3IN4` | team's third game in four US dates | — |
| `REST_DIFF` | rest-day difference of 2 or more | — |
| `TRAVEL_TZ` | 2 or more time zones crossed since the team's previous game (distance is logged, not thresholded) | — |
| `ALTITUDE` | game in Denver or Salt Lake City | `cfg:scenario.altitude_teams` |
| `NEUTRAL_SITE` | NBA Cup final at Hinkle Fieldhouse, Indianapolis (the Pacers' home city) | `cfg:season.cup_final` |
| `CUP_GROUP` | NBA Cup group-play game. Point differential, with overtime excluded, is a tiebreaker, so late-game margins carry incentives | `cfg:season.cup_group_play_dates` |
| `CUP_KNOCKOUT` | quarterfinal or semifinal (home sites) | `cfg:season.cup_quarterfinals`, `cfg:season.cup_semifinals` |
| `EARLY_SEASON` | either team has played fewer than `early_season_games` games | `cfg:scenario.early_season_games` |
| `POST_DEADLINE_ROSTER` | a team traded away or acquired a rotation player within `post_deadline_window_days` | `cfg:scenario.post_deadline_window_days`, `cfg:season.trade_deadline` |
| `LATE_SEASON_LOTTERY` | one of a team's last `late_season_games_remaining` games while it sits in the 16-team lottery range | `cfg:scenario.late_season_games_remaining`, `cfg:season.lottery_regime` |
| `STAR_ABSENT` | a "star" under the league's participation policy is out (latest version found: 2023-24) | — |
| `REF_CREW` | crew listed; low prior, flag only | — |

- **R-10.1** An adjustment requires a backtest with stated N and CI, a `VALIDATION.md` section, and a CHANGELOG entry.
- **R-10.2** Material flags for confidence (R-13.1) are listed in `cfg:scenario.material_flags`.

## 11. Platform bias monitor

- **R-11.1** One observation is one synchronized (R-4.4) platform market whose notation is `CONFIRMED`. For each observation:
  - `bias_fav_pts` = fair giving line − platform giving line (positive: favourable to favourite backers);
  - `bias_total_pts` = fair total − platform total (positive: favourable to over backers);
  - P-space bias = P_US(cover at the platform line) − 0.5, per side.

  `N±XX` observations are stored raw and excluded until their semantics are confirmed.
- **R-11.2** Splits: market; favourite / underdog; home / away; line-size bucket; time-to-tip bucket.
- **R-11.3** Inference: block bootstrap by slate date (`cfg:bias.bootstrap`). A bias is USABLE only when n ≥ `cfg:bias.bias_min_n`, distinct dates ≥ `cfg:bias.bias_min_days`, and the 95% CI excludes 0. Otherwise it is TENTATIVE.
- **R-11.4** A usable bias never changes EV. It labels an edge `BIAS` (R-12.6) and is reported weekly.
- **R-11.5** Tested, not assumed. H-MLB-1: platform totals sit below the US fair total (mean `bias_total_pts` > 0). H-MLB-2: handicaps are shaded toward the receiving side on larger lines.
- **R-11.6** Persistent-mispricing tracker, report only: per team, over the last `window_obs` observations, flag `PERSISTENT` when |mean| ≥ `min_abs_mean_pts` and the CI at level `ci` excludes 0. `cfg:bias.persistence`

## 12. Steps ③–④: EV, gates, sizing

- **R-12.1** EV per unit stake at the platform price h: EV = Σ over legs of weight × [P(win)·h − P(lose)]; a push contributes 0. Probabilities follow R-5.3.
- **R-12.2** Effective win probability p_eff = W / (W + L), where W and L are the win and loss masses (pushes excluded). The platform no-vig probability is the de-vig of the platform's own two prices (0.5 when they are equal). Divergence = p_eff − platform no-vig.
- **R-12.3** Noise:
  - σ_method = half the range of the leg probability across de-vig methods;
  - σ_books = 1.2533 × (IQR / 1.349) / √n, the standard error of the median across n books;
  - σ_translate, Tier B only, = √(SE(mass)² + (|empirical − normal| / 2)²);
  - σ_p = √(σ_method² + σ_books² + σ_translate²);
  - σ_EV = (1 + h) × σ_p.

  Reports show EV ± σ_EV and the age of the inputs.
- **R-12.4** Gates are evaluated in this order. A candidate is a bet only if all pass. The first failure is the primary code; every failure is logged.

  | Gate | Condition | Code |
  |---|---|---|
  | G0 | in scope, offered, not paused | `NB-SCOPE` / `NB-NOT-OFFERED` / `NB-PAUSED` |
  | G1 | every leg's notation and settlement `CONFIRMED` | `NB-FORMAT` / `NB-SETTLEMENT` |
  | G2 | bankroll `CONFIRMED` | no stake output |
  | G3 | snapshots synchronized and fresh, before tip (R-4.3, R-4.4, R-9.2) | `NB-STALE` |
  | G4 | data complete: consensus books, team mapping, cross-checks (R-3.4, R-5.7), Odds API pull allowed (R-5.8) | `NB-DATA` |
  | G5 | sanity and direction (R-6.6) | `NB-SANITY` |
  | G6 | every leg Tier A or Tier B | `NB-TIER-C` |
  | G7 | FINAL-eligible pass (R-4.5) and no blocking key-player status (R-9.4) | `NB-STATUS` |
  | G8 | EV ≥ `cfg:gates.min_ev`; EV − `cfg:gates.ev_noise_z` × σ_EV ≥ 0; for Tier A, the share of books whose own prices give EV > 0 is at least `cfg:gates.tier_a_book_agreement_min` | `NB-EV` |
  | G9 | divergence ≥ `cfg:gates.min_divergence_pp` | `NB-DIVERGENCE` |
  | G10 | no model veto (R-8.4) | `NB-MODEL-VETO` |
  | G11 | at most one of 讓分 and 獨贏 per game (`cfg:risk.one_side_market_per_game`); the one with the higher EV lower bound is kept | `NB-CORR` |
  | G12 | caps leave a stake of at least `cfg:platform.min_stake` | `NB-CAP` / `NB-MIN-STAKE` |

  *Why this order:* data completeness is checked before the edge, so a missing input cannot become a small edge (MLB `policy.py`). With equal 0.95 prices, G9 is implied by G8, because EV ≥ 4% already needs p_eff ≥ 53.33%; G9 is kept for unequal prices and moneylines.

- **R-12.5** Stake:
  1. f\* = argmax over f of Σᵢ pᵢ · log(1 + f · rᵢ) over the win / push / loss outcomes, using R-5.3 probabilities (generalized Kelly, as in `cc_npb bethero/ev.py`).
  2. stake = min(`cfg:risk.kelly_fraction` × f\* × bankroll, `cfg:risk.max_bet_pct` × bankroll, remaining daily cap, remaining per-game cap), rounded down to `cfg:platform.stake_increment`. Bankroll = `cfg:risk.bankroll`.
  3. Below `cfg:platform.min_stake` → `NB-MIN-STAKE`; a cap already exhausted → `NB-CAP`.
  4. Caps count amount at risk; with HK odds, risk = stake.
  5. The daily cap (`cfg:risk.daily_cap_pct`) applies per US Eastern slate date (`cfg:risk.daily_cap_basis`). When bets compete for it, allocate greedily by EV lower bound (EV − z·σ_EV), highest first (`cfg:risk.allocation_order`).
  6. 讓分 or 獨贏 plus 大小 on the same game share one per-game cap (`cfg:risk.per_game_cap_pct`) until their correlation is estimated.

  *Why the caps stay although the platform has no limit:* the largest EVs come disproportionately from errors (a misread line, a stale screenshot), and quarter Kelly sizes those errors largest. The caps bound that damage. Removing them is Eric's call (`CONFIRM`).
- **R-12.6** Edge label: `LAG` when R-9.5 holds; `BIAS` when the edge's direction matches a USABLE bias (R-11.3); `ROUNDING` when `|platform line − fair line| ≤ cfg:tiers.rounding_max_pts` and neither applies; otherwise `UNEXPLAINED`.
- **R-12.7** Mode: when `cfg:mode` = `shadow`, stakes are computed and logged as 影子注額 and are not to be placed. Live requires Eric's explicit go-live message.
- **R-12.8** Few qualifying bets is the expected outcome.

## 13. Step ⑤: Confidence

Confidence is informational; it never changes a stake.

- **R-13.1** Start at High, then apply every cap that matches.

  | Cap | Condition |
  |---|---|
  | Medium | any Tier B leg; `ts_source = received`; model `OFF`; σ_EV > `cfg:confidence.sigma_ev_medium`; at least one material flag |
  | Low | edge label `UNEXPLAINED`; σ_EV > `cfg:confidence.sigma_ev_low`; at least `cfg:confidence.material_flags_low` material flags |
  | One level down | model downgrade zone (R-8.4) |

## 14. Logging, CLV, review, pause

- **R-14.1** Every evaluated game × market × side, bet or not, is appended to a SHA-256 hash-chained JSONL ledger (`Codex-NPB src/codex_npb/ledger.py`). Each row holds: `platform_ts` and `ts_source`, `us_ts`, injury report time; platform notation, legs, prices; US consensus per line and per method; fair line; tier; EV ± σ_EV; divergence; reason codes; flags; confidence; model output; stake and mode; config version; code commit.
- **R-14.2** Board files are committed before the first tip they cover. The commit time is the evidence of pricing time and is checked per game (`Codex-NPB src/codex_npb/pipeline_cli.py`, `_board_row_commit_times`).
- **R-14.3** US close = the last US snapshot within `cfg:snapshots.close_snapshot_window_min` before tip. Platform close = Eric's last screenshot before tip. Missing → CLV is N/A, never imputed.
- **R-14.4** `CLV_line` = P(cover | bet line) − P(cover | platform closing line), both under the US closing fair distribution. *Why:* the platform moves the line, not the price, so price CLV is structurally 0.
- **R-14.5** `CLV_US` = EV of the bet ticket under the US closing fair distribution at the platform price, plus its change since bet time.
- **R-14.6** Weekly review on `cfg:clv.review_weekday` (Taipei): mean `CLV_line` and `CLV_US` with N and a date-block bootstrap CI; the bias monitor; veto hit-rate (CLV of vetoed versus non-vetoed candidates); reason-code counts; tier mix.
- **R-14.7** Pause: over the last `cfg:clv.pause_min_n` or more recommendations (shadow or live) with CLV available, if mean `CLV_US` or mean `CLV_line` is below 0 with the `cfg:clv.pause_ci` CI excluding 0 → `mode: paused`. Every market then gets `NB-PAUSED` until a diagnosis is logged and Eric approves resuming.
- **R-14.8** ROI is reported, but CLV leads decisions: separating a 3% ROI edge from variance takes about 6,500 bets (lesson 7).

## 15. No-bet codes

| Code | Gate | 說明 |
|---|---|---|
| `NB-SCOPE` | G0 | 不在 v1 範圍（更多玩法、季後賽等） |
| `NB-NOT-OFFERED` | G0 | 平台沒開這個盤（顯示「-」） |
| `NB-PAUSED` | G0 | 暫停規則啟動中，等待診斷 |
| `NB-FORMAT` | G1 | 盤口寫法或賠率格式讀不出來或未確認 |
| `NB-SETTLEMENT` | G1 | 這種寫法的結算規則未確認（目前：所有 N±XX 尾盤） |
| `NB-STALE` | G3 | 平台與美盤快照不同步，報價或傷病報告過舊，或已開賽 |
| `NB-DATA` | G4 | 資料不足或互相矛盾（書商太少、隊名對不上、獨贏與讓分矛盾、API 額度不足） |
| `NB-SANITY` | G5 | 與美盤公平線差太多或方向相反，推定是舊盤、抄錯或未反映的消息 |
| `NB-TIER-C` | G6 | 需要的換算超出範圍，或分布尚未驗證 |
| `NB-STATUS` | G7 | 關鍵球員出賽未定、當日傷病報告或裁判名單未出，或拿不到傷病報告 |
| `NB-EV` | G8 | 期望值未達門檻，或扣掉雜訊後不為正 |
| `NB-DIVERGENCE` | G9 | 公平機率與平台無水機率的差距不夠 |
| `NB-MODEL-VETO` | G10 | 獨立模型明顯站在另一邊 |
| `NB-CORR` | G11 | 同場已選讓分或獨贏其中之一 |
| `NB-CAP` | G12 | 單日或單場上限已滿 |
| `NB-MIN-STAKE` | G12 | 算出的注額低於平台最低注額 |

## 16. Report (繁體中文, mobile-first)

- **R-16.1** Language `cfg:report.language`; times in `cfg:report.display_tz`. The header states the mode, the times of the US snapshot, the platform screenshot, and the injury report (R-4.6), the bankroll, and today's exposure against the daily cap. In `shadow` mode the header says 影子 and every stake is a shadow stake.
- **R-16.2** The bets table has exactly these `cfg:report.max_bet_columns` columns: 比賽 | 選項 | 平台盤/賠率 | 公平機率 | EV(±) | 注額 | 信心. Under it, one line per bet: tier, edge label (R-12.6), scenario flags, and the worst acceptable platform line, i.e. the worst line at which every gate still passes.
- **R-16.3** The no-bet table has the columns 比賽 | 市場 | 代碼 | 說明, one row per evaluated market. The ledger keeps both sides (R-14.1).
- **R-16.4** The report ends with what would change each recommendation (「若 X 確定缺陣 → 取消」 style) and a transcription check listing every platform line as it was read.

Template, filled with the §18 example:

```markdown
# NBA 分析｜美東 11-02 賽程（台北 11-03 早上開打）
模式：影子（注額只記錄，不實際下注）
美盤快照 07:12｜平台截圖 07:10（手機時間）｜傷病報告 06:45｜報告 07:14
本金 100,000｜今日已用 1,000 / 5,000

## 建議
| 比賽 | 選項 | 平台盤/賠率 | 公平機率 | EV(±) | 注額 | 信心 |
|---|---|---|---|---|---|---|
| A@H 08:30 | H 讓 4.5 | 4.5 / 0.95 | 55.6% | +8.4% (±1.0) | 1,000 | 中 |

- A@H：Tier B（美盤 −5.5 換算 1 分）｜LAG：06:45 官方傷病報告 A 隊 X 改列缺陣｜情境：無｜最差可接受：讓 5平

## 不下注
| 比賽 | 市場 | 代碼 | 說明 |
|---|---|---|---|
| A@H | 大小 | NB-EV | 平台 228.5 與美盤相同，EV −3.0% |
| C@D | 讓分 | NB-SETTLEMENT | 5+50 尾盤結算規則待確認 |
| C@D | 獨贏 | NB-NOT-OFFERED | 平台沒開 |

## 什麼會改變建議
- 平台變成讓 5.5 或更多 → 取消 A@H
- A 隊 X 改列可出賽 → 重跑

## 抄盤核對
- A@H[主]：讓 H 4.5 / 0.95｜大小 228.5 / 0.94｜獨贏 0.45 / 1.75
- C@D[主]：讓 D 5+50 / 0.95｜大小 231平 / 0.94｜獨贏 -
```

The last section repeats every transcribed line so Eric can check the reading against his screen at a glance.

Glossary: handicap 讓分 · total 大小分 · moneyline 獨贏 · no-vig probability 無水機率 · breakeven 損益兩平 · expected value 期望值 (EV) · Kelly 凱利 · CLV 收盤線價值 · push 走盤 · half win / half loss 贏半 / 輸半 · back-to-back 背靠背 · No bet 不下注.

## 17. Change control

- **R-17.1** `config.yaml` carries `meta.version` (semver) and `meta.updated`. Every change bumps the version and adds a CHANGELOG entry.
- **R-17.2** A `CONFIRM` value changes only on Eric's explicit message; the CHANGELOG records its date.
- **R-17.3** An `UNVALIDATED` value changes only with evidence: source, N, date range, method, and CI, linked to a `VALIDATION.md` section. Recent profit or loss alone is never a reason. A threshold under a pre-declared test stays fixed until the declared sample size is reached (MLB `docs/prospective_test.md` convention).
- **R-17.4** Errors in Claude's own outputs go to `ERRATA.md`: what was wrong, its quantified impact, and the fix.

## 18. Worked example (HYPOTHETICAL)

**Every input below is invented to show the arithmetic. None is an estimate, and none may be quoted as one.** The example also assumes that `cfg:distribution.status` is `VALIDATED`. Today it is not, so this same input would stop at G6 with `NB-TIER-C`.

**Setup.** Away team A at home team H, US slate 2026-11-02, tip 08:30 Taipei on 11-03.
- 06:45 — the official injury report moves A's key player X from Questionable to Out. This is the timestamped trigger.
- 07:10 — Eric's screenshot, phone clock visible: H's row shows 讓分 `4.5` at 0.95 / 0.95. `4.5` is a half-point line, which is `CONFIRMED` notation.
- 07:12 — US snapshot. Eight books hang H −5.5; none hangs −4.5. Skew 2 minutes ≤ 20 (G3 passes).

**Step 1: de-vig each book** (probability that H covers −5.5, i.e. wins by 6 or more):

| Book | H −5.5 | A +5.5 | multiplicative | power | Shin |
|---|---|---|---|---|---|
| B1 | −120 | +100 | 0.5217 | 0.5232 | 0.5227 |
| B2 | −118 | −102 | 0.5174 | 0.5186 | 0.5182 |
| B3 | −122 | +102 | 0.5261 | 0.5278 | 0.5273 |
| B4 | −115 | −105 | 0.5108 | 0.5116 | 0.5113 |
| B5 | −120 | +100 | 0.5217 | 0.5232 | 0.5227 |
| B6 | −125 | +105 | 0.5325 | 0.5346 | 0.5339 |
| B7 | −119 | −101 | 0.5195 | 0.5209 | 0.5204 |
| B8 | −121 | +101 | 0.5239 | 0.5255 | 0.5250 |
| **Median** | | | **0.5217** | **0.5232** | **0.5227** |

**Step 2: consensus.** 8 books ≥ `consensus_min_books` (8), so G4 passes. The worst case for H is multiplicative: P(margin ≥ 6) = 0.5217. σ_method = 0.0007. The multiplicative IQR is 0.0076, so σ_books = 1.2533 × (0.0076 / 1.349) / √8 = 0.0025.

**Step 3: translation (Tier B).** The platform leg H −4.5 wins when H wins by 5 or more, so P = P(margin ≥ 6) + P(margin = 5). No US book quotes −4.5, and the gap to `L_ref` is 1.0 ≤ `tier_b_max_gap.spread` (1.5), so the leg is Tier B (G6 passes).
- From a hypothetical §7 bucket with N = 1,800: P(margin = 5 | spread −5.5) = 0.0340, SE = √(0.034 × 0.966 / 1800) = 0.0043. The normal approximation gives 0.0310.
- σ_translate = √(0.0043² + 0.0015²) = 0.0045.
- P(H covers −4.5) = 0.5217 + 0.0340 = **0.5557** (worst case; Shin 0.5567, power 0.5572).
- Sanity: with P(margin = 6) = 0.0330 (hypothetical), Shin gives P(margin ≥ 7) = 0.4897, and the no-push cover rate at −6 is 0.4897 / 0.967 = 0.5064 > 0.5. So the fair line lies between 6 and 6.5, which is 1.5 to 2.0 points from 4.5: within `sanity_gap.spread` (3.0), and the direction agrees (G5 passes).

**Step 4: EV and noise** at h = 0.95:
- EV (worst case) = 0.5557 × 1.95 − 1 = **+8.37%** (Shin +8.56%, power +8.66%).
- σ_p = √(0.0007² + 0.0025² + 0.0045²) = 0.0052, so σ_EV = 1.95 × 0.0052 = **0.0102**. Reported as +8.4% ± 1.0%.
- G8: 8.37% ≥ 4%, and 8.37% − 1.0 × 1.02% = 7.35% ≥ 0. Passes. Book agreement is a Tier A test and does not apply; for information, every book's own price gives EV > 0.
- G9: no push is possible, so p_eff = 0.5557 and divergence = 5.57 pp ≥ 3.0. Passes.
- G7: X is Out (resolved), no other key player is Questionable or Doubtful, and the game-day report and referee assignments are out. Passes.
- G10: hypothetical model margin for H = +5.0, so d = 5.0 − 4.5 = +0.5. It favours H, which changes nothing; agreement never raises a stake.
- Edge label: the gap exceeds `rounding_max_pts.spread` (1.0), and the 06:45 trigger with the post-trigger US move satisfies R-9.5, so the label is `LAG`.

**Step 5: stake.**
- f\* = (0.5557 × 0.95 − 0.4443) / 0.95 = 0.0881. Quarter Kelly = 2.20% × 100,000 = 2,202.
- min(2,202; max bet 1,000; daily remaining 5,000; per-game remaining 1,000) = 1,000, rounded down to the 100 increment = **1,000**.
- In `shadow` mode this is logged as 影子注額 1,000.

**Step 6: confidence.** Tier B caps it at Medium; the model agrees, which does not raise it. Result: **中**.

**Step 7: worst acceptable line.**
- At 讓 `5平`: win if H wins by 6+ (0.5217), push at exactly 5 (0.0340), lose otherwise (0.4443). EV = 0.5217 × 0.95 − 0.4443 = +5.14%; p_eff = 0.5217 / 0.966 = 0.5401, divergence 4.01 pp; EV − σ_EV ≈ 5.14% − 0.98% = 4.16%. All gates pass.
- At 讓 `5.5`: EV = 0.5217 × 1.95 − 1 = +1.74% < 4% → `NB-EV`.
- The report therefore says 「最差可接受：讓 5平」.

## Appendix A. Season facts

Checked on 2026-10-21 through web-search result summaries. The primary pages could not be opened from this environment, so re-open them before relying on any detail not stated here.

| Fact | Value | Source | Status |
|---|---|---|---|
| Regular season | 2026-10-20 → 2027-04-11 | [Fox Sports](https://www.foxsports.com/stories/nba/when-does-2026-27-nba-season-start-opening-night-schedule); NBC affiliates say only "April" | verified, secondary |
| NBA Cup group play | 2026-10-30; 11-06, 11-13, 11-20, 11-24, 11-25, 11-27 | [Fox News](https://www.foxnews.com/sports/2026-nba-cup-schedule-group-play-knockout-rounds-championship), [NBA.com](https://www.nba.com/news/2026-nba-cup-group-play-schedule-announced) | verified |
| NBA Cup knockout | quarterfinals 12-04 and 12-05; semifinals 12-08 and/or 12-09; home sites | [Fox News](https://www.foxnews.com/sports/2026-nba-cup-schedule-group-play-knockout-rounds-championship) | verified |
| NBA Cup final | Friday 2026-12-11, Hinkle Fieldhouse, Indianapolis | [Fox News](https://www.foxnews.com/sports/2026-nba-cup-schedule-group-play-knockout-rounds-championship), [Eurohoops](https://www.eurohoops.net/en/nba-news/1986361/nba-cup-update-indianapolis-groups/) | verified |
| Final counts in standings | no | brief | not re-verified |
| 80 games scheduled, 2 set after group play | — | brief | not re-verified |
| Group tiebreakers | head-to-head → point differential → total points (overtime excluded; an overtime game counts as 0 differential) → prior-season record → random draw | [Wikipedia: 2025 NBA Cup](https://en.wikipedia.org/wiki/2025_NBA_Cup), [Wikipedia: NBA Cup](https://en.wikipedia.org/wiki/NBA_Cup) | verified for the 2024 and 2025 editions; 2026 assumed identical |
| Trade deadline | Thursday 2027-02-11, 3:00 p.m. ET | [Hoops Rumors via Yardbarker](https://www.yardbarker.com/nba/articles/2027_nba_trade_deadline_set_for_february_11/s1_14822_44140863), citing the league's key-dates list | verified, secondary |
| Injury reporting | status and reason by 5 p.m. local the day before (second game of a back-to-back: 1 p.m. local on game day); game-day report 11 a.m.–1 p.m. local (8–10 a.m. for tips at 5 p.m. or earlier), not for the second game of a back-to-back; updated continually | [official.nba.com, 2025-26 page](https://official.nba.com/nba-injury-report-2025-26/) | verified for 2025-26; no 2026-27 page found; the brief's "~15-minute cadence" not verified |
| Referee assignments | about 9:00 a.m. ET each game day | [official.nba.com](https://official.nba.com/referee-assignments/) | verified |
| Lottery reform | "3-2-1": lottery grows from 14 to 16 teams; the three worst teams get 5.4% at No. 1, the 4th–10th worst 8.1%; the league may cut odds or move picks for tanking; approved 29-1 in May 2026 for the next three drafts | [AP via WTOP](https://wtop.com/nba/2026/05/nbas-board-of-governors-passes-anti-tanking-changes-to-draft-lottery-process-ap-source-says/), [theScore](https://es.thescore.com/nba/news/3546790) | verified |
| Participation policy | 2023-24 version: "star" definition; at most one star out per game; stars available for national TV and the Cup | [ESPN, 2023](https://africa.espn.com/nba/story/_/id/38392750/source-nba-board-governors-approve-tougher-rest-rule) | latest found; 2026-27 changes not verified |
| US DST | ends 2026-11-01, resumes 2027-03-14 | Python `zoneinfo` (tzdata), computed 2026-10-21 | verified |

## Appendix B. Data sources and access (2026-10-21)

This cloud environment's network policy allows only `api.the-odds-api.com` among the hosts below; the others were refused by the proxy (HTTP 403 on CONNECT). Whatever is blocked must be allowed in the environment settings or fetched on Eric's Windows machine.

| Need | Source | Access here | Terms / notes | Use |
|---|---|---|---|---|
| Live US odds | The Odds API v4, `basketball_nba` | reachable; `ODDS_API_KEY` present | Free tier is described by third parties as 500 credits a month, costing markets × regions per pull; historical pulls cost ten times as much and may need a paid plan. Check the official docs before Phase 2 | primary (R-5.8) |
| Final scores for settlement | The Odds API `/scores` (last 3 days) | reachable | same | primary |
| Injury report | official.nba.com, PDFs on ak-static.cms.nba.com | blocked | not yet checked | needed for G7 |
| Referee assignments | official.nba.com/referee-assignments | blocked | not yet checked | needed for G7 |
| Schedule, box scores (model, flags) | cdn.nba.com, stats.nba.com | blocked | not verified | model and flags |
| Historical closing lines and scores (§7) | Sportsbook Reviews Online archive (www.sportsbookreviewsonline.com); a Stanford CS229 poster says it covers every NBA game since October 2007 | blocked | not verified. Provenance questions: possibly one default book rather than a consensus, and a 2009 forum post reports past lines changing | candidate |
| Same, alternative | Kaggle datasets derived from that archive | blocked; needs a login | licence per dataset | candidate, if Eric downloads one |
| Same, fallback | our own close snapshots from The Odds API | reachable | — | slow: one season of history per season |
| bet365 | — | — | no public historical archive. Operator terms commonly forbid automated access ([DraftKings clause](https://conductatlas.com/platform/draftkings/draftkings-terms-of-use/provision/CA-P-039378/automated-scraping-of-website-information-prohibited/)); bet365's own terms could not be retrieved | not used |
| Paid sources | — | — | Eric: free data only | excluded |

## Appendix C. Lessons encoded

| Lesson | Rule |
|---|---|
| 1. Platform bias is platform- and sport-specific | §11: H-MLB-1 and H-MLB-2 are tested, not assumed |
| 2. Small samples lie | N on every statistic; `bias_min_n`, `bias_min_days`, `pause_min_n`; σ_EV (R-12.3) |
| 3. A fabricated benchmark drove a wrong diagnosis | P2; §0.1 labels; Appendices A and B record what was and was not verified |
| 4. Model-free anchoring beats distributional modelling | P1; Tier A (R-6.2, R-6.3); moneyline always Tier A |
| 5. Price CLV is structurally zero on a line-moving platform | `CLV_line` (R-14.4) |
| 6. Data overrides structural logic | P5: flags, not adjustments |
| 7. A 3% ROI edge needs ~6,500 bets to separate from variance | CLV leads (R-14.8); pause rule on CLV (R-14.7) |
| 8. No bet is valid and frequent | P4; §15; R-12.8 |
| 9. Multi-day tracking finds persistent mispricing | R-11.6; hash-chained ledger (R-14.1) |
| MLB Shin bug | R-5.2 |
| MLB screenshot row misreads (6 of 6) | R-6.6: never flip a reading |
| NPB: equal prices make the platform no-vig 0.5 | R-12.2, R-12.4 note |
| MLB gate 2B: edge under every de-vig method, ≥ 8 books, ≥ 75% agreement | R-5.3, `consensus_min_books`, `tier_a_book_agreement_min` |
| NPB: model–market disagreement was mostly model error (β ≈ 1.26, N = 177, post-hoc) | P1 |

## Appendix D. Code to port in Phase 2

Ported by copying, fixing, and testing; each module's docstring names the source repository and commit.

| What | From |
|---|---|
| HK and decimal conversion; generalized Kelly | `cc_npb bethero/ev.py` |
| American and decimal conversion; multiplicative and power de-vig (Shin rewritten) | `MLB src/mlbline/devig.py` |
| Odds API client, `Quote`, `line_key`, `eastern_date`, `select_slate` | `MLB src/mlbline/odds.py` |
| Median consensus and quote staleness | `MLB src/mlbline/market.py` |
| Model-free ticket pricing from US lines | `MLB src/mlbline/verify.py` |
| Notation parsing and settlement tests (tail lines pending) | `Codex-NPB src/codex_npb/model.py`, `tests/test_platform_rules.py`; `cc_npb bethero/lines.py` |
| Hash-chained ledger | `Codex-NPB src/codex_npb/ledger.py` |
| Per-game pricing-time check from git commit times | `Codex-NPB src/codex_npb/pipeline_cli.py` |
| Prospective ledger fields, including closing values | `Codex-MLB work/prospective_validation.py` |
| CJK display width for tables | `MLB src/mlbline/teams.py` |
