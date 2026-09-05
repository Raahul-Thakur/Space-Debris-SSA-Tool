"""``sdebris`` command-line interface.

Examples
--------
    sdebris fetch --group iridium-33-debris
    sdebris screen --norad 25544 --window-hours 72 --threshold-km 25
    sdebris screen --norad 25544 --no-fetch --alert
    sdebris catalog
"""

from __future__ import annotations

from datetime import datetime

import click
from rich.console import Console
from rich.table import Table

from sdebris import __version__
from sdebris.alerts import AlertDispatcher
from sdebris.config import load_config
from sdebris.ingest import TLECache, refresh_catalog
from sdebris.ontology import Database, persist_screening_result
from sdebris.reports import write_report
from sdebris.screening.screen import ScreeningResult, screen_target

console = Console()

_TIER_STYLE = {"critical": "bold red", "watch": "yellow", "nominal": "green"}


@click.group(help="Space debris SSA tool — conjunction screening from live TLE data.")
@click.version_option(__version__, prog_name="sdebris")
def cli() -> None:
    pass


@cli.command(help="Refresh the local TLE cache from CelesTrak.")
@click.option("--group", default=None, help="CelesTrak group (default: from config).")
@click.option("--config", "config_path", type=click.Path(exists=True), default=None)
def fetch(group: str | None, config_path: str | None) -> None:
    config = load_config(config_path)
    cache = refresh_catalog(config, group=group)
    group_name = group or config.ingestion.default_group
    stale = cache.stale_ids(config.ingestion.stale_after_days)
    console.print(
        f"Cache at [cyan]{cache.path}[/cyan]: [bold]{cache.count()}[/bold] objects "
        f"(group '{group_name}'), [yellow]{len(stale)}[/yellow] stale."
    )
    cache.close()


@cli.command(help="Show local TLE cache statistics.")
@click.option("--config", "config_path", type=click.Path(exists=True), default=None)
def catalog(config_path: str | None) -> None:
    config = load_config(config_path)
    cache = TLECache(config.resolve_path(config.ingestion.cache_path))
    stale = set(cache.stale_ids(config.ingestion.stale_after_days))
    console.print(f"[bold]{cache.count()}[/bold] objects cached ([yellow]{len(stale)} stale[/yellow]).")
    cache.close()


@cli.command("ontology-init", help="Initialize the local operational ontology database.")
@click.option("--database-url", default=None, help="Override the configured database URL.")
@click.option("--config", "config_path", type=click.Path(exists=True), default=None)
def ontology_init(database_url: str | None, config_path: str | None) -> None:
    config = load_config(config_path)
    database = Database(database_url or config.ontology.database_url)
    database.initialize()
    console.print(f"Ontology database initialized at [cyan]{database.engine.url}[/cyan]")
    database.engine.dispose()


@cli.command(help="Screen the catalog against a target NORAD id.")
@click.option("--norad", required=True, help="Target NORAD catalog id (e.g. 25544).")
@click.option("--group", default=None, help="CelesTrak group to screen against.")
@click.option("--config", "config_path", type=click.Path(exists=True), default=None)
@click.option("--window-hours", type=float, default=None, help="Override propagation window.")
@click.option("--step-sec", type=int, default=None, help="Override propagation step (s).")
@click.option("--threshold-km", type=float, default=None, help="Override report threshold (km).")
@click.option("--start", default=None, help="ISO-8601 UTC start time (default: now).")
@click.option("--no-fetch", is_flag=True, help="Use the cache only; do not hit CelesTrak.")
@click.option("--alert", is_flag=True, help="Dispatch alerts for critical events.")
@click.option("--no-report", is_flag=True, help="Skip writing CSV/JSON report files.")
@click.option(
    "--persist-ontology",
    is_flag=True,
    help="Version inputs and persist events, assessments, cases, audit, and lineage.",
)
def screen(
    norad: str, group: str | None, config_path: str | None,
    window_hours: float | None, step_sec: int | None, threshold_km: float | None,
    start: str | None, no_fetch: bool, alert: bool, no_report: bool,
    persist_ontology: bool,
) -> None:
    config = load_config(config_path)
    if window_hours is not None:
        config.propagation.window_hours = window_hours
    if step_sec is not None:
        config.propagation.step_sec = step_sec
    if threshold_km is not None:
        config.screening.report_threshold_km = threshold_km

    # Acquire data.
    if no_fetch:
        cache = TLECache(config.resolve_path(config.ingestion.cache_path))
    else:
        with console.status("Refreshing TLE catalog from CelesTrak..."):
            cache = refresh_catalog(config, group=group, extra_norad_ids=[norad])

    target = cache.get(norad)
    if target is None:
        cache.close()
        raise click.ClickException(
            f"Target NORAD {norad} not found in cache. Run `sdebris fetch` or drop --no-fetch."
        )
    objects = cache.all()
    cache.close()

    start_dt = datetime.fromisoformat(start) if start else None
    with console.status(f"Screening {len(objects)} objects against {target.name}..."):
        result = screen_target(target, objects, config, start=start_dt)

    _print_summary(result)

    if not no_report:
        paths = write_report(result, config)
        console.print(f"\nReport: [cyan]{paths.csv}[/cyan]\nMetadata: [cyan]{paths.json}[/cyan]")

    if alert:
        dispatched = AlertDispatcher(config).dispatch(result)
        console.print(f"Alerts dispatched for [bold]{len(dispatched)}[/bold] critical event(s).")

    if persist_ontology:
        database = Database(config.ontology.database_url)
        database.initialize()
        with console.status("Versioning inputs and persisting the ontology run..."):
            with database.session_factory() as session:
                summary = persist_screening_result(session, result, objects, config)
        database.engine.dispose()
        console.print(
            f"Ontology run: [cyan]{summary.screening_run_id}[/cyan] · "
            f"{summary.objects_versioned} versioned objects · "
            f"{summary.events_created} events · {summary.cases_opened} cases opened"
        )


def _print_summary(result: ScreeningResult) -> None:
    meta = result.metadata()
    by_tier = meta["events_by_tier"]
    console.print(
        f"\n[bold]{result.target_name}[/bold] (NORAD {result.target_norad}) — "
        f"screened {result.n_screened} objects over {result.window_hours:g} h\n"
        f"Events: [bold red]{by_tier['critical']} critical[/bold red], "
        f"[yellow]{by_tier['watch']} watch[/yellow], "
        f"[green]{by_tier['nominal']} nominal[/green]  "
        f"([yellow]{result.n_stale} stale TLEs[/yellow])"
    )
    if not result.events:
        console.print("[dim]No close approaches within the report threshold.[/dim]")
        return

    table = Table(show_header=True, header_style="bold")
    for col in ["Tier", "Secondary", "NORAD", "TCA (UTC)", "Miss (km)", "Rel v (km/s)", "Pc"]:
        table.add_column(col)
    df = result.to_dataframe()
    for _, row in df.head(20).iterrows():
        tier = str(row["risk_tier"])
        table.add_row(
            f"[{_TIER_STYLE.get(tier, '')}]{tier}[/]",
            str(row["secondary_name"])[:24],
            str(row["secondary_norad"]),
            str(row["tca_utc"])[:19],
            f"{row['miss_distance_km']:.3f}",
            f"{row['relative_speed_km_s']:.3f}",
            f"{row['probability_of_collision']:.2e}",
        )
    console.print(table)
    if len(df) > 20:
        console.print(f"[dim]... {len(df) - 20} more in the report CSV.[/dim]")


if __name__ == "__main__":
    cli()
