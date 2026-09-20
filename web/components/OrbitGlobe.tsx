"use client";

import { useEffect, useRef } from "react";
import * as Cesium from "cesium";
import type { Trajectory } from "@/lib/types";

declare global {
  interface Window {
    CESIUM_BASE_URL: string;
  }
}

/** Mirrors the plate tokens in globals.css; Cesium cannot read CSS variables. */
const PLATE = "#101214";
const PAPER = "#efece4";
const SIGNAL = "#c02f18";
const TRACK = "#948f83";
const GLOBE = "#2b2f32";
const LIMB = "#4d5256";

type OrbitGlobeProps = {
  trajectories: Trajectory[];
  selectedNoradId: string | null;
  onSelect: (noradId: string) => void;
};

const EARTH_ID = "earth-body";
/** Camera altitude above the surface for the whole-disc view, in metres. */
const VIEW_ALTITUDE = 19_000_000;

/**
 * Re-centre the disc on `target`'s ground track.
 *
 * Cesium's `flyTo(entity)` frames an entity's bounding sphere, which for a
 * satellite is a point: the camera ends up a few thousand kilometres out with
 * the planet half out of shot. Flying to the sub-satellite longitude and
 * latitude at a fixed altitude keeps the whole globe framed whatever is
 * selected. Leaving `orientation` unset gives the default nadir view; building
 * a direction/up pair by hand risks a skewed, non-orthonormal basis.
 */
function frameOverhead(viewer: Cesium.Viewer, target: Cesium.Cartesian3) {
  const carto = Cesium.Cartographic.fromCartesian(target);
  if (!carto) return;
  viewer.camera.flyTo({
    destination: Cesium.Cartesian3.fromRadians(
      carto.longitude,
      carto.latitude,
      VIEW_ALTITUDE
    ),
    duration: 0.9
  });
}

/** Earth as a flat-shaded sphere plus a graticule, both unlit. */
function addEarth(scene: Cesium.Scene) {
  const radii = Cesium.Ellipsoid.WGS84.radii;
  const flat = new Cesium.PerInstanceColorAppearance({ flat: true, translucent: false });
  scene.primitives.add(
    new Cesium.Primitive({
      geometryInstances: new Cesium.GeometryInstance({
        geometry: new Cesium.EllipsoidGeometry({
          radii,
          vertexFormat: Cesium.PerInstanceColorAppearance.VERTEX_FORMAT
        }),
        attributes: {
          color: Cesium.ColorGeometryInstanceAttribute.fromColor(
            Cesium.Color.fromCssColorString(GLOBE)
          )
        }
      }),
      appearance: flat,
      asynchronous: false
    })
  );
  scene.primitives.add(
    new Cesium.Primitive({
      geometryInstances: new Cesium.GeometryInstance({
        geometry: new Cesium.EllipsoidOutlineGeometry({
          radii,
          slicePartitions: 24,
          stackPartitions: 12
        }),
        attributes: {
          color: Cesium.ColorGeometryInstanceAttribute.fromColor(
            Cesium.Color.fromCssColorString(LIMB)
          )
        }
      }),
      appearance: new Cesium.PerInstanceColorAppearance({
        flat: true,
        translucent: false,
        renderState: { lineWidth: 1 }
      }),
      asynchronous: false
    })
  );
}

