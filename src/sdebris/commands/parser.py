"""Allowlisted command grammar for the operator console.

This parser produces typed action plans. It deliberately has no facility for
executing programs or forwarding arbitrary arguments to a shell.
"""

from __future__ import annotations

import re
import shlex
from typing import Any

from sdebris.ontology.enums import OperatorRole
from sdebris.ontology.schemas import CommandPlan


class CommandParseError(ValueError):
    """Raised when operator input does not match the allowlisted grammar."""


ROLE_RANK = {
    OperatorRole.VIEWER: 0,
    OperatorRole.ANALYST: 1,
    OperatorRole.OPERATOR: 2,
    OperatorRole.ADMIN: 3,
}

COMMAND_HELP = [
    "screen 25544 --window 72h --threshold 25km",
    "monitor add 20580",
    "monitor seed-known",
    "events list --tier critical",
    "case assign <case-id> analyst-1",
    'case close <case-id> --reason "Risk resolved"',
    "event explain <event-id>",
    "orbit refresh 25544",
]


def _number_with_unit(value: str, units: dict[str, float], name: str) -> float:
    match = re.fullmatch(r"(\d+(?:\.\d+)?)([a-zA-Z]+)?", value)
    if not match:
        raise CommandParseError(f"{name} must be a number followed by {', '.join(units)}")
    unit = match.group(2) or next(iter(units))
    if unit not in units:
        raise CommandParseError(f"unsupported {name} unit: {unit}")
    return float(match.group(1)) * units[unit]


def _options(tokens: list[str], allowed: set[str]) -> dict[str, str | bool]:
    parsed: dict[str, str | bool] = {}
    index = 0
    while index < len(tokens):
        key = tokens[index]
        if key not in allowed:
            raise CommandParseError(f"unknown option: {key}")
        if key in {"--cached"}:
            parsed[key] = True
            index += 1
            continue
        if index + 1 >= len(tokens) or tokens[index + 1].startswith("--"):
            raise CommandParseError(f"{key} requires a value")
        parsed[key] = tokens[index + 1]
        index += 2
    return parsed


def _plan(
    action: str,
    arguments: dict[str, Any],
    required_role: OperatorRole,
    asynchronous: bool = False,
) -> CommandPlan:
    return CommandPlan(
        action=action,
        arguments=arguments,
        required_role=required_role,
        asynchronous=asynchronous,
    )


def parse_command(raw: str, role: OperatorRole = OperatorRole.OPERATOR) -> CommandPlan:
    try:
        tokens = shlex.split(raw, posix=True)
    except ValueError as exc:
        raise CommandParseError(str(exc)) from exc
    if not tokens:
        raise CommandParseError("enter a command")

    plan: CommandPlan
    if tokens[0] == "screen":
        if len(tokens) < 2 or not tokens[1].isdigit():
            raise CommandParseError("usage: screen NORAD [--window 72h] [--threshold 25km]")
        opts = _options(
            tokens[2:], {"--window", "--threshold", "--step", "--group", "--cached"}
        )
        plan = _plan(
            "screen",
            {
                "norad_id": tokens[1],
                "window_hours": _number_with_unit(
                    str(opts.get("--window", "72h")), {"h": 1, "d": 24}, "window"
                ),
                "threshold_km": _number_with_unit(
                    str(opts.get("--threshold", "25km")), {"km": 1, "m": 0.001}, "threshold"
                ),
                "step_sec": int(
                    _number_with_unit(
                        str(opts.get("--step", "60s")), {"s": 1, "m": 60}, "step"
                    )
                ),
                "group": str(opts.get("--group", "iridium-33-debris")),
                "refresh_catalog": not bool(opts.get("--cached", False)),
                "persist_ontology": True,
            },
            OperatorRole.ANALYST,
            True,
        )
    elif tokens == ["monitor", "seed-known"]:
        plan = _plan("monitor.seed-known", {}, OperatorRole.ANALYST)
    elif tokens[:2] == ["monitor", "add"] and len(tokens) == 3 and tokens[2].isdigit():
        plan = _plan("monitor.add", {"norad_id": tokens[2]}, OperatorRole.ANALYST)
    elif tokens[:2] == ["events", "list"]:
        opts = _options(tokens[2:], {"--tier"})
        plan = _plan("events.list", {"tier": opts.get("--tier")}, OperatorRole.VIEWER)
    elif tokens[:2] == ["case", "assign"] and len(tokens) == 4:
        plan = _plan(
            "case.assign",
            {"case_id": tokens[2], "assignee": tokens[3]},
            OperatorRole.OPERATOR,
        )
    elif tokens[:2] == ["case", "close"] and len(tokens) >= 3:
        opts = _options(tokens[3:], {"--reason"})
        if "--reason" not in opts:
            raise CommandParseError("case close requires --reason")
        plan = _plan(
            "case.close",
            {"case_id": tokens[2], "reason": opts["--reason"]},
            OperatorRole.OPERATOR,
        )
    elif tokens[:2] == ["event", "explain"] and len(tokens) == 3:
        plan = _plan("event.explain", {"event_id": tokens[2]}, OperatorRole.VIEWER)
    elif tokens[:2] == ["orbit", "refresh"] and len(tokens) == 3 and tokens[2].isdigit():
        plan = _plan("orbit.refresh", {"norad_id": tokens[2]}, OperatorRole.ANALYST)
    else:
        raise CommandParseError("command is not allowed; use /commands/help for examples")

    if ROLE_RANK[role] < ROLE_RANK[plan.required_role]:
        raise PermissionError(
            f"{plan.action} requires {plan.required_role.value} role; current role is {role.value}"
        )
    return plan
