"""Configuration loading — TOML file + env var overrides."""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path

from sfmm.execution.clob import ClobConfig
from sfmm.risk.limits import RiskLimits


@dataclass
class Config:
    clob: ClobConfig
    risk: RiskLimits
    poll_interval_pre: float = 5.0
    poll_interval_live: float = 1.0
    circuit_cooldown_sec: float = 10.0
    max_position_per_market: int = 1000
    min_reward_usd: float = 500.0
    dry_run: bool = False
    sf_api_key: str = ""
    sf_api_url: str = "https://simplefunctions.dev"


def load_config(config_path: str | None = None, dry_run: bool = False) -> Config:
    """Load config from TOML file with env var overrides."""
    toml_data: dict = {}

    if config_path and Path(config_path).exists():
        if sys.version_info >= (3, 11):
            import tomllib
        else:
            try:
                import tomli as tomllib
            except ImportError:
                import tomllib  # type: ignore

        with open(config_path, "rb") as f:
            toml_data = tomllib.load(f)

    quoting = toml_data.get("quoting", {})
    risk_cfg = toml_data.get("risk", {})
    feeds = toml_data.get("feeds", {})

    clob = ClobConfig(
        private_key=os.environ.get("POLYMARKET_PRIVATE_KEY", ""),
        api_key=os.environ.get("POLYMARKET_API_KEY", ""),
        api_secret=os.environ.get("POLYMARKET_API_SECRET", ""),
        api_passphrase=os.environ.get("POLYMARKET_API_PASSPHRASE", ""),
    )

    risk = RiskLimits(
        max_position_per_market=quoting.get("max_position_per_market", 1000),
        max_total_exposure_usd=quoting.get("max_total_exposure_usd", 5000),
        daily_loss_limit_usd=risk_cfg.get("daily_loss_limit_usd", 500),
    )

    return Config(
        clob=clob,
        risk=risk,
        poll_interval_pre=feeds.get("poll_interval_pre", 5.0),
        poll_interval_live=feeds.get("poll_interval_live", 1.0),
        circuit_cooldown_sec=risk_cfg.get("circuit_cooldown_sec", 10.0),
        max_position_per_market=quoting.get("max_position_per_market", 1000),
        min_reward_usd=toml_data.get("markets", {}).get("min_reward_usd", 500),
        dry_run=dry_run,
        sf_api_key=os.environ.get("SF_API_KEY", ""),
        sf_api_url=os.environ.get("SF_API_URL", "https://simplefunctions.dev"),
    )
