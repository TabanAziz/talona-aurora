import type { StartCheck, StartCheckRequest, StartReason } from "../../api/client";
import type { Geometry, Room, Wall } from "../../components/plan3d/geometry";

/** The demo robot frames the partitions of the level 3 units on the A-201 plan. */
export const SHEET = "A-201";
export const UNIT = "3B";
export const ACTIVITY = "frame partitions";
export const ASKED_BY = "layout-robot-1";

export interface UnitWork {
  name: string;
  center: Room;
  walls: Wall[];
}

const LEVEL_UNIT = /^3[A-H]$/i;

/**
 * The level 3 units the drawing shows, each with the partitions nearest its room label. A wall belongs to
 * the room whose label is closest to the middle of the wall, so a moved partition still lands in its unit.
 */
export function levelUnits(geometry: Geometry, coverage?: string[]): UnitWork[] {
  const rooms = (geometry.rooms ?? []).filter((room) => coverage ? coverage.some(unit => unit.toUpperCase() === room.label.trim().toUpperCase()) : LEVEL_UNIT.test(room.label.trim()));
  const partitions = geometry.walls.filter((wall) => wall.kind === "partition");
  return rooms
    .map((room) => ({
      name: coverage?.find(unit => unit.toUpperCase() === room.label.trim().toUpperCase()) ?? room.label.trim().toUpperCase(),
      center: room,
      walls: partitions.filter((wall) => nearestRoom(geometry, wall, rooms)?.label === room.label && (!wall.level || !room.level || wall.level === room.level)),
    }))
    .filter((unit) => unit.walls.length > 0)
    .sort((a, b) => a.name.localeCompare(b.name));
}

function nearestRoom(geometry: Geometry, wall: Wall, rooms?: Room[]): Room | undefined {
  const x = (wall.x1 + wall.x2) / 2;
  const y = (wall.y1 + wall.y2) / 2;
  let best: Room | undefined;
  let distance = Number.POSITIVE_INFINITY;
  for (const room of rooms ?? geometry.rooms ?? []) {
    if (!rooms && !LEVEL_UNIT.test(room.label.trim())) continue;
    if (wall.level && room.level && wall.level !== room.level) continue;
    const next = Math.hypot(room.x - x, room.y - y);
    if (next < distance) {
      best = room;
      distance = next;
    }
  }
  return best;
}

export function startRequest(unit: string, askedBy = ASKED_BY): StartCheckRequest {
  return { asked_by: askedBy, unit, activity: ACTIVITY };
}

export function reasonsOf(answer: StartCheck | null): StartReason[] {
  return answer?.reasons ?? [];
}

export function sourcesOf(reason: StartReason): { eventId: string; quote: string }[] {
  const seen = new Set<string>();
  return (reason.sources ?? [])
    .map((source) => ({ eventId: source.event_id, quote: source.quote }))
    .filter((source) => {
      const key = `${source.eventId}\u0000${source.quote}`;
      if (seen.has(key)) return false;
      seen.add(key);
      return true;
    });
}

/** "B to C" for the revision switch line, or null while the robot still works from the old drawing. */
export function switchText(from: string | null, to: string | null): string | null {
  if (!from || !to || from === to) return null;
  return `Switched from Rev ${from} to Rev ${to}`;
}
