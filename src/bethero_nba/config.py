"""Load and check rules/nba/config.yaml.

Every setting is a mapping with `value`, `status` and `source`; UNVALIDATED
settings also carry a `rationale` (RULES §0.1). Code reads values only through
`Config.get`, so a key nobody wrote down fails loudly instead of quietly
falling back to a default that has no provenance.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

STATUSES = frozenset({
    "CONFIRMED", "CONFIRM", "VALIDATED", "UNVALIDATED", "UNCONFIRMED", "FACT", "RULE",
})
CONFIG_RELATIVE = Path("rules") / "nba" / "config.yaml"


class ConfigError(ValueError):
    """The config is missing, malformed, or asked for a key it does not have."""


def is_setting(node: Any) -> bool:
    return isinstance(node, dict) and "value" in node and isinstance(node.get("status"), str)


def _dig(value: Any, parts: list[str], key: str) -> Any:
    for part in parts:
        if not isinstance(value, dict) or part not in value:
            raise ConfigError(f"unknown config key {key!r}")
        value = value[part]
    return value


@dataclass(frozen=True)
class Config:
    data: dict
    path: Path | None = None

    @property
    def version(self) -> str:
        return str(self.data["meta"]["version"])

    def setting(self, key: str) -> dict:
        """The full setting (value, status, source) for a dotted key.

        A key may reach inside a structured value, e.g.
        ``tiers.tier_b_max_gap.spread``; the status and source are those of the
        enclosing setting.
        """
        node: Any = self.data
        parts = key.split(".")
        for i, part in enumerate(parts):
            if is_setting(node):
                return {**node, "value": _dig(node["value"], parts[i:], key)}
            if not isinstance(node, dict) or part not in node:
                raise ConfigError(f"unknown config key {key!r}")
            node = node[part]
        if not is_setting(node):
            raise ConfigError(f"{key!r} is a section, not a setting")
        return node

    def get(self, key: str) -> Any:
        return self.setting(key)["value"]

    def status(self, key: str) -> str:
        return self.setting(key)["status"]

    def problems(self) -> list[str]:
        """Every way the config breaks the RULES §0.1 contract."""
        found: list[str] = []

        def walk(node: Any, path: str) -> None:
            if is_setting(node):
                for field in ("value", "status", "source"):
                    if field not in node:
                        found.append(f"{path}: missing {field}")
                if node["status"] not in STATUSES:
                    found.append(f"{path}: unknown status {node['status']!r}")
                if node["status"] == "UNVALIDATED" and not node.get("rationale"):
                    found.append(f"{path}: UNVALIDATED without a rationale")
                return
            if isinstance(node, dict):
                for key, child in node.items():
                    walk(child, f"{path}.{key}" if path else str(key))
                return
            found.append(f"{path}: bare value {node!r} without status and source")

        if "meta" not in self.data or "version" not in self.data["meta"]:
            found.append("meta.version missing")
        for key, child in self.data.items():
            if key != "meta":
                walk(child, key)
        return found


def find_root(start: Path | None = None) -> Path:
    """The repository root: the nearest ancestor holding rules/nba/config.yaml."""
    here = (start or Path.cwd()).resolve()
    for candidate in (here, *here.parents):
        if (candidate / CONFIG_RELATIVE).is_file():
            return candidate
    raise ConfigError(f"no {CONFIG_RELATIVE.as_posix()} at or above {here}")


def load(path: Path | str | None = None) -> Config:
    """Load and check the config; refuse to run on a config that breaks the contract."""
    cfg_path = Path(path) if path else find_root() / CONFIG_RELATIVE
    try:
        data = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ConfigError(f"cannot read {cfg_path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ConfigError(f"{cfg_path} is not a mapping")
    config = Config(data, cfg_path)
    problems = config.problems()
    if problems:
        raise ConfigError(f"{cfg_path}: " + "; ".join(problems))
    return config
