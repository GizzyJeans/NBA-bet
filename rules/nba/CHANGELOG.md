# Changelog: rules/nba

Every change to `RULES.md` or `config.yaml`. A `CONFIRM` value changes only on Eric's explicit message (date recorded). An `UNVALIDATED` value changes only with evidence: source, N, date range, method, CI (RULES §17).

## 0.5.1 · 2026-10-23

- `model.status` stays `"OFF"`; its label changes from `CONFIRM` to `RULE`. `CONFIRM` means "the value shown is the stricter default", and OFF is not the stricter value: a model that is on can only block more bets. The source now says that turning it on needs in-season results and a run-time fit in `analyze` first (ERRATA E-006).
- R-8.5 defines "built" as that run-time fit. README and VALIDATION.md §1 say the same.

## 0.5.0 · 2026-10-23

Phase 3 validation. The criteria were committed before any data was loaded (VALIDATION.md §0, `b529ba6`), and the addendum before any statistic was computed (§0.7, `68696d8`). Every value below follows from those rules, with its evidence in VALIDATION.md. Lines come from a dataset that does not state their timing (D1).

- `distribution.status` UNAVAILABLE → VALIDATED, with a new key `distribution.validated_markets` = [spreads, totals] (VALIDATED). Both markets pass V3 at every offset up to their gap and V4 (R3: holdout 2023-24 and 2024-25, N = 2,441 / 2,438; residual SD 13.55 / 17.54).
- `distribution.train_seasons` = 2014-15 to 2022-23 without 2020-21 (N = 9,400) and `distribution.holdout_seasons` = 2023-24, 2024-25 (S1, R2). Status RULE.
- `distribution.smoothing_bandwidth` null → spread 2.0, total 3.0 (V1, leave one season out).
- `distribution.selected_method` null → normal for both (V2: holdout log loss 0.75262 vs 0.75512 empirical for spreads, 0.73466 vs 0.75169 for totals).
- `tiers.tier_b_max_gap` UNVALIDATED → VALIDATED, value unchanged at spread 1.5 and total 2.0 (Gap rule). VALIDATION.md §0.3 replaced the Phase 1 plan, which was to use the de-vig method spread, with a binomial calibration test.
- `anchor.devig_display_method` UNVALIDATED → VALIDATED, value unchanged at shin (DV1: lowest holdout log loss, N = 2,441). The three methods differ by less than one standard error; gating stays worst-case.
- `model.prior_shrinkage_k_games` null → 5 (M1, the edge of the declared grid).
- `model.model_veto_pts` {3.0, 6.0} → {5.4, 7.0} and `model.model_downgrade_pts` {1.5, 3.0} → {3.5, 4.5} (M3: 80th and 60th percentiles of |model − closing| on holdout, N = 2,371, rounded down). These are looser than the placeholders. `model.status` stays OFF, now `CONFIRM`: Eric decides.
- RULES:
  - R-6.4: Tier B only for validated markets, from matching `data/dist/` files, failing closed when a family cannot anchor.
  - R-7.2, R-7.4: the dataset in use, and the validation criteria.
  - R-8.3: k was chosen with a zero prior.
  - R-8.6: the deadline split is not evaluated.
  - Appendix B: us+us2 counts, NBA hosts behind Akamai, the SBR archive gone, the dataset in use.
- Code:
  - `history.py`, the source adapter, pinned by SHA-256.
  - `validate.py`, rewritten to the criteria (ERRATA E-004).
  - `data/dist/*.json`, aggregate family counts.
  - `analyze`: loads Tier B and refuses family files that disagree with the config.
  - The report lists which codes blocked the slate.

## 0.4.0 · 2026-10-23

