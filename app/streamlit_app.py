"""Multi-object space situational awareness dashboard.

Run with:
    streamlit run app/streamlit_app.py
"""

from __future__ import annotations

import math
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import streamlit as st

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from sdebris import __version__  # noqa: E402
from sdebris.config import load_config  # noqa: E402
from sdebris.ingest import TLECache, refresh_catalog  # noqa: E402
from sdebris.models import SpaceObject  # noqa: E402
from sdebris.propagation import make_time_grid, propagate_objects  # noqa: E402
from sdebris.screening.screen import screen_target  # noqa: E402
from sdebris.viz import build_groundtrack, build_orbit_3d, teme_to_geodetic  # noqa: E402

EARTH_RADIUS_KM = 6371.0
COMMON_OBJECTS = {
    "25544": "ISS (ZARYA)",
    "20580": "Hubble Space Telescope",
    "25338": "NOAA 15",
    "25994": "Terra",
    "27424": "Aqua",
    "39084": "Landsat 8",
    "40697": "Sentinel-2A",
}

st.set_page_config(
    page_title="Orbital watch",
    page_icon=":material/satellite_alt:",
    layout="wide",
    initial_sidebar_state="expanded",
)


def _to_objects(rows: tuple[tuple[str, str, str, str], ...]) -> list[SpaceObject]:
    return [SpaceObject(*row) for row in rows]


def _normalize_ids(values: list[str]) -> tuple[str, ...]:
    ids: list[str] = []
    for value in values:
        norad = str(value).strip().split(" ", 1)[0]
        if norad.isdigit() and norad not in ids:
            ids.append(norad)
    return tuple(ids[:6])


@st.cache_data(ttl=45, max_entries=16, show_spinner=False)
def load_catalog(
    group: str,
    use_live: bool,
    norad_ids: tuple[str, ...],
    refresh_key: int,
) -> tuple[tuple[tuple[str, str, str, str], ...], str | None]:
    """Load a serializable catalog snapshot and its actual cache timestamp."""
    del refresh_key  # Included only to permit an explicit/periodic cache bust.
    config = load_config()
    if use_live:
        cache = refresh_catalog(config, group=group, extra_norad_ids=list(norad_ids))
    else:
        cache = TLECache(config.resolve_path(config.ingestion.cache_path))
        if cache.count() == 0:
            cache = refresh_catalog(
                config, group=group, extra_norad_ids=list(norad_ids), offline_ok=True
            )
    objects = tuple((o.norad_id, o.name, o.line1, o.line2) for o in cache.all())
    # Streamlit can hot-reload this script while retaining an older imported
    # TLECache class in the server process. Keep that transition non-fatal; a
    # full server restart will restore the timestamp on the next run.
    last_fetched_at = getattr(cache, "last_fetched_at", None)
    fetched_at = last_fetched_at() if last_fetched_at else None
    cache.close()
    return objects, fetched_at.isoformat() if fetched_at else None


def _attention_score(row: pd.Series, threshold_km: float) -> int:
    tier_score = {"critical": 65, "watch": 35, "nominal": 5}.get(row["risk_tier"], 0)
    pc = max(float(row["probability_of_collision"]), 1e-12)
    pc_score = float(np.clip((math.log10(pc) + 8) / 4, 0, 1)) * 20
    proximity = max(0.0, 1.0 - float(row["miss_distance_km"]) / threshold_km) * 10
    freshness = 5 if bool(row["secondary_stale"]) else 0
    return int(round(min(100, tier_score + pc_score + proximity + freshness)))


def _recommendation(row: pd.Series) -> str:
    if row["risk_tier"] == "critical":
        return "Review immediately"
    if bool(row["secondary_stale"]):
        return "Refresh elements"
    if row["risk_tier"] == "watch":
        return "Track closely"
    return "Continue monitoring"


