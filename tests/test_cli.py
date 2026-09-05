from click.testing import CliRunner

from sdebris.cli import cli


def test_cli_version() -> None:
    result = CliRunner().invoke(cli, ["--version"])
    assert result.exit_code == 0
    assert "sdebris" in result.output


def test_cli_screen_offline_smoke(tmp_path) -> None:
    # --no-fetch with an empty cache seeded from the sample file path is exercised
    # in integration; here we just confirm the command wiring + error handling.
    result = CliRunner().invoke(cli, ["screen", "--norad", "00000", "--no-fetch"])
    # Either the cache is empty (target not found) or it screens; both are non-crash.
    assert result.exit_code in (0, 1)


def test_cli_initializes_ontology_database(tmp_path) -> None:
    database_url = f"sqlite:///{(tmp_path / 'ontology.db').as_posix()}"
    result = CliRunner().invoke(
        cli, ["ontology-init", "--database-url", database_url]
    )
    assert result.exit_code == 0
    assert (tmp_path / "ontology.db").exists()
