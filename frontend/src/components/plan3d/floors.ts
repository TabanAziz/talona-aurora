import type { Geometry, Opening, Room, Wall } from "./geometry";

export interface FloorPlan {
  level: string;
  walls: Wall[];
  rooms: Room[];
  openings: Opening[];
}

export function levelFromLabel(label: string): string | null {
  const text = label.trim();
  const unit = /^(\d{1,2})\s*[A-H]$/i.exec(text);
  if (unit) return unit[1];
  const named = /(?:level|floor|storey|geschoss|og|l)\s*[-:]?\s*(\d{1,2})(?:\b|[_-])/i.exec(text);
  if (named) return named[1];
  if (/^(?:EG|GF|GROUND)(?:\b|[_-])/i.test(text)) return "0";
  return null;
}

export function splitFloors(geometry: Geometry): FloorPlan[] {
  const rooms = geometry.rooms ?? [];
  const levelFor = (room: Room) => room.level ?? geometry.level ?? levelFromLabel(room.label);
  const names = new Set<string>();
  for (const room of rooms) { const level = levelFor(room); if (level !== null && level !== undefined) names.add(String(level)); }
  for (const wall of geometry.walls) if (wall.level !== null && wall.level !== undefined) names.add(String(wall.level));
  if (geometry.level !== null && geometry.level !== undefined) names.add(String(geometry.level));
  if (names.size <= 1) return [{ level: [...names][0] ?? "", walls: geometry.walls, rooms, openings: geometry.openings ?? [] }];
  const plates = [...names].sort((a, b) => a.localeCompare(b, undefined, { numeric: true })).map(level => ({ level, walls: [] as Wall[], rooms: rooms.filter(room => String(levelFor(room)) === level), openings: [] as Opening[] }));
  for (const wall of geometry.walls) {
    let level = wall.level ?? geometry.level;
    if (level === null || level === undefined) {
      const x = (wall.x1 + wall.x2) / 2, y = (wall.y1 + wall.y2) / 2;
      const nearest = rooms.reduce<Room | undefined>((best, room) => !best || Math.hypot(room.x - x, room.y - y) < Math.hypot(best.x - x, best.y - y) ? room : best, undefined);
      level = nearest ? levelFor(nearest) : null;
    }
    (plates.find(plate => plate.level === String(level)) ?? plates[0]).walls.push(wall);
  }
  for (const plate of plates) {
    const ids = new Set(plate.walls.map(wall => wall.id));
    plate.openings = (geometry.openings ?? []).filter(opening => ids.has(opening.wall));
  }
  return plates;
}
