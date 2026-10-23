import re

import pytest

from bethero_nba.config import Config, ConfigError, find_root


def test_repository_config_honours_the_contract(cfg):
    assert cfg.problems() == []
    assert cfg.version


def test_get_reaches_inside_structured_values(cfg):
    assert cfg.get("tiers.tier_b_max_gap.spread") == 1.5
    assert cfg.status("tiers.tier_b_max_gap.spread") == "VALIDATED"
    assert cfg.get("distribution.selected_method.total") == "normal"
    assert cfg.get("risk.bankroll") == 100000


def test_unknown_keys_and_sections_fail_loudly(cfg):
    with pytest.raises(ConfigError):
        cfg.get("gates.no_such_key")
    with pytest.raises(ConfigError):
        cfg.get("gates")


def test_contract_violations_are_reported():
    bad = Config({
        "meta": {"version": "0"},
        "a": {"value": 1, "status": "UNVALIDATED", "source": "x"},
        "b": {"value": 1, "status": "MAYBE", "source": "x"},
        "c": 3,
    })
    problems = " | ".join(bad.problems())
    assert "a: UNVALIDATED without a rationale" in problems
    assert "unknown status 'MAYBE'" in problems
    assert "c: bare value" in problems


def test_every_cfg_reference_in_the_rules_resolves(cfg, root):
    rules = (root / "rules" / "nba" / "RULES.md").read_text(encoding="utf-8")
    keys = set(re.findall(r"cfg:([a-z_][a-z0-9_.]*[a-z0-9_])", rules)) - {"section.key"}
    unresolved = []
    for key in sorted(keys):
        try:
            cfg.setting(key)
        except ConfigError:
            try:                                   # a reference to a whole section
                node = cfg.data
                for part in key.split("."):
                    node = node[part]
            except (KeyError, TypeError):
                unresolved.append(key)
    assert unresolved == []


def test_find_root_walks_up(root):
    assert find_root(root / "src" / "bethero_nba") == root
