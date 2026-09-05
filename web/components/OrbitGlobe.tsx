"use client";

import { useEffect, useRef } from "react";
import * as Cesium from "cesium";
import type { Trajectory } from "@/lib/types";

declare global {
  interface Window {
    CESIUM_BASE_URL: string;
  }
}

type OrbitGlobeProps = {
  trajectories: Trajectory[];
  selectedNoradId: string | null;
  onSelect: (noradId: string) => void;
};

export default function OrbitGlobe({
  trajectories,
  selectedNoradId,
  onSelect
}: OrbitGlobeProps) {
  const container = useRef<HTMLDivElement>(null);
  const viewerRef = useRef<Cesium.Viewer | null>(null);
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
    viewer.scene.backgroundColor = Cesium.Color.fromCssColorString("#050708");
    viewer.scene.globe.baseColor = Cesium.Color.fromCssColorString("#0a1518");
    viewer.scene.globe.showGroundAtmosphere = true;
    viewer.scene.globe.enableLighting = true;
    if (viewer.scene.skyBox) viewer.scene.skyBox.show = false;
    if (viewer.scene.sun) viewer.scene.sun.show = false;
    if (viewer.scene.moon) viewer.scene.moon.show = false;
    viewer.scene.fog.enabled = false;
    viewer.camera.setView({
      destination: new Cesium.Cartesian3(11_600_000, -11_600_000, 7_200_000)
    });
    const clickHandler = new Cesium.ScreenSpaceEventHandler(viewer.scene.canvas);
    clickHandler.setInputAction((movement: Cesium.ScreenSpaceEventHandler.PositionedEvent) => {
      const picked = viewer.scene.pick(movement.position);
      const entity = picked?.id as Cesium.Entity | undefined;
      if (entity?.id) onSelectRef.current(entity.id.replace(/^orbit-/, ""));
    }, Cesium.ScreenSpaceEventType.LEFT_CLICK);
    viewerRef.current = viewer;
    return () => {
      clickHandler.destroy();
      viewer.destroy();
      viewerRef.current = null;
    };
  }, []);

  useEffect(() => {
    const viewer = viewerRef.current;
    if (!viewer) return;
    viewer.entities.removeAll();
    let selectedEntity: Cesium.Entity | undefined;
    trajectories.forEach((trajectory) => {
      const selected = trajectory.norad_id === selectedNoradId;
      const color = selected
        ? Cesium.Color.fromCssColorString("#7de7ed")
        : Cesium.Color.fromCssColorString("#87999c");
      const valid = trajectory.points.filter((point) => point.valid);
      const positions = valid.map(
        (point) =>
          new Cesium.Cartesian3(point.x_km * 1000, point.y_km * 1000, point.z_km * 1000)
      );
      if (!positions.length) return;
      viewer.entities.add({
        id: `orbit-${trajectory.norad_id}`,
        name: trajectory.name,
        polyline: {
          positions,
          width: selected ? 2.8 : 0.8,
          material: new Cesium.PolylineGlowMaterialProperty({
            color: color.withAlpha(selected ? 0.95 : 0.22),
            glowPower: selected ? 0.18 : 0.04
          })
        }
      });
      const objectEntity = viewer.entities.add({
        id: trajectory.norad_id,
        name: trajectory.name,
        position: positions[0],
        point: {
          pixelSize: selected ? 10 : 4,
          color,
          outlineColor: color.withAlpha(selected ? 0.3 : 0.08),
          outlineWidth: selected ? 8 : 3
        },
        label: {
          text: `${trajectory.name}  /  ${trajectory.norad_id}`,
          font: "11px IBM Plex Mono",
          fillColor: Cesium.Color.fromCssColorString("#b7c5c7"),
          show: selected,
          showBackground: true,
          backgroundColor: Cesium.Color.fromCssColorString("#071012").withAlpha(0.72),
          pixelOffset: new Cesium.Cartesian2(14, -12),
          horizontalOrigin: Cesium.HorizontalOrigin.LEFT
        }
      });
      if (selected) selectedEntity = objectEntity;
    });
    if (selectedEntity) {
      viewer.flyTo(selectedEntity, {
        duration: 0.9,
        offset: new Cesium.HeadingPitchRange(0, -0.35, 5_000_000)
      });
    }
  }, [selectedNoradId, trajectories]);

  return <div ref={container} className="globe" aria-label="TEME orbital visualization" />;
}
