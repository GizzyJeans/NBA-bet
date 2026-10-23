"""CLAUDE.md and the project skills cite only rules, codes and settings that exist."""

import re

import pytest

GUIDES = ["CLAUDE.md", ".claude/skills/nba-daily-pass/SKILL.md", ".claude/skills/nba-rule-change/SKILL.md"]


@pytest.mark.parametrize("name", GUIDES)
def test_guides_cite_what_exists(name, root, cfg):
    text = (root / name).read_text(encoding="utf-8")
    rules = (root / "rules" / "nba" / "RULES.md").read_text(encoding="utf-8")
    defined = set(re.findall(r"\*\*(R-\d+\.\d+)\*\*", rules))
    assert set(re.findall(r"R-\d+\.\d+", text)) <= defined
    for code in re.findall(r"NB-[A-Z-]+[A-Z]", text):
        assert f"`{code}`" in rules, code
    for key in re.findall(r"`((?:snapshots|us_odds|injuries|golive|model|tiers|distribution|anchor|clv)\.[a-z_]+)", text):
        cfg.get(key)                                   # raises on an unknown key


@pytest.mark.parametrize("name", GUIDES[1:])
def test_skills_have_frontmatter(name, root):
    text = (root / name).read_text(encoding="utf-8")
    head = text.split("---")[1]
    assert re.search(r"^name: nba-[a-z-]+$", head, re.M) and re.search(r"^description: .{40,}", head, re.M)
