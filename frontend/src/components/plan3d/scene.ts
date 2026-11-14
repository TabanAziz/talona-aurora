import * as THREE from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";
import type { Geometry, Opening, Room, Wall } from "./geometry";
import { MM, addPlan, footprintOf, tokenColor } from "./primitives";
import { perspectiveFitDistance } from "./framing";
import { cameraTransition } from "./motion";
import { splitFloors } from "./floors";

export type Layer = "before" | "after" | "overlay";

/** One plate of the exploded stack: a floor's walls, its rooms and its openings. */
export interface FloorPlan {
  level: string;
  walls: Wall[];
  rooms: Room[];
  openings: Opening[];
}

export interface ScreenPoint {
  x: number;
  y: number;
}

/** Where the callouts and their leader lines attach, in pixels of the host. */
export interface ScreenPoints {
  /** The top middle of the changed wall, or null when nothing is highlighted. */
  primary: ScreenPoint | null;
  /** The room label of each unit, so a secondary plaque can point at it. */
  rooms: Record<string, ScreenPoint>;
  /** The middle of each plate, for a plaque that has no room to point at. */
  plates: ScreenPoint[];
}

export interface Viewer {
  show(layer: Layer): void;
  rotate(radians: number): void;
  zoom(factor: number): void;
  fit(): void;
  reset(): void;
  points(): ScreenPoints;
  dispose(): void;
}

/** Vertical distance between two plates of the stack, in metres. */
const PLATE_GAP = 4.2;

export function webglAvailable(): boolean {
  try {
    const canvas = document.createElement("canvas");
    const context = canvas.getContext("webgl2") || canvas.getContext("webgl");
    const available = Boolean(context);
    context?.getExtension("WEBGL_lose_context")?.loseContext();
    return available;
  } catch {
    return false;
  }
}