@st.cache_data(ttl=55, max_entries=12, show_spinner=False)
def build_snapshot(
    catalog_rows: tuple[tuple[str, str, str, str], ...],
    selected_ids: tuple[str, ...],
    window_hours: float,
    step_sec: int,
    threshold_km: float,
    snapshot_key: int,
) -> dict:
    """Propagate monitored objects and screen every one against the catalog."""
    del snapshot_key
    config = load_config()
    config.propagation.window_hours = window_hours
    config.propagation.step_sec = step_sec
    config.screening.report_threshold_km = threshold_km
    config.screening.coarse_threshold_km = max(
        config.screening.coarse_threshold_km, threshold_km * 1.5
    )

    catalog = _to_objects(catalog_rows)
    by_id = {obj.norad_id: obj for obj in catalog}
    monitored = [by_id[norad] for norad in selected_ids if norad in by_id]
    missing = [norad for norad in selected_ids if norad not in by_id]
    if not monitored:
        return {"error": "None of the selected NORAD IDs are available.", "missing": missing}

    start = datetime.now(timezone.utc)
    orbit_times = make_time_grid(
        start=start, window_hours=min(window_hours, 3), step_sec=max(step_sec, 30)
    )
    eph = propagate_objects(monitored, orbit_times, fail_on_error=False)

    monitor_rows = []
    for i, obj in enumerate(monitored):
        valid_idx = np.flatnonzero(eph.valid[i])
        if len(valid_idx):
            k = int(valid_idx[0])
            altitude = float(np.linalg.norm(eph.positions[i, k]) - EARTH_RADIUS_KM)
            speed = float(np.linalg.norm(eph.velocities[i, k]))
            propagation = "Healthy"
        else:
            altitude, speed, propagation = np.nan, np.nan, "Propagation error"
        age = obj.age_days(start)
        monitor_rows.append(
            {
                "norad_id": obj.norad_id,
                "object": obj.name,
                "status": "Stale TLE" if obj.is_stale(config.ingestion.stale_after_days, start)
                else propagation,
                "altitude_km": altitude,
                "speed_km_s": speed,
                "tle_age_days": age,
                "tle_epoch": obj.epoch,
            }
        )

    event_frames = []
    for target in monitored:
        result = screen_target(target, catalog, config, start=start)
        frame = result.to_dataframe()
        if not frame.empty:
            event_frames.append(frame)

    events = pd.concat(event_frames, ignore_index=True) if event_frames else pd.DataFrame()
    if not events.empty:
        # A monitored pair can appear in both directions. Keep one encounter.
        events["pair"] = events.apply(
            lambda row: " / ".join(sorted([row["target_norad"], row["secondary_norad"]])),
            axis=1,
        )
        events["tca_utc"] = pd.to_datetime(events["tca_utc"], utc=True)
        events = (
            events.sort_values(["miss_distance_km", "probability_of_collision"],
                               ascending=[True, False])
            .drop_duplicates(subset=["pair", "tca_utc"])
            .reset_index(drop=True)
        )
        events["attention_score"] = events.apply(
            _attention_score, axis=1, threshold_km=threshold_km
        )
        events["recommendation"] = events.apply(_recommendation, axis=1)
        events = events.sort_values(
            ["attention_score", "tca_utc"], ascending=[False, True]
        ).reset_index(drop=True)

    return {
        "generated_at": start,
        "monitored": pd.DataFrame(monitor_rows),
        "events": events,
        "eph": eph,
        "missing": missing,
        "catalog_size": len(catalog),
    }


def _render_metrics(snapshot: dict) -> None:
    objects = snapshot["monitored"]
    events = snapshot["events"]
    critical = int((events["risk_tier"] == "critical").sum()) if not events.empty else 0
    watch = int((events["risk_tier"] == "watch").sum()) if not events.empty else 0
    stale = int((objects["status"] == "Stale TLE").sum())
    next_tca = (
        events["tca_utc"].min().strftime("%d %b, %H:%M UTC") if not events.empty else "None"
    )
    with st.container(horizontal=True):
        st.metric("Objects monitored", len(objects), border=True)
        st.metric("Critical encounters", critical, border=True)
        st.metric("Watch encounters", watch, border=True)
        st.metric("Next encounter", next_tca, border=True)
    if stale:
        st.caption(f":orange-badge[{stale} stale element set(s)] require fresher orbital data.")


