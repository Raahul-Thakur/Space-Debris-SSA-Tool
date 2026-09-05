"""Write screening results to a canonical CSV plus a JSON metadata sidecar.

The CSV is the canonical, machine-readable event table (extends the original
notebook schema with Pc + RAC columns). The JSON captures run metadata and a set
of validation checks so a downstream consumer can trust the report.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from sdebris.config import Config
from sdebris.screening.screen import ScreeningResult

# Canonical column order for the screening CSV.
CSV_COLUMNS = [
    "target_norad", "target_name",
    "secondary_norad", "secondary_name",
    "tca_utc",
    "miss_distance_km", "relative_speed_km_s",
    "radial_km", "along_track_km", "cross_track_km",
    "probability_of_collision",
    "risk_tier", "risk_reason",
    "target_tle_age_days", "secondary_tle_age_days", "secondary_stale",
]


@dataclass(frozen=True)
class ReportPaths:
    csv: Path
    json: Path


def _validation_checks(result: ScreeningResult) -> dict[str, object]:
    df = result.to_dataframe()
    issues: list[str] = []
    if not df.empty:
        if (df["miss_distance_km"] < 0).any():
            issues.append("negative miss distance detected")
        if (df["probability_of_collision"] < 0).any() or (df["probability_of_collision"] > 1).any():
            issues.append("Pc outside [0, 1]")
        if df["secondary_norad"].duplicated().any():
            issues.append("duplicate secondary objects in event list")
    return {
        "passed": not issues,
        "issues": issues,
        "any_stale_secondary": bool(result.n_stale),
    }


def write_report(result: ScreeningResult, config: Config, tag: str | None = None) -> ReportPaths:
    """Write CSV + JSON to the configured output dir. Returns the paths written."""
    out_dir = config.resolve_path(config.reports.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    tag = tag or f"{result.target_norad}_{stamp}"
    csv_path = out_dir / f"screening_{tag}.csv"
    json_path = out_dir / f"screening_{tag}.json"

    df = result.to_dataframe()
    # Ensure the canonical column set/order even when there are no events.
    for col in CSV_COLUMNS:
        if col not in df.columns:
            df[col] = []
    df = df[CSV_COLUMNS] if not df.empty else df.reindex(columns=CSV_COLUMNS)
    df.to_csv(csv_path, index=False)

    metadata = result.metadata()
    metadata["report_csv"] = csv_path.name
    metadata["validation"] = _validation_checks(result)
    metadata["schema_columns"] = CSV_COLUMNS
    json_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")

    return ReportPaths(csv=csv_path, json=json_path)
