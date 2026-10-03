"""Natural-language helpers that propose, but never widen, allowlisted actions."""

from sdebris.nl.catalog import OBJECT_ALIASES, OBJECT_NAMES, resolve_object
from sdebris.nl.narrate import narrate_event
from sdebris.nl.translate import Suggestion, suggest_from_rules

__all__ = [
    "OBJECT_ALIASES",
    "OBJECT_NAMES",
    "Suggestion",
    "narrate_event",
    "resolve_object",
    "suggest_from_rules",
]
