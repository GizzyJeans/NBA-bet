# Errata

Errors found in Claude's own earlier outputs for this project: what was wrong, its impact, and the fix.

## E-001 · 2026-10-21 · Phase 0 reply, recon bullet on record-keeping tools

- **Wrong:** attributed the per-game "prospective by board-file git commit time" check to `Codex-NPB src/codex_npb/ledger.py`.
- **Correct:** the check lives in `src/codex_npb/pipeline_cli.py` (`_board_commit_time`, `_board_row_commit_times`) and `board.py`. `ledger.py` implements only the SHA-256 hash chain.
- **Impact:** none on any number, rule, or threshold. Attribution only.
- **Fix:** RULES R-14.1 and R-14.2 cite the right files.

## E-003 · 2026-10-21 · RULES 0.2.0, §16 template and §18 Step 7

- **Wrong:** the worked example's worst acceptable line was 讓 `5平`. That was correct in 0.1.0, when tail lines were unconfirmed, but 0.2.0 confirmed tail lines and the example was not updated.
- **Correct:** with tail lines, 讓 `5-30` (effective 5.15) still passes every gate: EV +4.11%, divergence 3.44 pp. 讓 `5-35` gives EV +3.94% and fails. Found by the Phase 2 golden test `tests/test_worked_example.py`.
- **Impact:** display only, 0.15 points in the reported threshold. No gate, EV, or stake changed.
- **Fix:** RULES 0.3.0 §16 and §18; the test now pins 讓 5-30.

## E-002 · 2026-10-21 · Phase 0 reply, "missing" bullet on CLV

- **Wrong:** said Codex-MLB computes CLV only from line or price.
- **Correct:** `Codex-MLB work/prospective_validation.py` also computes `probability_clv`: the closing selection probability minus the selection's market probability at prediction time.
- **Impact:** none on the rules. It understated reusable code. The NBA CLV definitions (R-14.4, R-14.5) stand, because the brief asks for CLV along the platform's line under the US closing fair distribution, which that code does not compute.
- **Fix:** recorded here; Phase 2 reuses that module's closing fields (RULES Appendix D).

## E-004 · 2026-10-23 · Phase 2 `src/bethero_nba/validate.py` (`b81e17f`)

- **Wrong:**
  1. `model_check` carried one season's ratings into the next season's first games until its next refit (up to 49 games), and used results of games earlier on the same date.
  2. `--out` replaced all of `VALIDATION.md`, which would have erased the pre-declared criteria.
  3. It had offsets ±1.5 and no leave-one-season-out bandwidth search, short of what VALIDATION.md §0 declared.
  4. Its residual "SD" was an uncentred root mean square.
- **Impact:** none on any reported number. The harness never ran on real data before it was rewritten. Found while aligning it with §0.
- **Fix:** rewritten in `68696d8`. Walk-forward within each season uses earlier dates only, results go below a marker, the declared offsets and V1 are in, and the SD is centred. Tests are in `tests/test_validation.py`.

## E-005 · 2026-10-23 · README after the us2 change (`b529ba6`)

- **Wrong:** the README still said a `--live` pull costs 3 credits and listed region `us` (about 9 books) under current limits. With regions us,us2 a pull costs 6 credits.
- **Impact:** documentation only. The budget guard computes the cost from the config (regions × markets), so no pull was budgeted wrongly.
- **Fix:** README updated with 0.5.0.

## E-006 · 2026-10-23 · Phase 3 reply and config 0.5.0, `model.status`

- **Wrong:** the Phase 3 reply offered the veto model as a plain choice between OFF and ON, and config 0.5.0 labelled `model.status` `CONFIRM`, whose definition is "the value shown is the stricter default".
  1. ON is not a switch yet: `analyze` passes no model to the engine, so setting ON would change nothing until this season's results are collected and the fit is wired in.
  2. OFF is not the stricter value: a model that is on can only block or downgrade, never add.
- **Impact:** none on any number, gate or stake. The model has never run in a pass. It could have led Eric to choose ON expecting an immediate effect.
- **Fix:** config 0.5.1 labels it `RULE` with an accurate source; RULES R-8.5, README and VALIDATION.md §1 state what turning it on needs; the follow-up reply explains both points.

## E-007 · 2026-10-24 · Phase 3 `dist.anchor` (Tier B anchoring)

- **Wrong:** `anchor` searched for the root in one fixed window of ±15 points around the US reference line. For a big line (SAS@DAL, home +15.5 on 2026-10-24), the window's far end asked the empirical family, the comparison model, about 30-point lines it has no history for. Anchoring raised an error, and Tier B failed closed with `NB-TIER-C`, although the root lies within a point of the line.
- **Impact:**
  - One market in the 2026-10-24 ET pass: the SAS@DAL handicap logged `NB-TIER-C` first.
  - Re-run on the stored snapshot with the fix, it is priced at Tier B: SAS 15平, EV +0.7% ± 3.3%, still `NB-STATUS` and below `min_ev`.
  - No bet, stake or validated number changed. Bisection has a unique root, so every line that anchored before anchors to the same point.
