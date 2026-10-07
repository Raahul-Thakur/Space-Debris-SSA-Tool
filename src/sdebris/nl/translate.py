"""Turn a plain-English request into an allowlisted command.

The translator only ever *proposes*. Whatever it produces is parsed by
`sdebris.commands.parser` before it is offered to the operator, and executed
only when the operator confirms it, so this module cannot widen what the
platform is able to do. That property is what makes it safe to put a language
model behind it later: the model's output is a suggestion that still has to
survive the same grammar as anything typed by hand.

Rules run first and answer most phrasings at no cost. A model, when one is
configured, is the fallback for the rest.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from sdebris.commands.parser import CommandParseError, parse_command
from sdebris.nl.catalog import resolve_object

Source = Literal["rules", "model", "none"]

#: Cap suggested windows at the parser's own maximum.
MAX_WINDOW_HOURS = 168


@dataclass(frozen=True, slots=True)
class Suggestion:
    """A proposed command, with the reasoning shown to the operator."""

    command: str | None
    source: Source
    rationale: str
    #: Set when the proposal failed to parse, which should never reach the UI.
    error: str | None = None

    @property
    def understood(self) -> bool:
        return self.command is not None


def _window_hours(
    text: str, ceiling: float = MAX_WINDOW_HOURS
) -> tuple[float, str] | None:
    """Parse a look-ahead from the phrase, never exceeding ``ceiling``.

    The ceiling is the caller's plan limit, not only the grammar's. Proposing
    a window the plan will refuse produces a command that reads as correct and
    then fails with a payment prompt the moment it runs, which makes the
    interpreter look broken rather than the plan look limited. Clamping here
    and saying so keeps the proposal runnable.
    """
    lowered = text.lower()
    limit = min(ceiling, MAX_WINDOW_HOURS)

    def capped(hours: float, label: str) -> tuple[float, str]:
        fitted = min(hours, limit)
        note = f"{label} → {fitted:g}h"
        if fitted < hours:
            note += f" (capped: your plan screens up to {limit:g}h)"
        return fitted, note

    explicit = re.search(r"(\d+(?:\.\d+)?)\s*(hour|hr|h|day|d|week|w)s?\b", lowered)
    if explicit:
        amount = float(explicit.group(1))
        unit = explicit.group(2)
        hours = amount * {"hour": 1, "hr": 1, "h": 1, "day": 24, "d": 24, "week": 168, "w": 168}[unit]
        return capped(hours, explicit.group(0).strip())

    for phrase, hours in (
        ("next week", 168),
        ("this week", 168),
        ("coming week", 168),
        ("fortnight", 168),
        ("tomorrow", 48),
        ("today", 24),
        ("tonight", 12),
        ("right now", 6),
        ("next few days", 72),
        ("few days", 72),
    ):
        if phrase in lowered:
            return capped(float(hours), f"'{phrase}'")
    return None


def _threshold_km(text: str) -> tuple[float, str] | None:
    match = re.search(
        r"(?:within|under|closer than|inside|below)\s*(\d+(?:\.\d+)?)\s*(km|kilometre|kilometer|m|metre|meter)s?\b",
        text.lower(),
    )
    if not match:
        return None
    amount = float(match.group(1))
    if match.group(2).startswith("m") and not match.group(2).startswith("km"):
        amount /= 1000
    return amount, f"'{match.group(0).strip()}' → {amount:g}km"


def _tier(text: str) -> str | None:
    lowered = text.lower()
    for tier in ("critical", "watch", "nominal"):
        if tier in lowered:
            return tier
    if "danger" in lowered or "risky" in lowered or "urgent" in lowered:
        return "critical"
    return None


def _mentions(text: str, *words: str) -> bool:
    lowered = text.lower()
    return any(word in lowered for word in words)


def suggest_from_rules(
    text: str, *, max_window_hours: float = MAX_WINDOW_HOURS
) -> Suggestion:
    """Best-effort translation without a model.

    ``max_window_hours`` is the caller's plan ceiling. It only ever narrows
    the proposal, so a caller that does not know the plan still gets a
    command the grammar accepts.
    """
    cleaned = text.strip()
    if not cleaned:
        return Suggestion(None, "none", "Nothing to interpret.")

    reasons: list[str] = []
    target = resolve_object(cleaned)

    # Ordered by specificity: a phrase mentioning both an object and a risk
    # word is a screening request, not a listing request.
    wants_screen = _mentions(
        cleaned,
        "screen",
        "close approach",
        "conjunction",
        "collision",
        "encounter",
        "how close",
        "near miss",
        "pass close",
        "danger",
        "dangerous",
        "risk",
        "risky",
        "safe",
        "at risk",
    )
    wants_watch = _mentions(cleaned, "monitor", "watch", "track", "follow", "add")
    wants_events = _mentions(cleaned, "list", "show me all", "what events", "events")
    wants_refresh = _mentions(cleaned, "refresh", "update the orbit", "latest tle", "new elements")
    wants_explain = _mentions(cleaned, "explain", "why is", "what does this mean")

    if wants_explain:
        return Suggestion(
            None,
            "rules",
            "Explanations are opened from an event, not typed: select a "
            "conjunction in the inspector and use Explain event.",
        )

    if wants_refresh and target:
        reasons.append(target[1])
        return _validated(f"orbit refresh {target[0]}", reasons)

    if wants_screen and target:
        reasons.append(target[1])
        return _validated(_screen_command(cleaned, target[0], reasons, max_window_hours), reasons)

    if wants_watch and target:
        reasons.append(target[1])
        return _validated(f"monitor add {target[0]}", reasons)

    if wants_events:
        tier = _tier(cleaned)
        if tier:
            reasons.append(f"'{tier}' → --tier {tier}")
            return _validated(f"events list --tier {tier}", reasons)
        return _validated("events list", reasons)

    if _mentions(cleaned, "seed", "starter", "started", "some objects", "set me up"):
        return _validated("monitor seed-known", ["Loads the starter watch list."])

    if target and not (wants_screen or wants_watch):
        # An object with no verb is most usefully read as "look at this".
        reasons.append(target[1])
        reasons.append("No action word found, so this was read as a screening request.")
        return _validated(_screen_command(cleaned, target[0], reasons, max_window_hours), reasons)

    return Suggestion(
        None,
        "rules",
        "Could not tell which object or action was meant. Naming a satellite "
        "and what to do with it usually works, for example "
        "'close approaches for the ISS this week'.",
    )


def _screen_command(
    text: str, norad: str, reasons: list[str], max_window_hours: float
) -> str:
    """Build a screening command, carrying over any window or threshold given."""
    parts = [f"screen {norad}"]
    window = _window_hours(text, max_window_hours)
    if window:
        parts.append(f"--window {window[0]:g}h")
        reasons.append(window[1])
    threshold = _threshold_km(text)
    if threshold:
        parts.append(f"--threshold {threshold[0]:g}km")
        reasons.append(threshold[1])
    return " ".join(parts)


def _validated(command: str, reasons: list[str]) -> Suggestion:
    """Refuse to propose anything the real parser would reject."""
    try:
        parse_command(command)
    except (CommandParseError, PermissionError) as exc:
        return Suggestion(
            None,
            "rules",
            "That request translated to a command the platform does not allow.",
            error=str(exc),
        )
    return Suggestion(command, "rules", " · ".join(reasons) if reasons else "Direct match.")
