import pytest

from sdebris.commands import CommandParseError, parse_command
from sdebris.ontology.enums import OperatorRole


def test_screen_command_becomes_typed_plan() -> None:
    plan = parse_command(
        "screen 25544 --window 3d --threshold 800m --step 2m --cached",
        OperatorRole.ANALYST,
    )

    assert plan.action == "screen"
    assert plan.asynchronous is True
    assert plan.arguments == {
        "norad_id": "25544",
        "window_hours": 72.0,
        "threshold_km": 0.8,
        "step_sec": 120,
        "group": "iridium-33-debris",
        "refresh_catalog": False,
        "persist_ontology": True,
    }


@pytest.mark.parametrize(
    "raw,action",
    [
        ("monitor add 20580", "monitor.add"),
        ("monitor seed-known", "monitor.seed-known"),
        ("events list --tier critical", "events.list"),
        ("case assign abc analyst-1", "case.assign"),
        ('case close abc --reason "Risk resolved"', "case.close"),
        ("event explain abc", "event.explain"),
        ("orbit refresh 25544", "orbit.refresh"),
    ],
)
def test_allowlisted_commands(raw: str, action: str) -> None:
    assert parse_command(raw).action == action


def test_shell_syntax_and_unknown_flags_are_rejected() -> None:
    with pytest.raises(CommandParseError):
        parse_command("screen 25544 --output report.csv")
    with pytest.raises(CommandParseError):
        parse_command("whoami")


def test_role_gate_is_enforced() -> None:
    with pytest.raises(PermissionError, match="requires analyst"):
        parse_command("screen 25544", OperatorRole.VIEWER)
