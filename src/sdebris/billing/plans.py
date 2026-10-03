"""Plans and the limits that define them.

The free tier is sized to teach: enough screening to see how the pipeline
behaves end to end, on short windows and a handful of objects. The paid tier
lifts the ceiling rather than unlocking a different product, so the limits are
the thing being sold and the science is identical on both sides.

Nothing here is a security boundary. Roles still gate *what* a principal may
do; plans gate *how much*.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Plan(str, Enum):
    FREE = "free"
    PRO = "pro"

    @property
    def label(self) -> str:
        return {"free": "Free", "pro": "Pro"}[self.value]


@dataclass(frozen=True, slots=True)
class PlanLimits:
    """A quota set. ``None`` means the dimension is not capped."""

    #: Screening jobs a principal may start per calendar month, UTC.
    screening_runs_per_month: int | None
    #: Objects a principal may keep on the watch list at once.
    monitored_objects: int | None
    #: Longest look-ahead a single screening run may request, in hours.
    max_window_hours: float | None
    #: Commands per minute, to keep one account from saturating the instance.
    commands_per_minute: int

    def describes_unlimited(self) -> bool:
        return (
            self.screening_runs_per_month is None
            and self.monitored_objects is None
            and self.max_window_hours is None
        )


#: Screening is the expensive, valuable operation, so that is what the paid
#: tier buys more of. The watch list is only propagation for display, and the
#: free allowance deliberately clears the 20 objects `monitor seed-known` adds
#: — a new visitor following the tour must not hit a paywall on their first
#: command. The schema already caps a window at 168 hours, so Pro simply gets
#: the full range the propagator supports.
PLAN_LIMITS: dict[Plan, PlanLimits] = {
    Plan.FREE: PlanLimits(
        screening_runs_per_month=5,
        monitored_objects=25,
        max_window_hours=24,
        commands_per_minute=20,
    ),
    Plan.PRO: PlanLimits(
        screening_runs_per_month=500,
        monitored_objects=250,
        max_window_hours=168,
        commands_per_minute=60,
    ),
}


@dataclass(frozen=True, slots=True)
class Offer:
    """A way to buy Pro."""

    code: str
    label: str
    price_usd: float
    #: None for a recurring offer; the grant then carries a renewal date.
    lifetime: bool
    blurb: str


#: Recurring revenue is what makes the platform a sellable asset, so the
#: subscription is the standing offer. The lifetime deal exists only to buy
#: early momentum and social proof, and is capped for that reason: a small
#: grandfathered cohort is acceptable to an acquirer, an all-lifetime customer
#: book is not, because it is future cost with no future revenue attached.
SUBSCRIPTION = Offer(
    code="pro-monthly",
    label="Pro",
    price_usd=6.0,
    lifetime=False,
    blurb="Everything in Pro, billed monthly.",
)
FOUNDING_LIFETIME = Offer(
    code="pro-founding",
    label="Founding lifetime",
    price_usd=29.0,
    lifetime=True,
    blurb="Pro for life. Limited to the first supporters of the project.",
)

#: How many lifetime grants are offered before the deal is withdrawn. The cap
#: is a selling decision enforced at checkout, not at the webhook: once money
#: has changed hands the grant is always honoured.
FOUNDING_SEATS = 100


def limits_for(plan: Plan) -> PlanLimits:
    return PLAN_LIMITS[plan]


def parse_plan(raw: str | None) -> Plan:
    """Read a stored plan name, falling back to free rather than failing."""
    if not raw:
        return Plan.FREE
    try:
        return Plan(raw.strip().lower())
    except ValueError:
        return Plan.FREE