export default function OrbitGlobe({
  trajectories,
  selectedNoradId,
  onSelect
}: OrbitGlobeProps) {
  const container = useRef<HTMLDivElement>(null);
  const viewerRef = useRef<Cesium.Viewer | null>(null);
  const tracksRef = useRef<Cesium.PolylineCollection | null>(null);
  const onSelectRef = useRef(onSelect);

  useEffect(() => {
    onSelectRef.current = onSelect;
  }, [onSelect]);

  useEffect(() => {
    if (!container.current || viewerRef.current) return;
    window.CESIUM_BASE_URL =
      process.env.NEXT_PUBLIC_CESIUM_BASE_URL ?? "/cesium";
    const viewer = new Cesium.Viewer(container.current, {
      animation: false,
      timeline: false,
      baseLayerPicker: false,
      geocoder: false,
      homeButton: false,
      sceneModePicker: false,
      navigationHelpButton: false,
      fullscreenButton: false,
      infoBox: false,
      selectionIndicator: false,
      baseLayer: false,
      terrainProvider: new Cesium.EllipsoidTerrainProvider()
    });
    viewer.scene.backgroundColor = Cesium.Color.fromCssColorString(PLATE);
    // There is no imagery layer, so the built-in globe contributes no visible
    // surface: what read as "Earth" before was the atmosphere shell alone.
    // The plate wants a flat diagram, so the shell is switched off and the
    // planet is drawn below as an evenly toned ellipsoid primitive instead.
    viewer.scene.globe.showGroundAtmosphere = false;
    viewer.scene.globe.enableLighting = false;
    if (viewer.scene.skyBox) viewer.scene.skyBox.show = false;
    if (viewer.scene.sun) viewer.scene.sun.show = false;
    if (viewer.scene.moon) viewer.scene.moon.show = false;
    viewer.scene.fog.enabled = false;

    // Drawn as primitives rather than entities: an entity ellipsoid is placed
    // through an east-north-up frame, which is undefined at the geocentric
    // origin, so it never renders. A primitive's identity model matrix is
    // already Earth-centred.
    addEarth(viewer.scene);

    // Orbit tracks are drawn through a PolylineCollection rather than as
    // entity polylines. Entity geometry is built asynchronously in Cesium's
    // web workers, and in this bundling setup those primitives never reach
    // `ready`, so every track silently stayed hidden. A PolylineCollection
    // is built on the main thread and needs no worker round-trip.
    const tracks = new Cesium.PolylineCollection();
    viewer.scene.primitives.add(tracks);
    tracksRef.current = tracks;

    viewer.camera.setView({
      destination: new Cesium.Cartesian3(11_600_000, -11_600_000, 7_200_000)
    });
    const clickHandler = new Cesium.ScreenSpaceEventHandler(viewer.scene.canvas);
    clickHandler.setInputAction((movement: Cesium.ScreenSpaceEventHandler.PositionedEvent) => {
      const picked = viewer.scene.pick(movement.position) as
        | { id?: string | { id?: unknown } }
        | undefined;
      // Entities hand back an Entity whose `id` is the string; a polyline in a
      // PolylineCollection hands back the string directly.
      const raw = picked?.id;
      const id =
        typeof raw === "string"
          ? raw
          : typeof raw?.id === "string"
            ? raw.id
            : null;
      // Clicking the planet itself is not a selection.
      if (!id || id === EARTH_ID) return;
      onSelectRef.current(id.replace(/^orbit-/, ""));
    }, Cesium.ScreenSpaceEventType.LEFT_CLICK);
    viewerRef.current = viewer;
    return () => {
      clickHandler.destroy();
      viewer.destroy();
      viewerRef.current = null;
      tracksRef.current = null;
    };
  }, []);

  useEffect(() => {
    const viewer = viewerRef.current;
    const tracks = tracksRef.current;
    if (!viewer || !tracks) return;
    // Earth is a primitive, so clearing the entity collection never touches it.
    viewer.entities.removeAll();
    tracks.removeAll();
    let selectedPosition: Cesium.Cartesian3 | undefined;
    trajectories.forEach((trajectory) => {
      const selected = trajectory.norad_id === selectedNoradId;
      const color = Cesium.Color.fromCssColorString(selected ? SIGNAL : TRACK);
      const valid = trajectory.points.filter((point) => point.valid);
      const positions = valid.map(
        (point) =>
          new Cesium.Cartesian3(point.x_km * 1000, point.y_km * 1000, point.z_km * 1000)
      );
      if (!positions.length) return;
      tracks.add({
        id: `orbit-${trajectory.norad_id}`,
        positions,
        width: selected ? 2 : 1,
        // A flat drawn line, not a glow: the plate reads as printed, not lit.
        material: Cesium.Material.fromType("Color", {
          color: color.withAlpha(selected ? 1 : 0.55)
        })
      });
      viewer.entities.add({
        id: trajectory.norad_id,
        name: trajectory.name,
        position: positions[0],
        point: {
          pixelSize: selected ? 9 : 4,
          color,
          outlineColor: Cesium.Color.fromCssColorString(PLATE),
          outlineWidth: selected ? 2 : 0,
          // The selected object stays visible even when it is behind Earth;
          // the rest are occluded so the near side reads correctly.
          disableDepthTestDistance: selected ? Number.POSITIVE_INFINITY : 0
        },
        label: {
          text: `${trajectory.name} / ${trajectory.norad_id}`,
          font: "500 11px 'IBM Plex Mono', monospace",
          fillColor: Cesium.Color.fromCssColorString(PAPER),
          show: selected,
          showBackground: true,
          backgroundColor: Cesium.Color.fromCssColorString(SIGNAL),
          backgroundPadding: new Cesium.Cartesian2(7, 5),
          pixelOffset: new Cesium.Cartesian2(14, -12),
          horizontalOrigin: Cesium.HorizontalOrigin.LEFT
        }
      });
      if (selected) selectedPosition = positions[0];
    });
    if (selectedPosition) frameOverhead(viewer, selectedPosition);
  }, [selectedNoradId, trajectories]);

  return <div ref={container} className="globe" aria-label="TEME orbital visualization" />;
}