export function createViewer(host: HTMLElement, before: Geometry, after: Geometry, onRender: () => void,
                             floors?: FloorPlan[], presentation: "building" | "exploded" = "exploded"): Viewer {
  const currentFloors = floors?.length ? floors : splitFloors(after);
  const previousFloors = before === after && floors?.length ? floors : splitFloors(before);
  const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
  renderer.shadowMap.enabled = true;
  renderer.shadowMap.autoUpdate = false;
  renderer.shadowMap.type = THREE.PCFSoftShadowMap;
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  renderer.toneMappingExposure = 1;
  renderer.domElement.style.display = "block";
  renderer.domElement.style.width = "100%";
  renderer.domElement.style.height = "100%";
  host.appendChild(renderer.domElement);

  const scene = new THREE.Scene();
  scene.add(new THREE.HemisphereLight(0xf3f7ff, 0xd6cbb8, 2));
  const sun = new THREE.DirectionalLight(0xfff4e5, 3);
  scene.add(sun);

  const currentArea = footprintOf(after), oldArea = footprintOf(before);
  const area = {
    x: Math.min(currentArea.x, oldArea.x), z: Math.min(currentArea.z, oldArea.z),
    width: Math.max(currentArea.x + currentArea.width, oldArea.x + oldArea.width) - Math.min(currentArea.x, oldArea.x),
    depth: Math.max(currentArea.z + currentArea.depth, oldArea.z + oldArea.depth) - Math.min(currentArea.z, oldArea.z),
  };
  const widthM = area.width;
  const depthM = area.depth;
  const wallHeight = Math.max(before.wall_height, after.wall_height) * MM;
  const plateGap = presentation === "building" ? wallHeight + .15 : Math.max(PLATE_GAP, wallHeight + 1.2);
  const stackHeight = (Math.max(1, currentFloors.length, previousFloors.length) - 1) * plateGap + Math.max(before.wall_height, after.wall_height) * MM;
  const target = new THREE.Vector3(area.x + widthM / 2, stackHeight / 2, area.z + depthM / 2);
  const span = Math.max(widthM, depthM, stackHeight);
  sun.position.set(target.x - span * .7, span * 1.6, target.z + span);
  sun.target.position.copy(target);
  sun.castShadow = true;
  sun.shadow.mapSize.set(1024, 1024);
  sun.shadow.camera.left = -span; sun.shadow.camera.right = span;
  sun.shadow.camera.top = span; sun.shadow.camera.bottom = -span;
  sun.shadow.camera.near = .1; sun.shadow.camera.far = span * 5;
  sun.shadow.normalBias = .03;
  scene.add(sun.target);
  const camera = new THREE.PerspectiveCamera(30, 1, 0.1, Math.max(400, span * 20));

  const controls = new OrbitControls(camera, renderer.domElement);
  controls.enablePan = true;
  controls.screenSpacePanning = true;
  controls.touches.ONE = THREE.TOUCH.ROTATE;
  controls.touches.TWO = THREE.TOUCH.DOLLY_PAN;
  controls.target.copy(target);
  controls.minPolarAngle = THREE.MathUtils.degToRad(12);
  controls.maxPolarAngle = THREE.MathUtils.degToRad(78);

  // Ground and guide lines are a neutral viewing aid, not extra building geometry.
  const groundGeometry = new THREE.PlaneGeometry(span * 2.5, span * 2.5);
  const groundMaterial = new THREE.MeshStandardMaterial({ color: tokenColor("--model-ground"), roughness: 1 });
  const ground = new THREE.Mesh(groundGeometry, groundMaterial);
  ground.rotation.x = -Math.PI / 2;
  ground.position.set(target.x, -.18, target.z);
  ground.receiveShadow = true;
  scene.add(ground);
  const grid = new THREE.GridHelper(span * 2.5, 24, tokenColor("--sheet-shade"), tokenColor("--sheet-shade"));
  grid.position.set(target.x, -.17, target.z);
  const gridMaterial = grid.material as THREE.LineBasicMaterial;
  gridMaterial.transparent = true;
  gridMaterial.opacity = .35;
  scene.add(grid);

  const group = new THREE.Group();
  scene.add(group);
  let anchors: THREE.Vector3[] = [];
  let roomPoints: Map<string, THREE.Vector3> = new Map();
  let plateCentres: THREE.Vector3[] = [];
  const corners = [area.x - .3, area.x + widthM + .3].flatMap((x) => [-.15, stackHeight].flatMap((y) => [area.z - .3, area.z + depthM + .3].map((z) => ({ x, y, z }))));
  let previousAspect = 0;
  let stopTransition = () => {};
  let planningCommand = false;
  let renderFrame = 0;
  let disposed = false;
  const cancelCameraMotion = () => { stopTransition(); stopTransition = () => {}; };
  const fitDistance = (aspect: number) => perspectiveFitDistance(corners, controls.target, camera.position.clone().sub(controls.target), camera.fov, aspect);

  function setDistance(distance: number) {
    const offset = camera.position.clone().sub(controls.target).setLength(distance);
    camera.position.copy(controls.target).add(offset);
    controls.minDistance = .5;
    controls.maxDistance = Math.max(span * 12, distance * 3);
    controls.update();
  }

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
    anchors = [];
    roomPoints = new Map();
    plateCentres = [];
  }

  function render() {
    if (planningCommand || disposed || renderFrame) return;
    renderFrame = requestAnimationFrame(() => {
      renderFrame = 0;
      if (disposed) return;
      const started = performance.now();
      renderer.render(scene, camera);
      host.dataset.drawCalls = String(renderer.info.render.calls);
      host.dataset.renderTimeMs = (performance.now() - started).toFixed(2);
      onRender();
    });
  }

  function fit() {
    const { clientWidth, clientHeight } = host;
    if (clientWidth === 0 || clientHeight === 0) return;
    renderer.setSize(clientWidth, clientHeight, false);
    const aspect = clientWidth / clientHeight;
    if (previousAspect > 0 && Math.abs(aspect - previousAspect) > .001) {
      cancelCameraMotion();
      const ratio = camera.position.distanceTo(controls.target) / fitDistance(previousAspect);
      setDistance(fitDistance(aspect) * ratio);
    }
    previousAspect = aspect;
    camera.aspect = aspect;
    camera.updateProjectionMatrix();
    render();
  }

  function frame() {
    const aspect = Math.max(host.clientWidth / Math.max(host.clientHeight, 1), 0.1);
    controls.target.copy(target);
    camera.position.copy(target).add(new THREE.Vector3().setFromSpherical(new THREE.Spherical(1, THREE.MathUtils.degToRad(34), THREE.MathUtils.degToRad(22))));
    setDistance(fitDistance(aspect));
    previousAspect = aspect;
    fit();
  }

  function animateCommand(command: () => void) {
    cancelCameraMotion();
    const fromTarget = controls.target.clone();
    const from = new THREE.Spherical().setFromVector3(camera.position.clone().sub(fromTarget));
    planningCommand = true;
    command();
    const toTarget = controls.target.clone();
    const to = new THREE.Spherical().setFromVector3(camera.position.clone().sub(toTarget));
    controls.maxDistance = Math.max(controls.maxDistance, from.radius, to.radius);
    const turn = Math.atan2(Math.sin(to.theta - from.theta), Math.cos(to.theta - from.theta));
    planningCommand = false;
    stopTransition = cameraTransition((progress) => {
      controls.target.lerpVectors(fromTarget, toTarget, progress);
      const offset = new THREE.Vector3().setFromSpherical(new THREE.Spherical(
        THREE.MathUtils.lerp(from.radius, to.radius, progress),
        THREE.MathUtils.lerp(from.phi, to.phi, progress),
        from.theta + turn * progress,
      ));
      camera.position.copy(controls.target).add(offset);
      controls.update();
      render();
    }, window.matchMedia("(prefers-reduced-motion: reduce)").matches);
  }

  function show(layer: Layer) {
    clear();
    const geometry = layer === "before" ? before : after;
    const changed = layer === "overlay" ? new Set(after.changed ?? []) : undefined;
    const plates = layer === "before" ? previousFloors : currentFloors;
    const centre = area;
    plates.forEach((floor, index) => {
      const plate = new THREE.Group();
      plate.position.y = index * plateGap;
      group.add(plate);
      const floorGeometry: Geometry = {
        ...geometry,
        walls: floor.walls,
        rooms: floor.rooms,
        openings: floor.openings,
      };
      const result = addPlan(plate, floorGeometry, {
        frame: before === after ? floorGeometry : after,
        labels: !(presentation === "building" && plates.length > 1),
        changed,
        changedColor: "accent",
        old: layer === "overlay" ? { ...before, walls: (previousFloors.find(item => item.level === floor.level) ?? previousFloors[index])?.walls ?? [], openings: (previousFloors.find(item => item.level === floor.level) ?? previousFloors[index])?.openings ?? [], rooms: [] } : null,
      });
      if (result.anchor) {
        plate.localToWorld(result.anchor);
        anchors.push(result.anchor);
      }
      for (const room of floor.rooms) {
        roomPoints.set(room.label.toUpperCase(), new THREE.Vector3(room.x * MM, plate.position.y + 0.02, room.y * MM));
      }
      plateCentres.push(new THREE.Vector3(centre.x + centre.width / 2, plate.position.y, centre.z + centre.depth / 2));
    });
    if (presentation === "building" && plates.length > 1) {
      const topArea = footprintOf({ ...geometry, walls: plates[plates.length - 1].walls });
      const roof = new THREE.Mesh(new THREE.BoxGeometry(topArea.width + .6, .15, topArea.depth + .6),
        new THREE.MeshStandardMaterial({ color: tokenColor("--model-roof"), roughness: .8 }));
      roof.position.set(topArea.x + topArea.width / 2, (plates.length - 1) * plateGap + wallHeight + .075, topArea.z + topArea.depth / 2);
      roof.castShadow = true; roof.receiveShadow = true; group.add(roof);
      const outline = new THREE.LineSegments(new THREE.EdgesGeometry(roof.geometry), new THREE.LineBasicMaterial({ color: tokenColor("--model-edge") }));
      outline.position.copy(roof.position); group.add(outline);
    }
    renderer.shadowMap.needsUpdate = true;
    render();
  }

  controls.addEventListener("change", render);
  renderer.domElement.addEventListener("pointerdown", cancelCameraMotion, { passive: true });
  renderer.domElement.addEventListener("wheel", cancelCameraMotion, { passive: true });
  const observer = new ResizeObserver(fit);
  observer.observe(host);
  frame();

  function project(point: THREE.Vector3): ScreenPoint | null {
    const projected = point.clone().project(camera);
    if (projected.z > 1) return null;
    return { x: ((projected.x + 1) / 2) * host.clientWidth, y: ((1 - projected.y) / 2) * host.clientHeight };
  }

  return {
    show,
    rotate(radians) {
      animateCommand(() => {
      const ratio = camera.position.distanceTo(controls.target) / fitDistance(camera.aspect);
      const offset = camera.position.clone().sub(controls.target);
      offset.applyAxisAngle(new THREE.Vector3(0, 1, 0), radians);
      camera.position.copy(controls.target).add(offset);
      setDistance(fitDistance(camera.aspect) * ratio);
      });
    },
    zoom(factor) {
      animateCommand(() => {
      const distance = camera.position.distanceTo(controls.target);
      setDistance(THREE.MathUtils.clamp(distance * factor, .5, span * 12));
      });
    },
    fit() {
      animateCommand(() => {
      const offset = camera.position.clone().sub(controls.target);
      controls.target.copy(target);
      camera.position.copy(target).add(offset);
      setDistance(fitDistance(camera.aspect));
      });
    },
    reset() { animateCommand(frame); },
    points() {
      const rooms: Record<string, ScreenPoint> = {};
      for (const [label, point] of roomPoints) {
        const screen = project(point);
        if (screen) rooms[label] = screen;
      }
      return {
        primary: anchors[0] ? project(anchors[0]) : null,
        rooms,
        plates: plateCentres.map((point) => project(point)).filter((point): point is ScreenPoint => point !== null),
      };
    },
    dispose() {
      disposed = true;
      cancelAnimationFrame(renderFrame);
      cancelCameraMotion();
      observer.disconnect();
      renderer.domElement.removeEventListener("pointerdown", cancelCameraMotion);
      renderer.domElement.removeEventListener("wheel", cancelCameraMotion);
      controls.removeEventListener("change", render);
      controls.dispose();
      clear();
      groundGeometry.dispose(); groundMaterial.dispose(); grid.geometry.dispose(); gridMaterial.dispose();
      sun.shadow.dispose();
      renderer.dispose();
      renderer.forceContextLoss();
      renderer.domElement.remove();
    },
  };
}
