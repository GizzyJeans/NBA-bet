"""Shared command-line plumbing for the `python -m bethero_nba.<command>` entry points."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from . import config

API_KEY_ENV = "ODDS_API_KEY"


def setup_output() -> None:
    """Print UTF-8 even on a Windows console or a redirected cp950 stream."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass


def add_root(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--root", type=Path, default=None,
                        help="repository root (default: nearest folder above the current one "
                             "that holds rules/nba/config.yaml)")


def resolve_root(arg: Path | None) -> Path:
    return arg.resolve() if arg else config.find_root()


def load_config(root: Path) -> config.Config:
    return config.load(root / config.CONFIG_RELATIVE)


def api_key() -> str:
    key = os.environ.get(API_KEY_ENV, "").strip()
    if not key:
        raise SystemExit(f"{API_KEY_ENV} is not set")
    return key