- **Fix:** the root is searched in the narrowest window around the line that brackets it (±3, then ±6, then ±15). Test `test_anchoring_a_big_line_stays_inside_the_history`.

## E-008 · 2026-10-27 · Reply recommending API-Sports for player minutes

- **Wrong:** recommended API-Sports API-NBA as the free minutes source for R-9.3 and estimated 5–15 requests a day, one per listed player. It relied on a getting-started guide's summary ("100 requests a day, all endpoints") and did not establish the free plan's season and date limits.
- **Correct:** the free plan refuses 2026 season queries (it offers seasons 2022–2024) and any date outside a three-day UTC window, so per-player queries are impossible. And 5 of the 10 team box scores it served for 2026-10-26 UTC left out players. It cannot supply a 10-game average.
- **Impact:** none on any number, gate or stake; no pass read its data, and the reply had said it would be checked before use. Eric opened three domains and registered a key for a source that is not used.
- **Fix:** checked with 11 requests before any use and not adopted (RULES 0.6.2, Appendix B). Minutes then came from Eric's game-log screenshots; since 0.6.3 they come from ESPN's box scores via sportsdataverse (R-9.3).

## E-009 · 2026-10-27 · Reply and RULES 0.6.2: "a screenshot from any site"

- **Wrong:** the reply told Eric a game-log screenshot from any site would do, and R-9.3 and the README said "on any site he browses".
- **Correct:** Sports Reference's terms (clause 5, quoted on its Data Use page, read 2026-10-27) forbid using its content for prompting or instructing AI models, including generating statistics. This project runs through Claude, so Basketball-Reference screenshots are excluded.
- **Impact:** none; no screenshot was sent.
- **Fix:** RULES 0.6.3 R-9.3, the README, the daily-pass skill and the report's request exclude Sports Reference sites.

## E-010 · 2026-10-27 · RULES 0.6.2 Appendix B and the reply on API-Sports

- **Wrong:** said one team's minutes in API-Sports' 2026-10-26 data, 266, exceeded a 240-minute game.
- **Correct:** that game, MIN@CLE, went to overtime (ESPN schedule: 5 periods), so 265 is right; API-Sports' period count of 4 was what was wrong.
- **Impact:** one of the reasons given against API-Sports was misstated. The conclusion stands on its three-day window and the 5 team box scores missing players. No number, gate or stake changed.
- **Fix:** Appendix B corrected in RULES 0.6.3.

## E-011 · 2026-10-28 · Commit `19f740e` (config 0.6.5)

- **Wrong:** pushed a `config.yaml` that does not parse. A source string gained unescaped double quotes, so every command would refuse to load the config. The pre-commit test run was piped through `tail`, so its failure (5 failed, 69 errors) did not stop the commit.
- **Impact:** none on any number, gate, stake or pass. No pass ran on that commit; the next commit fixes it.
- **Fix:** the quotes are single quotes. Checks before a commit are run on their own, so a failure stops the commit.

## E-012 · 2026-10-28 · Phase 3 `src/bethero_nba/dist.py`: the comparison family at large spreads

- **Wrong:**
  - `EmpiricalFamily` said "a symmetric kernel keeps the mixture centred".
  - `anchor` said that P(cover) moves one way as the line moves, so bisection finds the one root.
- **Correct:** neither holds where history is sparse or one-sided.
  - Each bucket enters the mixture with the same weight whatever its size, so at large spreads a few games at nearby lines decide it.
  - VALIDATION.md R8 (2026-10-28), anchored to 0.5 at home lines −20 to +20, found two problems with the empirical family:
    - it cannot be anchored at −20 to −17, +13.5 and +14;
    - it anchors without moving one way at −15.5 to −12.5, +13 and +14.5 to +17.5.
  - 61 of the 336 holdout games with laid lines of 12+ points are at lines where it cannot be anchored.
- **Impact:** no stake. No decision changed.
  - Tier B fails closed where the family cannot be anchored, so the SAC@SAS (2026-10-27) and SAS@UTA (2026-10-28) handicaps were not priced.
  - Where it anchors without moving one way, σ_translate's model term rests on an erratic comparison. Three live markets were priced this way: SAS@DAL +15.5 (10-24 slate), CHI@BOS −14.5 (10-26) and BKN@BOS −12.5 (10-27). Each was a non-bet for other reasons; the best EV was +0.7%.
- **Fix:** the docstrings now say what holds. VALIDATION.md §4 tested a shifted variant; it failed T2 and T3, so production is unchanged (RULES 0.6.6).

