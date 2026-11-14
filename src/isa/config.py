"""Configuration loading. All tunables live in config/*.toml, never in code."""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = ROOT / "config"


def _load(name: str, config_dir: Path) -> dict:
    with open(config_dir / f"{name}.toml", "rb") as fh:
        return tomllib.load(fh)


@dataclass(frozen=True)
class Config:
    weights: dict
    thresholds: dict
    valuation: dict
    tax: dict

    @classmethod
    def load(cls, config_dir: Path | None = None) -> "Config":
        d = Path(config_dir) if config_dir else CONFIG_DIR
        return cls(
            weights=_load("weights", d),
            thresholds=_load("thresholds", d),
            valuation=_load("valuation", d),
            tax=_load("tax", d),
        )


def db_path() -> Path:
    """Database path: ISA_DB_PATH if set, else data/isa.db in the repo."""
    raw = os.environ.get("ISA_DB_PATH")
    if raw:
        p = Path(raw)
        return p if p.is_absolute() else ROOT / p
    return ROOT / "data" / "isa.db"
