import * as THREE from "three";
import { splitFloors } from "../plan3d/floors";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";
import type { Geometry } from "../plan3d/geometry";
import { MM, addPlan, footprintOf, labelTexture, tokenColor } from "../plan3d/primitives";
import type { SiteModel, SiteUnit } from "./units";

export interface SiteScene {
  update(model: SiteModel, geometry: Geometry | null, selected: string | null): void;
  dispose(): void;
}

export interface SiteLayerContext {
  group: THREE.Group;
  host: HTMLElement;
  units: Map<string, THREE.Vector3>;
  centre: THREE.Vector3;
  width: number;
  depth: number;
  top: number;
  reducedMotion: boolean;
}
export interface SiteLayer { tick(now: number): boolean; dispose(): void }
export interface SiteSceneOptions {
  interactive?: boolean;
  layer?: (context: SiteLayerContext) => SiteLayer;
}

/** Distance between two floor plates, in metres. */
const LEVEL_GAP = 9;
const FENCE = 1.1;
/** The unit patches are this wide and deep, in metres; a room label from the drawing sets their centre. */
const PATCH = { width: 2.6, depth: 2.2 };
const STATE_WORD: Record<string, string> = {
  hold: "hold",
  inspection: "inspection",
  confirmation: "waiting",
  working: "in work",
  clear: "",
  unknown: "unknown",
};
const STATE_TOKENS: Record<string, string> = {
  hold: "--danger",
  inspection: "--warning",
  confirmation: "--accent",
  working: "--success",
  clear: "--text-faint",
  unknown: "--text-muted",
};