def _render_overview(snapshot: dict) -> None:
    objects = snapshot["monitored"].copy()
    events = snapshot["events"]

    risk_by_target: dict[str, str] = {}
    score_by_target: dict[str, int] = {}
    if not events.empty:
        tier_rank = {"critical": 3, "watch": 2, "nominal": 1}
        for norad in objects["norad_id"]:
            related = events[
                (events["target_norad"] == norad) | (events["secondary_norad"] == norad)
            ]
            if not related.empty:
                risk_by_target[norad] = max(
                    related["risk_tier"], key=lambda tier: tier_rank.get(tier, 0)
                )
                score_by_target[norad] = int(related["attention_score"].max())
    objects.insert(2, "risk", objects["norad_id"].map(risk_by_target).fillna("clear"))
    objects.insert(3, "attention", objects["norad_id"].map(score_by_target).fillna(0))

    left, right = st.columns([1.15, 0.85], gap="large")
    with left:
        st.subheader("Monitored objects")
        st.caption("Current propagated state and element-set health.")
        st.dataframe(
            objects,
            hide_index=True,
            key="monitored_objects",
            column_order=[
                "norad_id", "object", "risk", "attention", "status",
                "altitude_km", "speed_km_s", "tle_age_days", "tle_epoch",
            ],
            column_config={
                "norad_id": st.column_config.TextColumn("NORAD", pinned=True),
                "object": st.column_config.TextColumn("Object", pinned=True),
                "risk": st.column_config.TextColumn("Risk"),
                "attention": st.column_config.ProgressColumn(
                    "Attention", min_value=0, max_value=100, format="%d"
                ),
                "status": st.column_config.TextColumn("Telemetry"),
                "altitude_km": st.column_config.NumberColumn("Altitude", format="%.0f km"),
                "speed_km_s": st.column_config.NumberColumn("Speed", format="%.2f km/s"),
                "tle_age_days": st.column_config.NumberColumn("TLE age", format="%.1f d"),
                "tle_epoch": st.column_config.DatetimeColumn(
                    "TLE epoch", format="DD MMM, HH:mm"
                ),
            },
        )
    with right:
        st.subheader("Attention queue")
        st.caption("Ranked using risk tier, Pc, proximity, and data freshness.")
        if events.empty:
            st.success(
                "No reportable encounters in the current window.",
                icon=":material/check_circle:",
            )
        else:
            queue = events.head(8).copy()
            queue["encounter"] = queue["target_name"] + " → " + queue["secondary_name"]
            st.dataframe(
                queue,
                hide_index=True,
                key="attention_queue",
                column_order=[
                    "attention_score", "encounter", "risk_tier",
                    "miss_distance_km", "tca_utc", "recommendation",
                ],
                column_config={
                    "attention_score": st.column_config.ProgressColumn(
                        "Score", min_value=0, max_value=100, format="%d"
                    ),
                    "encounter": st.column_config.TextColumn("Encounter", pinned=True),
                    "risk_tier": st.column_config.TextColumn("Tier"),
                    "miss_distance_km": st.column_config.NumberColumn(
                        "Miss", format="%.2f km"
                    ),
                    "tca_utc": st.column_config.DatetimeColumn(
                        "TCA", format="DD MMM, HH:mm"
                    ),
                    "recommendation": st.column_config.TextColumn("Action"),
                },
            )


