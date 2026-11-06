"""The CelesTrak groups a screening may run against.

``--group`` used to accept any string, and CelesTrak's larger groups are
large: ``active`` is around eleven thousand objects, which propagated over a
72-hour window is several gigabytes of state vectors on an instance with
512 MB. An allow-list keeps a screening to catalogues of debris-cloud size.
The job-size cap in ``sdebris.jobs.manager`` is the second line, for a group
that grows.
"""

from __future__ import annotations

#: Group name -> what it holds. All are CelesTrak GP group names.
SCREENING_GROUPS: dict[str, str] = {
    "iridium-33-debris": "Debris from the 2009 Iridium 33 / Cosmos 2251 collision (Iridium side)",
    "cosmos-2251-debris": "Debris from the 2009 Iridium 33 / Cosmos 2251 collision (Cosmos side)",
    "cosmos-1408-debris": "Debris from the 2021 Cosmos 1408 anti-satellite test",
    "stations": "Crewed stations and the objects around them",
    "visual": "The brightest objects, visible to the naked eye",
    "last-30-days": "Objects launched in the last 30 days",
}

DEFAULT_GROUP = "iridium-33-debris"


def check_group(group: str) -> str:
    """Return ``group`` if screenings may use it, else raise ``ValueError``."""
    if group not in SCREENING_GROUPS:
        raise ValueError(
            f"unknown catalogue group {group!r}; choose one of "
            + ", ".join(sorted(SCREENING_GROUPS))
        )
    return group
