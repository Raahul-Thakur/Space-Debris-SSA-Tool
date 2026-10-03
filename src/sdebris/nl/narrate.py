"""Turn a computed conjunction into sentences a learner can follow.

Every sentence is derived from numbers the pipeline already produced. Nothing
here estimates, rounds toward a conclusion, or infers physics — if a value is
missing the sentence is omitted rather than guessed at. That constraint is the
whole point: the narration has to be as trustworthy as the computation, and a
language model asked to "explain a conjunction" will happily invent the parts
it does not have.

A model can later rewrite these sentences for fluency. It must not be the
thing that decides what they say.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

#: Earth's equatorial radius, for expressing a miss distance in familiar terms.
EARTH_RADIUS_KM = 6378.137


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _parse(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return _aware(value)
    if isinstance(value, str):
        try:
            return _aware(datetime.fromisoformat(value.replace("Z", "+00:00")))
        except ValueError:
            return None
    return None


def _hours_until(moment: datetime | None, now: datetime) -> float | None:
    if moment is None:
        return None
    return (moment - now).total_seconds() / 3600


def _describe_pc(pc: float | None) -> str | None:
    if pc is None:
        return None
    if pc <= 0:
        return (
            "The estimated probability of collision rounds to zero, which means "
            "the miss distance is large compared with the assumed position "
            "uncertainty — not that a collision is impossible."
        )
    odds = round(1 / pc) if pc > 0 else None
    scale = f"roughly a 1 in {odds:,} chance" if odds and odds > 1 else "a near-certainty"
    return (
        f"The estimated probability of collision is {pc:.2e}, {scale} on this "
        "model's assumptions."
    )


def narrate_event(
    explanation: dict[str, Any],
    *,
    tle_epoch: datetime | None = None,
    now: datetime | None = None,
) -> list[str]:
    """Sentences explaining one event, ordered from what to why to caveat.

    ``explanation`` is the payload `_event_explanation` already returns.
    """
    moment = now or datetime.now(timezone.utc)
    primary = (explanation.get("primary") or {}).get("name") or "the primary object"
    secondary = (explanation.get("secondary") or {}).get("name") or "the secondary object"
    miss = explanation.get("miss_distance_km")
    speed = explanation.get("relative_speed_km_s")
    tier = str(explanation.get("tier") or "unassessed")
    pc = explanation.get("probability_of_collision")
    tca = _parse(explanation.get("tca"))

    lines: list[str] = []

    # 1. What happens.
    if isinstance(miss, (int, float)):
        headline = (
            f"{primary} and {secondary} are predicted to pass within "
            f"{miss:.3f} km of each other"
        )
        hours = _hours_until(tca, moment)
        if hours is not None:
            if hours < 0:
                headline += f", which already happened {abs(hours):.1f} hours ago"
            elif hours < 48:
                headline += f", in about {hours:.1f} hours"
            else:
                headline += f", in about {hours / 24:.1f} days"
        lines.append(headline + ".")

    # 2. How fast, which is what turns a near miss into an energetic one.
    if isinstance(speed, (int, float)) and speed > 0:
        lines.append(
            f"They close at {speed:.2f} km/s, so the whole encounter resolves in "
            "under a second and there is no opportunity to react during it. "
            "Anything done about it has to be done in advance."
        )

    # 3. Why that tier.
    reason = explanation.get("explanation")
    if isinstance(reason, str) and reason.strip():
        # The stored reason is a terse machine string like
        # "CRITICAL: miss 0.41 km <= 1 km"; quote it rather than trying to
        # re-case it into a sentence.
        lines.append(f"It is classified {tier}. The rule that fired was: {reason.strip()}")
    elif tier != "unassessed":
        lines.append(f"It is classified {tier}.")

    # 4. What the probability means.
    described = _describe_pc(pc if isinstance(pc, (int, float)) else None)
    if described:
        lines.append(described)

    # 5. How much to trust it.
    if tle_epoch is not None:
        age_days = (moment - _aware(tle_epoch)).total_seconds() / 86400
        confidence = (
            "recent enough for the propagation to be meaningful"
            if age_days <= 3
            else "old enough that the predicted position has drifted appreciably"
        )
        lines.append(
            f"The orbit used here came from an element set {age_days:.1f} days "
            f"old, which is {confidence}. Two-line element accuracy decays with "
            "age and after any manoeuvre."
        )

    model = explanation.get("model_version")
    lines.append(
        "The covariance behind this probability is synthetic rather than taken "
        "from an operator's conjunction data message"
        + (f" (model {model})" if model else "")
        + ", so treat the number as a demonstration of how the calculation "
        "behaves, not as grounds for a manoeuvre."
    )
    return lines
