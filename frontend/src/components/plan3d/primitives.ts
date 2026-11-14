import * as THREE from "three";
import { mergeGeometries } from "three/examples/jsm/utils/BufferGeometryUtils.js";
import { wallLength, wallPieces, type Geometry, type Wall } from "./geometry";

/** Millimetres to metres: the geometry file is in millimetres, the scene in metres. */
export const MM = 0.001;
const SLAB = 150;
/** The floor reaches this far past the outer walls, in metres. */
const MARGIN = 0.3;
/** The line the robot chalked on the slab lies this high above the floor, in metres. */
const CHALK = 0.02;

/** Colors come from the design tokens, so a 3D view follows the theme like every other part of the page. */
export function tokenColor(name: string): THREE.Color {
  return new THREE.Color(getComputedStyle(document.documentElement).getPropertyValue(name).trim());
}

export function hatchTexture(color: THREE.Color): THREE.CanvasTexture {
  const size = 64;
  const canvas = document.createElement("canvas");
  canvas.width = size;
  canvas.height = size;
  const context = canvas.getContext("2d");
  if (context) {
    context.fillStyle = "rgba(255, 255, 255, 0.55)";
    context.fillRect(0, 0, size, size);
    context.strokeStyle = `#${color.getHexString()}`;
    context.lineWidth = 6;
    for (let offset = -size; offset <= size * 2; offset += 16) {
      context.beginPath();
      context.moveTo(offset, size);
      context.lineTo(offset + size, 0);
      context.stroke();
    }
  }
  const texture = new THREE.CanvasTexture(canvas);
  texture.wrapS = THREE.RepeatWrapping;
  texture.wrapT = THREE.RepeatWrapping;
  texture.colorSpace = THREE.SRGBColorSpace;
  return texture;
}

export function labelTexture(text: string, color: THREE.Color, font: string): THREE.CanvasTexture {
  const canvas = document.createElement("canvas");
  canvas.width = 512;
  canvas.height = 128;
  const context = canvas.getContext("2d");
  if (context) {
    context.fillStyle = `#${color.getHexString()}`;
    context.font = `600 ${Math.min(64, 440 / Math.max(1, text.length * .58))}px ${font}`;
    context.textAlign = "center";
    context.textBaseline = "middle";
    context.fillText(text, canvas.width / 2, canvas.height / 2);
  }
  const texture = new THREE.CanvasTexture(canvas);
  texture.colorSpace = THREE.SRGBColorSpace;
  return texture;
}

/** A box from a piece of a wall: centred on the wall line, `thickness` wide, from `low` to `high` above the floor. */
export function wallBoxGeometry(wall: Wall, from: number, to: number, low: number, high: number): THREE.BoxGeometry {
  const length = to - from;
  const geometry = new THREE.BoxGeometry(length * MM, (high - low) * MM, wall.thickness * MM);
  const total = wallLength(wall);
  const ux = (wall.x2 - wall.x1) / total;
  const uy = (wall.y2 - wall.y1) / total;
  const middle = (from + to) / 2;
  geometry.rotateY(-Math.atan2(uy, ux));
  geometry.translate((wall.x1 + ux * middle) * MM, ((low + high) / 2) * MM, (wall.y1 + uy * middle) * MM);
  return geometry;
}

/** The footprint of the building in metres. The sheet is larger than the building, and the camera frames the building. */
export function footprintOf(geometry: Geometry): { x: number; z: number; width: number; depth: number } {
  if (!geometry.walls.length) return { x: 0, z: 0, width: geometry.width * MM, depth: geometry.height * MM };
  const half = (wall: Wall) => wall.thickness / 2;
  const x0 = Math.min(...geometry.walls.map((wall) => Math.min(wall.x1, wall.x2) - half(wall)));
  const x1 = Math.max(...geometry.walls.map((wall) => Math.max(wall.x1, wall.x2) + half(wall)));
  const y0 = Math.min(...geometry.walls.map((wall) => Math.min(wall.y1, wall.y2) - half(wall)));
  const y1 = Math.max(...geometry.walls.map((wall) => Math.max(wall.y1, wall.y2) + half(wall)));
  return { x: x0 * MM, z: y0 * MM, width: (x1 - x0) * MM, depth: (y1 - y0) * MM };
}

