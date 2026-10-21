# Changelog: rules/nba

Every change to `RULES.md` or `config.yaml`. A `CONFIRM` value changes only on Eric's explicit message (date recorded). An `UNVALIDATED` value changes only with evidence: source, N, date range, method, CI (RULES §17).

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
