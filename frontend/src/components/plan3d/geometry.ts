/** The drawing geometry file of one revision (contracts/README.md, "Drawing geometry"). Lengths are millimetres. */
export interface Wall {
  id: string;
  level?: string | null;
  x1: number;
  y1: number;
  x2: number;
  y2: number;
  thickness: number;
  kind: "exterior" | "interior" | "partition";
}

export interface Opening {
  wall: string;
  offset: number;
  width: number;
  kind: "door" | "window";
}

export interface Room {
  label: string;
  level?: string | null;
  x: number;
  y: number;
}

export interface Geometry {
  sheet: string;
  level?: string | null;
  revision: string;
  units: string;
  width: number;
  height: number;
  wall_height: number;
  walls: Wall[];
  openings?: Opening[];
  rooms?: Room[];
  changed?: string[];
}

export async function loadGeometry(url: string): Promise<Geometry> {
  const response = await fetch(url);
  if (!response.ok) throw new Error(`The drawing geometry could not be loaded (HTTP ${response.status}).`);
  return (await response.json()) as Geometry;
}

export interface WallPiece {
  /** Start and end along the wall, in millimetres from its first point. */
  from: number;
  to: number;
  /** Bottom and top of the piece above the floor. */
  low: number;
  high: number;
}

const SILL = 900;
const HEAD = 2100;

/**
 * A wall as boxes: the solid runs between its openings. A door leaves a gap to the floor, a window keeps
 * the wall below its sill and above its head, so the 3D view shows where people and light pass.
 */
export function wallPieces(wall: Wall, openings: Opening[], wallHeight: number): WallPiece[] {
  const length = Math.hypot(wall.x2 - wall.x1, wall.y2 - wall.y1);
  const mine = openings
    .filter((item) => item.wall === wall.id)
    .map((item) => ({ ...item, from: Math.max(0, item.offset), to: Math.min(length, item.offset + item.width) }))
    .filter((item) => item.to > item.from)
    .sort((a, b) => a.from - b.from);

  const pieces: WallPiece[] = [];
  let cursor = 0;
  for (const item of mine) {
    if (item.from > cursor) pieces.push({ from: cursor, to: item.from, low: 0, high: wallHeight });
    if (item.kind === "window") {
      pieces.push({ from: item.from, to: item.to, low: 0, high: Math.min(SILL, wallHeight) });
      pieces.push({ from: item.from, to: item.to, low: Math.min(HEAD, wallHeight), high: wallHeight });
    } else {
      pieces.push({ from: item.from, to: item.to, low: Math.min(HEAD, wallHeight), high: wallHeight });
    }
    cursor = Math.max(cursor, item.to);
  }
  if (cursor < length) pieces.push({ from: cursor, to: length, low: 0, high: wallHeight });
  return pieces.filter((piece) => piece.to > piece.from && piece.high > piece.low);
}

export function wallLength(wall: Wall): number {
  return Math.hypot(wall.x2 - wall.x1, wall.y2 - wall.y1);
}
