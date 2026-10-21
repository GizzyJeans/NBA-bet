"""Bethero NBA: price an Asian platform's NBA lines against the US no-vig consensus.

The rules live in rules/nba/RULES.md and override this code; thresholds live in
rules/nba/config.yaml. Modules:

* `config`     load and check config.yaml
* `teams`      NBA teams: tricode, Odds API name, Chinese name, arena time zone
* `odds`       odds formats, de-vig, split-ticket settlement, EV, Kelly
* `platform`   platform notation and board (screenshot transcription) files
* `net`        the only way code reaches the network (RULES R-4.7)
* `oddsapi`    The Odds API client and quote normalisation
* `consensus`  US consensus per line and Tier A pricing
* `dist`       empirical margin / total distributions and translation (Tier B)
* `injuries`   official injury-report timeline and status gates
* `context`    scenario flags (rest, travel, altitude, NBA Cup, ...)
* `model`      veto-only team ratings
* `bias`       platform bias monitor and persistence tracker
* `edge`       EV, gates G0-G12, Kelly, caps, confidence, reason codes
* `clv`        closing-line value and the pause rule
* `ledger`     SHA-256 hash-chained JSONL ledger
* `report`     Traditional Chinese report
* `validate`   validation harness for VALIDATION.md

Entry points (Windows-friendly): `python -m bethero_nba.analyze`,
`python -m bethero_nba.fetch`, `python -m bethero_nba.settle`.
"""

__version__ = "0.1.0"
