"""Names people actually type, mapped to catalogue numbers.

Only well-known objects belong here. Anything else has to be given by NORAD
id, because guessing at a satellite's identity from a partial name is exactly
the kind of confident wrongness this tool should not produce.
"""

from __future__ import annotations

import re

#: Aliases are matched case-insensitively on word boundaries, longest first, so
#: "sentinel 2a" wins over "sentinel".
OBJECT_ALIASES: dict[str, str] = {
    "iss": "25544",
    "zarya": "25544",
    "international space station": "25544",
    "space station": "25544",
    "css": "48274",
    "tianhe": "48274",
    "chinese space station": "48274",
    "hubble": "20580",
    "hst": "20580",
    "hubble space telescope": "20580",
    "landsat 8": "39084",
    "landsat 9": "49260",
    "terra": "25994",
    "aqua": "27424",
    "sentinel 1a": "39634",
    "sentinel 2a": "40697",
    "sentinel 2b": "42063",
    "sentinel 3a": "41335",
    "sentinel 3b": "43437",
    "goes 16": "41866",
    "goes 17": "43226",
    "goes 18": "51850",
    "noaa 15": "25338",
    "noaa 18": "28654",
    "noaa 19": "33591",
    "noaa 20": "43013",
    "envisat": "27386",
    "vanguard 1": "00005",
    "vanguard": "00005",
}

#: Canonical display names, for explaining a resolution back to the operator.
OBJECT_NAMES: dict[str, str] = {
    "25544": "ISS (ZARYA)",
    "48274": "CSS (TIANHE)",
    "20580": "HUBBLE SPACE TELESCOPE",
    "39084": "LANDSAT 8",
    "49260": "LANDSAT 9",
    "25994": "TERRA",
    "27424": "AQUA",
    "39634": "SENTINEL-1A",
    "40697": "SENTINEL-2A",
    "42063": "SENTINEL-2B",
    "41335": "SENTINEL-3A",
    "43437": "SENTINEL-3B",
    "41866": "GOES 16",
    "43226": "GOES 17",
    "51850": "GOES 18",
    "25338": "NOAA 15",
    "28654": "NOAA 18",
    "33591": "NOAA 19",
    "43013": "NOAA 20",
    "27386": "ENVISAT",
    "00005": "VANGUARD 1",
}

#: Quantities like "10 km" or "3 days" are stripped before hunting for a bare
#: catalogue number, otherwise the magnitude gets mistaken for the object.
_QUANTITY = re.compile(
    r"\b\d+(?:\.\d+)?\s*(?:km|kilometres?|kilometers?|m|metres?|meters?|"
    r"hours?|hrs?|h|days?|d|weeks?|w)\b",
    re.IGNORECASE,
)
#: An explicit catalogue reference, which beats everything else.
_EXPLICIT = re.compile(
    r"(?:norad|catalogue|catalog|sat(?:ellite)?\s+id|#)"
    r"(?:\s+(?:number|id|no))?\s*(\d{1,5})",
    re.IGNORECASE,
)
_BARE_ID = re.compile(r"\b(\d{4,5})\b")


def _normalise(text: str) -> str:
    # Punctuation and hyphenation vary wildly in how people write these names.
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def resolve_object(text: str) -> tuple[str, str] | None:
    """Find the object a phrase refers to, as ``(norad_id, how_it_matched)``.

    Resolution order matters. An explicit catalogue reference is unambiguous
    and wins outright. A known name comes next, because names like "LANDSAT 8"
    contain digits that would otherwise be read as an id. Only then is a bare
    number considered, and only if it is long enough to plausibly be one.
    """
    explicit = _EXPLICIT.search(text)
    if explicit:
        norad = explicit.group(1)
        return norad, f"NORAD {norad}"

    haystack = _normalise(text)
    for alias in sorted(OBJECT_ALIASES, key=len, reverse=True):
        if re.search(rf"\b{re.escape(alias)}\b", haystack):
            norad = OBJECT_ALIASES[alias]
            return norad, f"{OBJECT_NAMES.get(norad, alias)} → NORAD {norad}"

    # Nothing named, so fall back to a bare number — but not one that is really
    # a distance, a duration or a year.
    without_quantities = _QUANTITY.sub(" ", text)
    for candidate in _BARE_ID.findall(without_quantities):
        if len(candidate) == 4 and 1900 <= int(candidate) <= 2100:
            continue
        return candidate, f"NORAD {candidate}"
    return None