def _render_orbits(snapshot: dict) -> None:
    st.subheader("Orbital picture")
    st.caption("Three-hour TEME propagation for all monitored objects.")
    eph = snapshot["eph"]
    events = snapshot["events"]
    tiers = {}
    if not events.empty:
        tiers = dict(zip(events["secondary_norad"], events["risk_tier"]))
        tiers.update(dict(zip(events["target_norad"], events["risk_tier"])))
    fig = build_orbit_3d(eph, eph.norad_ids[0], tiers)
    fig.update_layout(height=680)
    st.plotly_chart(fig, width="stretch", key="multi_orbit_view")


def _render_ground_tracks(snapshot: dict) -> None:
    st.subheader("Ground tracks")
    st.caption("Projected sub-satellite paths for the monitored fleet.")
    eph = snapshot["eph"]
    tracks = {}
    for i, norad in enumerate(eph.norad_ids):
        valid = eph.valid[i]
        if valid.any():
            tracks[f"{norad} {eph.names[i]}"] = teme_to_geodetic(
                eph.positions[i][valid], eph.times[valid]
            )
    fig = build_groundtrack(tracks, eph.norad_ids[0])
    fig.update_layout(height=620)
    st.plotly_chart(fig, width="stretch", key="multi_groundtrack_view")


def _render_encounters(snapshot: dict) -> None:
    st.subheader("Conjunction analysis")
    st.caption("Every monitored object screened against the selected CelesTrak catalog.")
    events = snapshot["events"]
    if events.empty:
        st.success("No conjunctions meet the report threshold.", icon=":material/check_circle:")
        return
    st.dataframe(
        events,
        hide_index=True,
        key="all_encounters",
        column_order=[
            "attention_score", "risk_tier", "target_name", "secondary_name", "tca_utc",
            "miss_distance_km", "relative_speed_km_s", "probability_of_collision",
            "radial_km", "along_track_km", "cross_track_km", "recommendation",
        ],
        column_config={
            "attention_score": st.column_config.ProgressColumn(
                "Attention", min_value=0, max_value=100, format="%d"
            ),
            "risk_tier": st.column_config.TextColumn("Tier"),
            "target_name": st.column_config.TextColumn("Primary", pinned=True),
            "secondary_name": st.column_config.TextColumn("Secondary", pinned=True),
            "tca_utc": st.column_config.DatetimeColumn("TCA", format="DD MMM YYYY, HH:mm:ss"),
            "miss_distance_km": st.column_config.NumberColumn("Miss", format="%.3f km"),
            "relative_speed_km_s": st.column_config.NumberColumn(
                "Relative speed", format="%.3f km/s"
            ),
            "probability_of_collision": st.column_config.NumberColumn(
                "Collision probability", format="scientific"
            ),
            "radial_km": st.column_config.NumberColumn("Radial", format="%.2f km"),
            "along_track_km": st.column_config.NumberColumn("Along-track", format="%.2f km"),
            "cross_track_km": st.column_config.NumberColumn("Cross-track", format="%.2f km"),
            "recommendation": st.column_config.TextColumn("Action"),
        },
    )
    st.download_button(
        "Download encounter report",
        events.drop(columns=["pair"], errors="ignore").to_csv(index=False).encode(),
        file_name="multi_norad_encounters.csv",
        mime="text/csv",
        icon=":material/download:",
    )


st.session_state.setdefault("refresh_nonce", 0)
st.session_state.setdefault("view", "Overview")