- `anchor.regions` [us] → [us, us2], CONFIRMED (Eric 2026-10-23: 「確認，加開 us2」). A pull now costs 6 credits and returns 14–15 books per game.
- `us_odds.monthly_credit_budget` 500: CONFIRM → FACT (response headers 2026-10-21: used 84 + remaining 416).
- `us_odds.max_calls_per_day` 4 → 2 (UNVALIDATED, stricter): 2 pulls × 6 credits × 30 days = 360 of 500.
- `anchor.consensus_min_books` stays 8 (Eric chose us2 over a lower bar); rationale updated.
- Code: spread line keys no longer split a pick'em into `-0.0` and `0.0`.

## 0.3.0 · 2026-10-21

Phase 1 approved by Eric (「確認，開始 Phase 2」). Clarifications found while implementing Phase 2; no threshold value changed.

- R-4.7: raw Odds API responses stay out of git (`data/raw/` ignored). The Odds API's terms forbid redistributing its data as dumps and the repository is public; the ledger keeps hash, time and redacted URL.
- R-5.3: the worst case is the method giving the ticket its lowest EV (identical to the lowest probability for one-leg tickets).
- R-5.6: while the distribution is unvalidated, the fair line is approximated by `L_ref` (`fair_source = l_ref`); it can only block or label.
- R-9.1: the injury report enters as a JSON transcription until it can be fetched and its PDF layout has been tested on a real copy.
- §10: `TRAVEL_TZ` logs no distance until a sourced arena table exists; `CUP_GROUP` is date-based (assumed for 2026); `CUP_KNOCKOUT` needs an explicit knockout list.
- R-16.2: the worst acceptable line is searched in tail steps of 5 (0.025 points), 獨贏 prices in steps of 0.01.
- §16 and §18: the worst acceptable line in the worked example is 讓 5-30, not 讓 5平 (ERRATA E-003).
- Appendix B: observed book counts for region `us` (9 books; the most-quoted line 3–9) and the 30 team names checked against the API. Appendix D: ported modules with source commits.
- config: `anchor.regions` and `anchor.consensus_min_books` rationales record the book-count observation; the values stay until Eric decides.

## 0.2.0 · 2026-10-21

- Tail lines `N+XX` and `N-XX` confirmed. Eric corrected his earlier 「沒有部份輸贏」 the same day: 「會有部分輸贏的狀況，規則跟A一樣」, i.e. WAS `5+50` at 0.95 with WAS winning by exactly 5 pays +47.5 per 100 on WAS and −50 per 100 on MIL. `cfg:platform.notation.tail_line` moves from `UNCONFIRMED` to `CONFIRMED`; tail lines are priced as two legs (RULES §3.2) and enter the bias monitor at their effective line.
- R-12.2 and R-12.5 spell out partial outcomes; the report template's no-bet example now shows a tail line stopped at `NB-TIER-C`.

## 0.1.0 · 2026-10-21

Initial Phase 1 draft (Claude), awaiting Eric's approval.

- Platform facts from Eric's answers of 2026-10-21 and his screenshot of two games (ORL–ATL, WAS–MIL): same platform as MLB/NPB, Hong Kong odds, overtime counts, no postponements, bankroll 100,000 separate from baseball, platform has no bet limit, screenshots are the only platform source, free data only.
- `X.5` and `N平` notation confirmed. `N±XX` tail lines left `UNCONFIRMED` (→ `NB-SETTLEMENT`) because the same-platform NPB rule (partial settlement at exactly N) conflicts with Eric's 「沒有部份輸贏」.
- Policy values mirror the NPB profile and are marked `CONFIRM`: `kelly_fraction` 0.25, `min_ev` 0.04, `min_divergence_pp` 3.0, `max_bet_pct` 0.01, `daily_cap_pct` 0.05. The 1% and 5% caps are kept although Eric wrote 「無上限」, read as the platform's limit (stricter reading, flagged).
- Data-dependent thresholds proposed as `UNVALIDATED` with rationales.
- Season facts re-checked through web-search summaries (RULES Appendix A).
- `pilot.py` does not exist; its role is defined as R-4.7, with a repository-URL User-Agent instead of an email.