export function createSiteScene(
  host: HTMLElement,
  onSelect: (unit: string) => void,
  onOpen: (href: string) => void,
  options: SiteSceneOptions = {},
): SiteScene {
  const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
  renderer.domElement.style.display = "block";
  renderer.domElement.style.width = "100%";
  renderer.domElement.style.height = "100%";
  host.appendChild(renderer.domElement);

  const scene = new THREE.Scene();
  scene.add(new THREE.AmbientLight(0xffffff, 1.7));
  const sun = new THREE.DirectionalLight(0xffffff, 1.5);
  sun.position.set(-14, 26, 18);
  scene.add(sun);

  const camera = new THREE.PerspectiveCamera(32, 1, 0.1, 400);
  const controls = new OrbitControls(camera, renderer.domElement);
  controls.enabled = options.interactive !== false;
  controls.enablePan = false;
  controls.maxPolarAngle = THREE.MathUtils.degToRad(78);

  const group = new THREE.Group();
  scene.add(group);
  const selectable: THREE.Object3D[] = [];
  let framed = false;
  let layer: SiteLayer | null = null;
  let animation = 0;
  const reduced = window.matchMedia('(prefers-reduced-motion: reduce)');
  let latest: [SiteModel, Geometry | null, string | null] | null = null;
  let frameCount = 0;
  let frameStart = 0;

  function clear() {
    cancelAnimationFrame(animation);
    animation = 0;
    layer?.dispose();
    layer = null;
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
    selectable.length = 0;
  }

  function render() {
    renderer.render(scene, camera);
    if (options.layer) {
      const now = performance.now();
      if (!frameStart) frameStart = now;
      frameCount += 1;
      host.dataset.renderedFrames = String(frameCount);
      host.dataset.renderElapsed = String(now - frameStart);
      const corners = new THREE.Box3().setFromObject(group);
      const projected = [];
      for (const x of [corners.min.x,corners.max.x]) for (const y of [corners.min.y,corners.max.y]) for (const z of [corners.min.z,corners.max.z]) {
        projected.push(new THREE.Vector3(x,y,z).project(camera));
      }
      host.dataset.wholeSiteVisible = String(projected.every(p=>Math.abs(p.x)<=1 && Math.abs(p.y)<=1 && Math.abs(p.z)<=1));
    }
  }

  function animate(now: number) {
    animation = 0;
    const moving = layer?.tick(now);
    render();
    if (moving) animation = requestAnimationFrame(animate);
  }

  function fit() {
    const { clientWidth, clientHeight } = host;
    if (clientWidth === 0 || clientHeight === 0) return;
    renderer.setSize(clientWidth, clientHeight, false);
    camera.aspect = clientWidth / clientHeight;
    camera.updateProjectionMatrix();
    if (framed && options.layer) frame();
    render();
  }

  let site = { centre: new THREE.Vector3(0, 0, 0), top: LEVEL_GAP * 3, width: 34, depth: 28 };
  function frame() {
    const target = new THREE.Vector3(site.centre.x, site.top * 0.45, site.centre.z);
    const sphere = new THREE.Box3().setFromObject(group).getBoundingSphere(new THREE.Sphere());
    if (options.layer) target.copy(sphere.center);
    const halfAngle = Math.atan(Math.tan(THREE.MathUtils.degToRad(camera.fov/2))*Math.min(1,camera.aspect));
    const radius = Math.max(site.width * 1.05, site.depth * 1.35, site.top * 2.25,
      options.layer ? sphere.radius / Math.sin(halfAngle) * 1.08 : 0);
    const polar = THREE.MathUtils.degToRad(58);
    const azimuth = THREE.MathUtils.degToRad(26);
    camera.position.set(
      target.x + radius * Math.sin(polar) * Math.sin(azimuth),
      target.y + radius * Math.cos(polar),
      target.z + radius * Math.sin(polar) * Math.cos(azimuth),
    );
    camera.far = Math.max(400,radius*3);
    camera.updateProjectionMatrix();
    controls.target.copy(target);
    controls.minDistance = 20;
    controls.maxDistance = Math.max(120,radius*2);
    controls.update();
    framed = true;
  }

  function box(width: number, height: number, depth: number, x: number, y: number, z: number, material: THREE.Material) {
    const mesh = new THREE.Mesh(new THREE.BoxGeometry(width, height, depth), material);
    mesh.position.set(x, y + height / 2, z);
    return mesh;
  }

  function label(text: string, x: number, y: number, z: number, width: number, color: THREE.Color, size = 0.06) {
    const material = new THREE.MeshBasicMaterial({
      map: labelTexture(text, color, getComputedStyle(document.body).fontFamily),
      transparent: true,
      depthWrite: false,
    });
    const plane = new THREE.Mesh(new THREE.PlaneGeometry(width, width / 4), material);
    plane.rotation.x = -Math.PI / 2;
    plane.position.set(x, y + size, z);
    return plane;
  }

  function ground(group_: THREE.Group, centre: THREE.Vector3, width: number, depth: number) {
    const grass = new THREE.MeshLambertMaterial({ color: tokenColor("--sheet-shade") });
    group_.add(box(width, 0.12, depth, centre.x, -0.12, centre.z, grass));
    const fenceMaterial = new THREE.MeshBasicMaterial({ color: tokenColor("--text-muted") });
    const halfW = width / 2 - 1;
    const halfD = depth / 2 - 1;
    const gate = 3.4;
    group_.add(box(width - 2, FENCE, 0.06, centre.x, 0, centre.z - halfD, fenceMaterial));
    group_.add(box(0.06, FENCE, depth - 2, centre.x - halfW, 0, centre.z, fenceMaterial));
    group_.add(box(0.06, FENCE, depth - 2, centre.x + halfW, 0, centre.z, fenceMaterial));
    // The front fence stops at the gate: two pillars and an orange barrier across the opening.
    const side = (width - gate) / 2;
    group_.add(box(side, FENCE, 0.06, centre.x - (gate / 2 + side / 2), 0, centre.z + halfD, fenceMaterial));
    group_.add(box(side, FENCE, 0.06, centre.x + gate / 2 + side / 2, 0, centre.z + halfD, fenceMaterial));
    const pillar = new THREE.MeshBasicMaterial({ color: tokenColor("--accent") });
    group_.add(box(0.16, FENCE + 0.5, 0.16, centre.x - gate / 2, 0, centre.z + halfD, pillar));
    group_.add(box(0.16, FENCE + 0.5, 0.16, centre.x + gate / 2, 0, centre.z + halfD, pillar));
    const barrier = new THREE.MeshBasicMaterial({ color: tokenColor("--accent") });
    group_.add(box(gate - 0.4, 0.1, 0.08, centre.x, FENCE - 0.2, centre.z + halfD, barrier));
  }

  function plate(level: number, geometry: Geometry | null, model: SiteModel) {
    const plateGroup = new THREE.Group();
    plateGroup.position.y = level * LEVEL_GAP;
    group.add(plateGroup);
    const area = geometry ? footprintOf(geometry) : { x: -11, z: -8, width: 22, depth: 12 };
    const units = model.units.filter((unit) => unit.level === level);
    const floors = geometry ? splitFloors(geometry) : [];
    const floor = floors.find(item => item.level !== "" && Number(item.level) === level)
      ?? (floors.length === 1 && floors[0].level === "" && model.levels.length === 1 ? floors[0] : undefined);
    if (geometry && floor) {
      addPlan(plateGroup, { ...geometry, walls: floor.walls, rooms: floor.rooms, openings: floor.openings }, { frame: geometry, changedColor: "accent" });
    } else {
      const slab = new THREE.MeshLambertMaterial({ color: tokenColor("--sheet-shade") });
      const edge = new THREE.MeshBasicMaterial({ color: tokenColor("--text-muted") });
      const mesh = box(area.width + 0.4, 0.3, area.depth + 0.4, area.x + area.width / 2, -0.3, area.z + area.depth / 2, slab);
      plateGroup.add(mesh);
      const outline = new THREE.LineSegments(
        new THREE.EdgesGeometry(new THREE.BoxGeometry(area.width + 0.4, 0.3, area.depth + 0.4)),
        new THREE.LineBasicMaterial({ color: edge.color }),
      );
      outline.position.set(area.x + area.width / 2, -0.15, area.z + area.depth / 2);
      plateGroup.add(outline);
      plateGroup.add(label(`LEVEL ${level} · SCHEMATIC`, area.x + area.width / 2, 0.02, area.z + 0.6, 4.6, tokenColor("--text-muted"), 0.04));
    }
    const schematic = units.filter((item) => item.schematic);
    if (geometry && floor && schematic.length > 0) {
      // Units the drawing does not cover yet sit on an extension of the slab, named schematic.
      const stripWidth = schematic.length * 2.9;
      const stripMaterial = new THREE.MeshLambertMaterial({ color: tokenColor("--sheet-shade") });
      plateGroup.add(box(stripWidth, 0.3, 2.4, area.x + 1.2 + stripWidth / 2, -0.3, area.z + area.depth + 1.9, stripMaterial));
      plateGroup.add(label("NOT IN THE DRAWING · SCHEMATIC", area.x + 1.2 + stripWidth / 2, 0.02, area.z + area.depth + 3.0, 5.4, tokenColor("--text-muted"), 0.03));
    }
    for (const unit of units) {
      const centre = unitCentre(unit, area, units);
      const color = tokenColor(STATE_TOKENS[unit.state] ?? "--text-muted");
      const patchMaterial = new THREE.MeshBasicMaterial({ color, transparent: true, opacity: 0.32 });
      const patch = box(PATCH.width, 0.05, PATCH.depth, centre.x, 0.03, centre.z, patchMaterial);
      patch.userData.unit = unit.unit;
      plateGroup.add(patch);
      selectable.push(patch);
      const rim = new THREE.LineSegments(
        new THREE.EdgesGeometry(new THREE.BoxGeometry(PATCH.width, 0.06, PATCH.depth)),
        new THREE.LineBasicMaterial({ color }),
      );
      rim.position.copy(patch.position);
      plateGroup.add(rim);
      plateGroup.add(stageFigure(unit, centre));
      const word = STATE_WORD[unit.state] ?? "";
      const suffix = `${word ? ` · ${word}` : ""}${unit.schematic ? " · schematic" : ""}`;
      plateGroup.add(label(`${unit.unit}${suffix}`, centre.x, 0.12, centre.z + PATCH.depth / 2 + 0.45, 3.4, tokenColor("--text")));
      if (unit.heldBy) {
        plateGroup.add(label(`HOLD · ${unit.heldBy.slice(0, 46)}`, centre.x, 2.3, centre.z + PATCH.depth / 2 + 0.45, 5.6, tokenColor("--danger"), 0.05));
      }
    }
    return { plateGroup, area, units };
  }

  function unitCentre(unit: SiteUnit, area: { x: number; z: number; width: number; depth: number }, units: SiteUnit[]) {
    if (!unit.schematic) return { x: unit.x * MM, z: unit.y * MM };
    const schematic = units.filter((item) => item.schematic);
    const index = schematic.findIndex((item) => item.unit === unit.unit);
    if (unit.level === 3) {
      return { x: area.x + 1.2 + index * 2.9 + 1.45, z: area.z + area.depth + 1.9 };
    }
    const columns = Math.max(units.length, 1);
    const levelIndex = units.findIndex((item) => item.unit === unit.unit);
    return {
      x: area.x + ((levelIndex + 0.5) / columns) * area.width,
      z: area.z + area.depth / 2,
    };
  }

  function stageFigure(unit: SiteUnit, centre: { x: number; z: number }) {
    const figure = new THREE.Group();
    figure.position.set(centre.x, 0.06, centre.z);
    if (unit.stage === "not_started") return figure;
    const wall = new THREE.MeshBasicMaterial({ color: tokenColor("--ink") });
    const stud = new THREE.MeshBasicMaterial({ color: tokenColor("--ink-muted") });
    const half = { w: PATCH.width / 2 - 0.06, d: PATCH.depth / 2 - 0.06 };
    if (unit.stage === "framing") {
      const count = 5;
      for (let index = 0; index < count; index += 1) {
        const x = -half.w + (index / (count - 1)) * PATCH.width;
        figure.add(box(0.045, 1.15, 0.045, x, 0, -half.d, stud));
        figure.add(box(0.045, 1.15, 0.045, x, 0, half.d, stud));
      }
      figure.add(box(PATCH.width - 0.1, 0.06, 0.06, 0, 1.15, -half.d, stud));
      figure.add(box(PATCH.width - 0.1, 0.06, 0.06, 0, 1.15, half.d, stud));
    } else if (unit.stage === "rough_in") {
      // Open walls: two low runs with a gap, so the unit reads as framed and opened up.
      figure.add(box(PATCH.width - 0.1, 0.9, 0.1, 0, 0, -half.d, wall));
      figure.add(box(0.9, 0.9, 0.1, -half.w + 0.5, 0, half.d, wall));
      figure.add(box(0.9, 0.9, 0.1, half.w - 0.5, 0, half.d, wall));
    } else {
      figure.add(box(PATCH.width - 0.1, 2.1, 0.12, 0, 0, -half.d, wall));
      figure.add(box(0.12, 2.1, PATCH.depth - 0.1, -half.w, 0, 0, wall));
      figure.add(box(0.12, 2.1, PATCH.depth - 0.1, half.w, 0, 0, wall));
      figure.add(box(0.9, 2.1, 0.12, -half.w + 0.55, 0, half.d, wall));
      figure.add(box(0.9, 2.1, 0.12, half.w - 0.55, 0, half.d, wall));
    }
    return figure;
  }

  function figures(model: SiteModel, plates: Map<number, { area: { x: number; z: number; width: number; depth: number }; units: SiteUnit[] }>) {
    for (const figure of [...model.crews, ...model.machines]) {
      const unit = model.units.find((item) => item.unit === figure.unit);
      if (!unit) continue;
      const plate = plates.get(unit.level);
      if (!plate) continue;
      const centre = unitCentre(unit, plate.area, plate.units);
      const offset = figure.kind === "machine" ? 0.95 : -0.95;
      const x = centre.x + offset;
      const z = centre.z + PATCH.depth / 2 + 0.35;
      const color = figure.kind === "machine" ? tokenColor("--accent") : tokenColor("--text");
      const body = box(figure.kind === "machine" ? 0.5 : 0.3, figure.kind === "machine" ? 0.45 : 1.15, figure.kind === "machine" ? 0.6 : 0.3, x, 0.05, z, new THREE.MeshBasicMaterial({ color }));
      body.userData.href = figure.href;
      const target = new THREE.Group();
      target.position.y = unit.level * LEVEL_GAP;
      target.add(body);
      target.add(label(`${figure.kind === "machine" ? "MACHINE" : "CREW"} · ${figure.label}`, x, 1.35, z, 3.6, color, 0.04));
      group.add(target);
      selectable.push(body);
    }
  }

  function update(model: SiteModel, geometry: Geometry | null, selected: string | null) {
    latest = [model,geometry,selected];
    clear();
    const footprint = geometry ? footprintOf(geometry) : { x: -11, z: -8, width: 22, depth: 12 };
    const centre = new THREE.Vector3(footprint.x + footprint.width / 2, 0, footprint.z + footprint.depth / 2);
    const width = footprint.width + 10;
    const depth = footprint.depth + 8;
    site = { centre, top: Math.max(...model.levels) * LEVEL_GAP, width, depth };
    ground(group, centre, width, depth);
    const plates = new Map<number, { area: { x: number; z: number; width: number; depth: number }; units: SiteUnit[]; plate: THREE.Group }>();
    for (const level of model.levels) {
      const data = plate(level, geometry, model);
      plates.set(level, { area: data.area, units: data.units, plate: data.plateGroup });
    }
    if (!options.layer) figures(model, plates);
    if (options.layer) {
      const units = new Map<string, THREE.Vector3>();
      for (const unit of model.units) {
        const plate = plates.get(unit.level);
        if (!plate) continue;
        const centre = unitCentre(unit,plate.area,plate.units);
        units.set(unit.unit,new THREE.Vector3(centre.x,unit.level*LEVEL_GAP+0.15,centre.z));
      }
      layer = options.layer({group,host,units,centre,width,depth,top:site.top,reducedMotion:reduced.matches});
      host.dataset.reducedMotion = String(reduced.matches);
      layer.tick(performance.now());
      frameCount = 0;
      frameStart = 0;
    }
    if (selected) {
      const unit = model.units.find((item) => item.unit === selected);
      const plate = unit ? plates.get(unit.level) : undefined;
      if (unit && plate) {
        const centre = unitCentre(unit, plate.area, plate.units);
        const ring = new THREE.Mesh(
          new THREE.TorusGeometry(1.75, 0.045, 6, 32),
          new THREE.MeshBasicMaterial({ color: tokenColor("--accent") }),
        );
        ring.rotation.x = -Math.PI / 2;
        ring.position.set(centre.x, 0.1, centre.z);
        plate.plate.add(ring);
      }
    }
    if (!framed || options.layer) frame();
    render();
    if (layer && !reduced.matches) animation = requestAnimationFrame(animate);
  }

  let down: { x: number; y: number } | null = null;
  function onPointerDown(event: PointerEvent) {
    down = { x: event.clientX, y: event.clientY };
  }
  function onPointerUp(event: PointerEvent) {
    if (!down) return;
    const moved = Math.hypot(event.clientX - down.x, event.clientY - down.y);
    down = null;
    if (moved > 6) return;
    const rect = renderer.domElement.getBoundingClientRect();
    const pointer = new THREE.Vector2(
      ((event.clientX - rect.left) / rect.width) * 2 - 1,
      -((event.clientY - rect.top) / rect.height) * 2 + 1,
    );
    const raycaster = new THREE.Raycaster();
    raycaster.setFromCamera(pointer, camera);
    const hit = raycaster.intersectObjects(selectable, false)[0];
    if (!hit) return;
    const href = hit.object.userData.href as string | undefined;
    if (href) {
      onOpen(href);
      return;
    }
    const unit = hit.object.userData.unit as string | undefined;
    if (unit) onSelect(unit);
  }
  if (options.interactive !== false) {
    renderer.domElement.addEventListener("pointerdown", onPointerDown);
    renderer.domElement.addEventListener("pointerup", onPointerUp);
  }
  const motionChanged = () => { if (latest) update(...latest); };
  reduced.addEventListener('change',motionChanged);
  controls.addEventListener("change", render);
  const observer = new ResizeObserver(fit);
  observer.observe(host);
  fit();

  return {
    update,
    dispose() {
      renderer.domElement.removeEventListener("pointerdown", onPointerDown);
      renderer.domElement.removeEventListener("pointerup", onPointerUp);
      observer.disconnect();
      reduced.removeEventListener('change',motionChanged);
      controls.removeEventListener("change", render);
      controls.dispose();
      clear();
      renderer.dispose();
      renderer.domElement.remove();
    },
  };
}
