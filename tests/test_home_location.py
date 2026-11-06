"""Where the package looks for configs/ and data/ once it is installed."""

from pathlib import Path

from sdebris.config import locate_home


def _checkout(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    (repo / "configs").mkdir(parents=True)
    (repo / "configs" / "default.yaml").write_text("{}\n")
    (repo / "src" / "sdebris").mkdir(parents=True)
    return repo


def test_source_checkout_uses_the_repository(tmp_path: Path) -> None:
    repo = _checkout(tmp_path)
    assert locate_home(repo / "src" / "sdebris", {}, tmp_path) == repo


def test_installed_package_does_not_resolve_into_site_packages(tmp_path: Path) -> None:
    """A regular install must not treat Python's library folder as home.

    This is the container's layout: the package sits in site-packages and the
    old arithmetic resolved to /usr/local/lib/python3.12, which the service
    user cannot write to.
    """
    site = tmp_path / "lib" / "python3.12" / "site-packages" / "sdebris"
    site.mkdir(parents=True)
    workdir = tmp_path / "app"
    workdir.mkdir()
    home = locate_home(site, {}, workdir)
    assert home == workdir.resolve()
    assert "site-packages" not in str(home) and home != site.parent.parent


def test_sdebris_home_wins(tmp_path: Path) -> None:
    repo = _checkout(tmp_path)
    chosen = tmp_path / "elsewhere"
    assert locate_home(repo / "src" / "sdebris", {"SDEBRIS_HOME": str(chosen)}, tmp_path) == chosen.resolve()
