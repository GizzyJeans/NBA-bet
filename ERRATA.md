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