/** A short line on the slab along one wall: what the robot chalked before it raised the wall. */
export function chalkBox(wall: Wall): THREE.BoxGeometry {
  const total = wallLength(wall);
  const geometry = new THREE.BoxGeometry(total * MM, CHALK, wall.thickness * MM);
  geometry.rotateY(-Math.atan2(wall.y2 - wall.y1, wall.x2 - wall.x1));
  geometry.translate(
    ((wall.x1 + wall.x2) / 2) * MM,
    CHALK / 2,
    ((wall.y1 + wall.y2) / 2) * MM,
  );
  return geometry;
}

export interface PlanOptions {
  labels?: boolean;
  /** The geometry that sets the floor and the framing, when it differs from the one drawn. */
  frame?: Geometry;
  /** Ids of walls that changed; they are drawn in the success color, or the accent color when asked for. */
  changed?: Set<string>;
  /** The color of a changed wall: the success green by default, the attention accent in the floor stack. */
  changedColor?: "success" | "accent";
  /** Ids of walls the robot has laid out; a chalk line marks each. */
  marked?: Set<string>;
  /** The revision before the change, drawn as a hatched red ghost of the changed walls. */
  old?: Geometry | null;
}

export interface PlanResult {
  /** The top middle of the last changed wall, for a label, or null when nothing is highlighted. */
  anchor: THREE.Vector3 | null;
}

