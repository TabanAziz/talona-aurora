import * as THREE from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";
import type { Geometry, Room, Wall } from "../../components/plan3d/geometry";
import { addPlan, footprintOf, tokenColor, MM } from "../../components/plan3d/primitives";

export type RobotState = "running" | "stopped" | "done";

export interface RobotScene {
  /** What is on the slab: the loaded revision, the old revision as a ghost, the chalked lines and the robot. */
  update(geometry: Geometry, old: Geometry | null, marked: string[], station: Room | null, state: RobotState): void;
  dispose(): void;
}

/** The chalk band the robot leaves on the slab. The slab is 19 m wide, so a true 2 cm line is a couple of
 * pixels at the demo camera: the band is wider so the line it just laid down reads in the screenshot. */
const CHALK_HEIGHT = 0.12;
const CHALK_WIDTH = 0.22;

export function createRobotScene(host: HTMLElement, frame: Geometry): RobotScene {
  const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
  renderer.domElement.style.display = "block";
  renderer.domElement.style.width = "100%";
  renderer.domElement.style.height = "100%";
  host.appendChild(renderer.domElement);

  const scene = new THREE.Scene();
  scene.add(new THREE.AmbientLight(0xffffff, 1.6));
  const sun = new THREE.DirectionalLight(0xffffff, 1.4);
  sun.position.set(-8, 20, 14);
  scene.add(sun);

  const area = footprintOf(frame);
  const target = new THREE.Vector3(area.x + area.width / 2, 0, area.z + area.depth / 2);
  const camera = new THREE.PerspectiveCamera(30, 1, 0.1, 400);
  const controls = new OrbitControls(camera, renderer.domElement);
  controls.enablePan = false;
  controls.target.copy(target);
  controls.maxPolarAngle = THREE.MathUtils.degToRad(80);

  const group = new THREE.Group();
  scene.add(group);

  // The rover sits outside the plan group, so a redraw does not remove it and it can drive between units.
  const rover = new THREE.Group();
  const shell = new THREE.MeshBasicMaterial({ color: tokenColor("--accent") });
  const body = new THREE.Mesh(new THREE.BoxGeometry(1.15, 0.5, 0.8), shell);
  body.position.y = 0.5;
  rover.add(body);
  const cabin = new THREE.Mesh(new THREE.BoxGeometry(0.5, 0.35, 0.6), shell);
  cabin.position.set(0.2, 0.86, 0);
  rover.add(cabin);
  const tyreMaterial = new THREE.MeshBasicMaterial({ color: tokenColor("--ink") });
  for (const [x, z] of [[-0.42, -0.36], [-0.42, 0.36], [0.42, -0.36], [0.42, 0.36]]) {
    const tyre = new THREE.Mesh(new THREE.CylinderGeometry(0.2, 0.2, 0.14, 14), tyreMaterial);
    tyre.rotation.x = Math.PI / 2;
    tyre.position.set(x, 0.2, z);
    rover.add(tyre);
  }
  // The mast stands above the walls, so the rover is still the one thing to look at from the demo camera.
  const mast = new THREE.Mesh(new THREE.BoxGeometry(0.08, 1.35, 0.08), shell);
  mast.position.set(-0.3, 1.35, 0);
  rover.add(mast);
  const arm = new THREE.Mesh(new THREE.BoxGeometry(0.7, 0.08, 0.08), shell);
  arm.position.set(0.6, 0.74, -0.26);
  rover.add(arm);
  rover.scale.setScalar(1.7);
  scene.add(rover);

  const at = new THREE.Vector3();
  const goal = new THREE.Vector3();
  let driving = false;

  function render() {
    renderer.render(scene, camera);
  }

  function drive() {
    if (!driving) return;
    at.lerp(goal, 0.18);
    rover.position.copy(at);
    render();
    if (at.distanceTo(goal) < 0.03) {
      at.copy(goal);
      rover.position.copy(at);
      driving = false;
      render();
      return;
    }
    requestAnimationFrame(drive);
  }

  function place(station: Room, instant: boolean) {
    goal.set(station.x * MM, 0, station.y * MM);
    if (instant) {
      at.copy(goal);
      rover.position.copy(at);
      return;
    }
    if (at.distanceTo(goal) < 0.02) return;
    driving = true;
    requestAnimationFrame(drive);
  }

  let placed = false;

  function clear() {
    for (const child of [...group.children]) {
      group.remove(child);
      child.traverse((node) => {
        const mesh = node as THREE.Mesh;
        mesh.geometry?.dispose();
        const material = mesh.material;
        for (const item of Array.isArray(material) ? material : material ? [material] : []) {
          (item as THREE.MeshBasicMaterial).map?.dispose();
          item.dispose();
        }
      });
    }
  }

  function fit() {
    const { clientWidth, clientHeight } = host;
    if (clientWidth === 0 || clientHeight === 0) return;
    renderer.setSize(clientWidth, clientHeight, false);
    camera.aspect = clientWidth / clientHeight;
    camera.updateProjectionMatrix();
    render();
  }

  function frameCamera() {
    const tan = Math.tan(THREE.MathUtils.degToRad(camera.fov / 2));
    const aspect = Math.max(host.clientWidth / Math.max(host.clientHeight, 1), 0.1);
    const radius = Math.max((area.width * 0.68) / (tan * aspect), (area.depth * 1.05) / tan);
    const polar = THREE.MathUtils.degToRad(46);
    const azimuth = THREE.MathUtils.degToRad(18);
    camera.position.set(
      target.x + radius * Math.sin(polar) * Math.sin(azimuth),
      target.y + radius * Math.cos(polar),
      target.z + radius * Math.sin(polar) * Math.cos(azimuth),
    );
    controls.minDistance = radius * 0.35;
    controls.maxDistance = radius * 1.6;
    controls.update();
  }

  function addChalk(target: THREE.Group, wall: Wall, material: THREE.Material) {
    const length = Math.hypot(wall.x2 - wall.x1, wall.y2 - wall.y1) * MM;
    if (length <= 0) return;
    const box = new THREE.BoxGeometry(length, CHALK_HEIGHT, Math.max(wall.thickness * MM, CHALK_WIDTH));
    box.rotateY(-Math.atan2(wall.y2 - wall.y1, wall.x2 - wall.x1));
    box.translate(((wall.x1 + wall.x2) / 2) * MM, CHALK_HEIGHT / 2, ((wall.y1 + wall.y2) / 2) * MM);
    target.add(new THREE.Mesh(box, material));
  }

  function update(geometry: Geometry, old: Geometry | null, marked: string[], station: Room | null, state: RobotState) {
    clear();
    addPlan(group, geometry, {
      frame,
      changed: new Set(geometry.changed ?? []),
      old,
    });
    const chalked = new Set(marked);
    const chalk = new THREE.MeshBasicMaterial({ color: tokenColor("--accent") });
    for (const wall of geometry.walls) if (chalked.has(wall.id)) addChalk(group, wall, chalk);
    const color = state === "stopped" ? tokenColor("--danger") : state === "done" ? tokenColor("--success") : tokenColor("--accent");
    shell.color.copy(color);
    if (station) {
      place(station, !placed);
      placed = true;
    }
    render();
  }

  controls.addEventListener("change", render);
  const observer = new ResizeObserver(fit);
  observer.observe(host);
  frameCamera();

  return {
    update,
    dispose() {
      observer.disconnect();
      controls.removeEventListener("change", render);
      controls.dispose();
      clear();
      rover.traverse((node) => {
        const mesh = node as THREE.Mesh;
        mesh.geometry?.dispose();
        const material = mesh.material;
        for (const item of Array.isArray(material) ? material : material ? [material] : []) item.dispose();
      });
      renderer.dispose();
      renderer.domElement.remove();
    },
  };
}