with st.sidebar:
    st.title("Orbital watch")
    st.caption(f"Space situational awareness · v{__version__}")
    selected_values = st.multiselect(
        "NORAD objects",
        options=[f"{norad} · {name}" for norad, name in COMMON_OBJECTS.items()],
        default=[
            f"25544 · {COMMON_OBJECTS['25544']}",
            f"20580 · {COMMON_OBJECTS['20580']}",
        ],
        accept_new_options=True,
        max_selections=6,
        placeholder="Select or enter a NORAD ID",
        help="Monitor up to six satellites or debris objects.",
    )
    group = st.selectbox(
        "Screening catalog",
        ["iridium-33-debris", "cosmos-2251-debris", "active", "stations", "last-30-days"],
    )
    use_live = st.toggle("Use live CelesTrak data", value=True)
    auto_refresh = st.toggle("Automatic monitoring", value=False)
    refresh_seconds = st.select_slider(
        "Refresh interval",
        options=[60, 120, 300, 600],
        value=120,
        format_func=lambda seconds: f"{seconds // 60} min",
        disabled=not auto_refresh,
    )
    with st.expander("Screening parameters", icon=":material/tune:"):
        window_hours = st.slider("Look-ahead window", 6, 168, 24, step=6, format="%d h")
        threshold_km = st.slider("Report threshold", 1, 100, 25, format="%d km")
        step_sec = st.select_slider("Propagation step", [30, 60, 120, 300], value=120)
    if st.button("Refresh now", type="primary", icon=":material/refresh:", width="stretch"):
        st.session_state.refresh_nonce += 1
        load_catalog.clear()
        build_snapshot.clear()
        st.toast("Refreshing orbital elements")

selected_ids = _normalize_ids(selected_values)

title_col, status_col = st.columns([0.78, 0.22], vertical_alignment="center")
with title_col:
    st.title("Multi-object monitoring")
    st.caption("Live orbital state, conjunction screening, and a ranked operator attention queue.")
with status_col:
    if auto_refresh:
        st.badge(
            f"Monitoring · {refresh_seconds // 60} min",
            icon=":material/radar:",
            color="green",
        )
    elif use_live:
        st.badge("Live on refresh", icon=":material/sync:", color="blue")
    else:
        st.badge("Cached data", icon=":material/database:", color="gray")

view = st.segmented_control(
    "Workspace",
    ["Overview", "Orbits", "Ground tracks", "Encounters"],
    key="view",
    label_visibility="collapsed",
)

if not selected_ids:
    st.info(
        "Select at least one NORAD object in the sidebar to begin monitoring.",
        icon=":material/satellite_alt:",
    )
    st.stop()


@st.fragment(run_every=refresh_seconds if auto_refresh else None)
def monitoring_workspace() -> None:
    bucket = int(time.time() // refresh_seconds) if auto_refresh else st.session_state.refresh_nonce
    catalog_slot = st.container()
    with catalog_slot:
        with st.spinner("Synchronizing elements and screening the catalog…", show_time=True):
            catalog_rows, fetched_at = load_catalog(
                group, use_live, selected_ids, bucket + st.session_state.refresh_nonce
            )
            snapshot = build_snapshot(
                catalog_rows,
                selected_ids,
                float(window_hours),
                int(step_sec),
                float(threshold_km),
                bucket + st.session_state.refresh_nonce,
            )

    if "error" in snapshot:
        st.error(snapshot["error"], icon=":material/error:")
        return
    if snapshot["missing"]:
        st.warning(
            "No element set was found for: " + ", ".join(snapshot["missing"]),
            icon=":material/warning:",
        )

    generated = snapshot["generated_at"].strftime("%d %b %Y, %H:%M:%S UTC")
    if fetched_at:
        fetched = pd.Timestamp(fetched_at).tz_convert("UTC").strftime("%d %b, %H:%M:%S UTC")
    else:
        fetched = "unknown"
    st.caption(
        f"Snapshot {generated} · catalog {snapshot['catalog_size']:,} objects · "
        f"latest cached fetch {fetched}"
    )
    _render_metrics(snapshot)

    if view == "Orbits":
        _render_orbits(snapshot)
    elif view == "Ground tracks":
        try:
            _render_ground_tracks(snapshot)
        except Exception as exc:
            st.warning(f"Ground-track rendering unavailable: {exc}", icon=":material/warning:")
    elif view == "Encounters":
        _render_encounters(snapshot)
    else:
        _render_overview(snapshot)

    st.caption(
        "Educational analysis only. TLE-derived covariance and collision probability "
        "are illustrative and must not drive operational maneuver decisions."
    )


monitoring_workspace()