/** Slab, walls with their openings, room labels, the old positions of changed walls and the robot's chalk lines. */
export function addPlan(group: THREE.Group, geometry: Geometry, options: PlanOptions): PlanResult {
  const frame = options.frame ?? geometry;
  const ink = tokenColor("--ink");
  const grey = tokenColor("--ink-muted");
  const added = tokenColor(options.changedColor === "accent" ? "--accent" : "--success");
  const removed = tokenColor("--danger");
  const accent = tokenColor("--accent");
  const font = getComputedStyle(document.body).fontFamily;
  const area = footprintOf(frame);
  const target = new THREE.Vector3(area.x + area.width / 2, 0, area.z + area.depth / 2);
  let anchor: THREE.Vector3 | null = null;

  const edge = new THREE.MeshStandardMaterial({ color: tokenColor("--model-wall-top"), roughness: .85 });
  const slab = new THREE.Mesh(
    new THREE.BoxGeometry(area.width + MARGIN * 2, SLAB * MM, area.depth + MARGIN * 2),
    [edge, edge, new THREE.MeshStandardMaterial({ color: tokenColor("--model-slab"), roughness: .95 }), edge, edge, edge],
  );
  slab.position.set(target.x, (-SLAB * MM) / 2, target.z);
  slab.receiveShadow = true;
  slab.castShadow = true;
  group.add(slab);
  const slabOutline = new THREE.LineSegments(new THREE.EdgesGeometry(slab.geometry), new THREE.LineBasicMaterial({ color: tokenColor("--model-edge"), transparent: true, opacity: .5 }));
  slabOutline.position.copy(slab.position); group.add(slabOutline);

  const sides = { exterior: tokenColor("--model-wall"), interior: tokenColor("--model-inner"), partition: tokenColor("--model-partition") };
  const tops = { exterior: tokenColor("--model-wall-top"), interior: tokenColor("--model-inner-top"), partition: tokenColor("--model-partition-top") };
  const chalk = new THREE.MeshBasicMaterial({ color: accent });
  const wallGeometries: THREE.BufferGeometry[] = [];
  const chalkGeometries: THREE.BufferGeometry[] = [];

  for (const wall of geometry.walls) {
    const isChanged = Boolean(options.changed?.has(wall.id));
    const side = isChanged ? added : sides[wall.kind];
    const top = isChanged ? added : tops[wall.kind];
    for (const piece of wallPieces(wall, geometry.openings ?? [], geometry.wall_height)) {
      const box = wallBoxGeometry(wall, piece.from, piece.to, piece.low, piece.high);
      const normals = box.getAttribute("normal");
      const colors = new Float32Array(normals.count * 3);
      for (let index = 0; index < normals.count; index++) {
        const color = normals.getY(index) > .5 ? top : side;
        colors[index*3] = color.r; colors[index*3+1] = color.g; colors[index*3+2] = color.b;
      }
      box.setAttribute("color", new THREE.BufferAttribute(colors, 3));
      box.clearGroups();
      wallGeometries.push(box);
    }
    if (isChanged) {
      const middle = wallLength(wall) / 2;
      const ux = (wall.x2 - wall.x1) / wallLength(wall);
      const uy = (wall.y2 - wall.y1) / wallLength(wall);
      anchor = new THREE.Vector3(
        (wall.x1 + ux * middle) * MM,
        geometry.wall_height * MM,
        (wall.y1 + uy * middle) * MM,
      );
    }
    if (options.marked?.has(wall.id)) chalkGeometries.push(chalkBox(wall));
  }

  if (wallGeometries.length) {
    const merged = mergeGeometries(wallGeometries, false);
    if (merged) {
      const mesh = new THREE.Mesh(merged, new THREE.MeshStandardMaterial({ vertexColors: true, roughness: .85, polygonOffset: true, polygonOffsetFactor: 1, polygonOffsetUnits: 1 }));
      mesh.castShadow = true; mesh.receiveShadow = true; group.add(mesh);
      group.add(new THREE.LineSegments(new THREE.EdgesGeometry(merged, 35), new THREE.LineBasicMaterial({ color: tokenColor("--model-edge"), transparent: true, opacity: .72 })));
    }
    wallGeometries.forEach(geometry => geometry.dispose());
  }
  if (chalkGeometries.length) {
    const merged = mergeGeometries(chalkGeometries, false);
    if (merged) group.add(new THREE.Mesh(merged, chalk));
    chalkGeometries.forEach(geometry => geometry.dispose());
  } else chalk.dispose();
  const glass: THREE.BufferGeometry[] = [];
  const wallsById = new Map(geometry.walls.map(wall => [wall.id, wall]));
  for (const opening of geometry.openings ?? []) {
    const wall = wallsById.get(opening.wall);
    if (opening.kind !== "window" || !wall || geometry.wall_height <= 900) continue;
    glass.push(wallBoxGeometry({ ...wall, thickness: Math.min(wall.thickness, 12) }, opening.offset, opening.offset + opening.width, 900, Math.min(2100, geometry.wall_height)));
  }
  if (glass.length) {
    const merged = mergeGeometries(glass, false);
    if (merged) group.add(new THREE.Mesh(merged, new THREE.MeshStandardMaterial({ color: tokenColor("--model-glass"), transparent: true, opacity: .6, roughness: .25, metalness: .1, depthWrite: false })));
    glass.forEach(geometry => geometry.dispose());
  }

  if (options.old) {
    const texture = hatchTexture(removed);
    const material = new THREE.MeshBasicMaterial({ map: texture, transparent: true, depthWrite: false });
    const outline = new THREE.LineDashedMaterial({ color: removed, dashSize: 0.18, gapSize: 0.12 });
    const previous = new Map(options.old.walls.map((wall) => [wall.id, wall]));
    for (const wall of geometry.walls) {
      if (!options.changed?.has(wall.id)) continue;
      const old = previous.get(wall.id);
      if (!old) continue;
      const box = wallBoxGeometry(old, 0, wallLength(old), 0, geometry.wall_height);
      const uv = box.getAttribute("uv");
      const repeat = Math.max(1, Math.round((wallLength(old) * MM) / 0.6));
      for (let index = 0; index < uv.count; index++) uv.setXY(index, uv.getX(index) * repeat, uv.getY(index) * 3);
      group.add(new THREE.Mesh(box, material));
      const lines = new THREE.LineSegments(new THREE.EdgesGeometry(box), outline);
      lines.computeLineDistances();
      group.add(lines);
    }
  }

  for (const room of options.labels === false ? [] : geometry.rooms ?? []) {
    const neighbours = (geometry.rooms ?? []).filter((other) => other !== room).map((other) => Math.hypot(room.x - other.x, room.y - other.y) * MM);
    const separation = neighbours.length ? Math.min(...neighbours) * .72 : 3;
    const labelWidth = Math.max(.8, Math.min(2.8, separation, .75 + room.label.length * .11));
    const plane = new THREE.Mesh(
      new THREE.PlaneGeometry(labelWidth, labelWidth / 4),
      new THREE.MeshBasicMaterial({ map: labelTexture(room.label, grey.clone().lerp(ink, .25), font), transparent: true, depthWrite: false }),
    );
    plane.rotation.x = -Math.PI / 2;
    plane.position.set(room.x * MM, 0.02, room.y * MM);
    group.add(plane);
  }

  return { anchor };
}
