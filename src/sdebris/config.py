"""Typed configuration model and YAML loader.

The whole pipeline is driven by a single :class:`Config` object so that the CLI,
the Streamlit app, and the scheduled job all behave identically. Defaults live in
``configs/default.yaml`` and any field can be overridden by a user-supplied YAML.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field

# Repository root resolved relative to this file: src/sdebris/config.py -> repo/
PACKAGE_ROOT = Path(__file__).resolve().parent
REPO_ROOT = PACKAGE_ROOT.parent.parent
DEFAULT_CONFIG_PATH = REPO_ROOT / "configs" / "default.yaml"


class IngestionConfig(BaseModel):
    default_group: str = "iridium-33-debris"
    base_url: str = "https://celestrak.org/NORAD/elements/gp.php"
    cache_path: str = "data/cache/tle_cache.sqlite"
    poll_interval_hours: float = 2.0
    stale_after_days: float = 5.0


class PropagationConfig(BaseModel):
    window_hours: float = 72.0
    step_sec: int = 60
    refine_step_sec: int = 1


class ScreeningConfig(BaseModel):
    coarse_threshold_km: float = 50.0
    report_threshold_km: float = 25.0


class AgeGrowth(BaseModel):
    radial: float = 20.0
    intrack: float = 400.0
    crosstrack: float = 30.0


class TierThreshold(BaseModel):
    miss_distance_km: float
    probability_of_collision: float


class RiskTiers(BaseModel):
    critical: TierThreshold = TierThreshold(miss_distance_km=1.0, probability_of_collision=1e-4)
    watch: TierThreshold = TierThreshold(miss_distance_km=5.0, probability_of_collision=1e-5)


class RiskConfig(BaseModel):
    hard_body_radius_m: float = 20.0
    sigma_radial_m: float = 50.0
    sigma_intrack_m: float = 200.0
    sigma_crosstrack_m: float = 50.0
    age_growth_m_per_day: AgeGrowth = Field(default_factory=AgeGrowth)
    tiers: RiskTiers = Field(default_factory=RiskTiers)


class ReportsConfig(BaseModel):
    output_dir: str = "data/reports"


class OntologyConfig(BaseModel):
    database_url: str = "sqlite:///data/ontology.sqlite"


class EmailConfig(BaseModel):
    enabled: bool = False
    sender: str = "ssa-bot@example.com"
    recipients: list[str] = Field(default_factory=list)


class WebhookConfig(BaseModel):
    enabled: bool = False
    url: str = ""


class AlertsConfig(BaseModel):
    enabled: bool = False
    cooldown_hours: float = 6.0
    email: EmailConfig = Field(default_factory=EmailConfig)
    webhook: WebhookConfig = Field(default_factory=WebhookConfig)


class Config(BaseModel):
    ingestion: IngestionConfig = Field(default_factory=IngestionConfig)
    propagation: PropagationConfig = Field(default_factory=PropagationConfig)
    screening: ScreeningConfig = Field(default_factory=ScreeningConfig)
    risk: RiskConfig = Field(default_factory=RiskConfig)
    reports: ReportsConfig = Field(default_factory=ReportsConfig)
    ontology: OntologyConfig = Field(default_factory=OntologyConfig)
    alerts: AlertsConfig = Field(default_factory=AlertsConfig)

    def resolve_path(self, value: str) -> Path:
        """Resolve a config path against the repo root unless it is absolute."""
        path = Path(value)
        return path if path.is_absolute() else REPO_ROOT / path


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        if key in merged and isinstance(merged[key], dict) and isinstance(value, dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def load_config(path: str | Path | None = None) -> Config:
    """Load configuration, merging an optional override file over the defaults."""
    data: dict[str, Any] = {}
    if DEFAULT_CONFIG_PATH.exists():
        data = yaml.safe_load(DEFAULT_CONFIG_PATH.read_text(encoding="utf-8")) or {}
    if path is not None:
        override = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
        data = _deep_merge(data, override)
    return Config.model_validate(data)
