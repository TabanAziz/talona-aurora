import * as THREE from "three";
import { MM, tokenColor } from "../../components/plan3d/primitives";
import { createSiteScene, type SiteScene, type SiteLayerContext } from "../../components/site3d/siteScene";
import type { SurveyWall } from "./survey";

export interface FlightView { flying: boolean; stopped: boolean; wall: SurveyWall | null }

export function createDroneScene(host: HTMLElement, read: () => FlightView): SiteScene {
  return createSiteScene(host, () => {}, () => {}, {
    layer: (context: SiteLayerContext) => {
      const craft = new THREE.Group();
      const ink = new THREE.MeshBasicMaterial({ color: tokenColor("--ink") });
      const accent = new THREE.MeshBasicMaterial({ color: tokenColor("--accent") });
      craft.add(new THREE.Mesh(new THREE.BoxGeometry(0.85, 0.24, 0.85), accent));
      for (const [x, z] of [[-0.65, -0.65], [-0.65, 0.65], [0.65, -0.65], [0.65, 0.65]]) {
        const rotor = new THREE.Mesh(new THREE.CylinderGeometry(0.48, 0.48, 0.06, 20), ink);
        rotor.position.set(x, 0.08, z);
        craft.add(rotor);
        const arm = new THREE.Mesh(new THREE.BoxGeometry(1.7, 0.08, 0.1), ink);
        arm.rotation.y = x * z > 0 ? Math.PI / 4 : -Math.PI / 4;
        craft.add(arm);
      }
      context.group.add(craft);
      const beam = new THREE.Line(new THREE.BufferGeometry(), new THREE.LineBasicMaterial({ color: tokenColor("--accent") }));
      context.group.add(beam);
      const ground = new THREE.Vector3(context.centre.x + context.width / 2 - 3, 0.6, context.centre.z + context.depth / 2 - 3);
      let started = 0;
      return {
        tick(now) {
          const state = read();
          const point = state.wall;
          if (!started) started = now;
          if (state.flying && point) {
            const x = (point.wall.x1 + point.wall.x2) / 2 * MM;
            const z = (point.wall.y1 + point.wall.y2) / 2 * MM;
            const floor = context.units.get(point.unit)?.y ?? context.top;
            const movement = context.reducedMotion ? 0 : Math.sin((now - started) / 450) * 0.55;
            craft.position.set(x + movement, floor + 4.4, z + 0.9);
            beam.geometry.dispose();
            beam.geometry = new THREE.BufferGeometry().setFromPoints([craft.position, new THREE.Vector3(x, floor + 0.2, z)]);
          } else craft.position.copy(ground);
          beam.visible = state.flying && point !== null;
          accent.color.copy(tokenColor(state.stopped ? "--danger" : "--accent"));
          return state.flying && !context.reducedMotion;
        },
        dispose() {},
      };
    },
  });
}
