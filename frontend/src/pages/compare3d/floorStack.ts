/** The exploded floor stack of a drawing: one plate per floor that has walls, and the callouts that explain it. */
import type { DrawingDiff, Plan, Task } from "../../api/client";
import type { Geometry, Opening, Room, Wall } from "../../components/plan3d/geometry";

export interface Floor {
  /** The level this plate shows, for example "3". */
  level: string;
  walls: Wall[];
  rooms: Room[];
  openings: Opening[];
}

export interface Callout {
  id: string;
  /** Two lines: what it is, and the fact about it. */
  lines: [string, string];
  primary: boolean;
  /** Where the leader line ends: the changed wall, or the room of the affected unit. */
  target: "wall" | Room;
}

const UNIT_LABEL = /^(\d{1,2})\s*([A-H])$/i;
const LEVEL_IN_LABEL = /level\s*(\d{1,2})/i;
const UNIT_IN_TEXT = /(?:^|[\s,(])(\d{1,2}[A-H])(?![\w-])/i;

/** The level a room label names: "3B" is level 3, "LEVEL 3 CORRIDOR" is level 3. */
export function levelOf(label: string): string | null {
  const text = (label ?? "").trim();
  const unit = UNIT_LABEL.exec(text);
  if (unit) return unit[1];
  const named = LEVEL_IN_LABEL.exec(text);
  return named ? named[1] : null;
}

function openingsOf(geometry: Geometry, walls: Wall[]): Opening[] {
  const ids = new Set(walls.map((wall) => wall.id));
  return (geometry.openings ?? []).filter((opening) => ids.has(opening.wall));
}

function nearestRoom(wall: Wall, rooms: Room[]): Room | null {
  const x = (wall.x1 + wall.x2) / 2;
  const y = (wall.y1 + wall.y2) / 2;
  let best: Room | null = null;
  let bestDistance = Infinity;
  for (const room of rooms) {
    const distance = Math.hypot(room.x - x, room.y - y);
    if (distance < bestDistance) {
      best = room;
      bestDistance = distance;
    }
  }
  return best;
}

/**
 * The plates the geometry supports. A sheet with one floor is one plate. With several floors, a wall belongs to
 * the plate of the room it is nearest to, so every plate carries real walls and a floor without walls gets none.
 */
export function floorsOf(geometry: Geometry, unitLabels: string[] = []): Floor[] {
  const rooms = geometry.rooms ?? [];
  const byLevel = new Map<string, Room[]>();
  for (const room of rooms) {
    const level = levelOf(room.label);
    if (!level) continue;
    byLevel.set(level, [...(byLevel.get(level) ?? []), room]);
  }
  if (byLevel.size <= 1) {
    return [{
      level: byLevel.size === 1 ? [...byLevel.keys()][0] : "",
      walls: geometry.walls,
      rooms,
      openings: geometry.openings ?? [],
    }];
  }
  const levels = [...byLevel.entries()].sort(([a], [b]) => Number(a) - Number(b));
  const plates = levels.map(([level, levelRooms]) => ({
    level, rooms: levelRooms, walls: [] as Wall[], openings: [] as Opening[],
  }));
  const extras = rooms.filter((room) => !levelOf(room.label));
  for (const wall of geometry.walls) {
    const room = nearestRoom(wall, rooms);
    const level = room ? levelOf(room.label) : null;
    const plate = plates.find((candidate) => candidate.level === level) ?? plates[0];
    plate.walls.push(wall);
  }
  for (const plate of plates) {
    plate.rooms = [...plate.rooms, ...extras];
    plate.openings = openingsOf(geometry, plate.walls);
  }
  return plates.filter((plate) => plate.walls.length > 0 || unitLabels.includes(plate.level));
}

/** The unit names a wall change touches, from the region label and, failing that, the room nearest the wall. */
export function unitsOf(diff: DrawingDiff, geometry?: Geometry): string[] {
  const found = new Set<string>();
  for (const region of diff.regions ?? []) {
    const unit = UNIT_IN_TEXT.exec(region.label ?? "");
    if (unit) found.add(unit[1].toUpperCase());
  }
  const changed = new Set(geometry?.changed ?? []);
  for (const wall of geometry?.walls ?? []) {
    if (!changed.has(wall.id)) continue;
    const room = nearestRoom(wall, geometry?.rooms ?? []);
    const unit = UNIT_IN_TEXT.exec(room?.label ?? "");
    if (unit) found.add(unit[1].toUpperCase());
  }
  return [...found];
}

function split(label: string | null | undefined): [string, string] {
  const text = (label ?? "").trim();
  const comma = text.indexOf(",");
  if (comma === -1) return [text || "Changed wall", ""];
  return [text.slice(0, comma).trim(), text.slice(comma + 1).trim()];
}

/** The one plaque the view exists for: the changed wall, with how far it moved and between which revisions. */
export function primaryCallout(diff: DrawingDiff): Callout {
  const [what, how] = split(diff.regions?.[0]?.label);
  const revisions = `Rev ${diff.from_rev} to ${diff.to_rev}`;
  return {
    id: "primary",
    lines: [what, how ? `${how}, ${revisions}` : revisions],
    primary: true,
    target: "wall",
  };
}

function clock(value: string | undefined): string {
  const date = new Date(value ?? "");
  if (Number.isNaN(date.getTime())) return "";
  return date.toLocaleTimeString("en-US", { hour: "2-digit", minute: "2-digit", hour12: false, timeZone: "UTC" });
}

function day(value: string | undefined): string {
  const date = new Date(value ?? "");
  if (Number.isNaN(date.getTime())) return "";
  return date.toLocaleDateString("en-GB", { day: "numeric", month: "short", timeZone: "UTC" });
}

/** The tasks the change touches: the plan's tasks in those units, the next ones first. */
export function affectedTasks(plan: Plan | undefined, units: string[], limit = 3): Task[] {
  if (!plan) return [];
  const wanted = new Set(units.map((unit) => unit.toUpperCase()));
  return [...(plan.tasks ?? [])]
    .filter((task) => task.unit && wanted.has(task.unit.toUpperCase()))
    .sort((a, b) => a.start.localeCompare(b.start))
    .slice(0, limit);
}

/** Two secondary plaques at most say what has to happen: the task, or the inspection that gates it. */
export function secondaryCallouts(tasks: Task[], rooms: Room[]): Callout[] {
  return tasks.slice(0, 3).map((task, index) => {
    const unit = task.unit ?? "";
    const room = rooms.find((candidate) => (candidate.label ?? "").toUpperCase() === unit.toUpperCase())
      ?? rooms.find((candidate) => levelOf(candidate.label) === levelOf(unit));
    const when = task.start ? `${day(task.start)} ${clock(task.start)}` : "no start";
    const fact = task.requires_inspection
      ? `Needs ${task.requires_inspection} first, ${task.crew}, ${when}`
      : `${task.crew}, starts ${when}`;
    return {
      id: `task-${task.id}-${index}`,
      lines: [task.name, fact],
      primary: false,
      target: room ?? "wall",
    };
  });
}

/** For a plaque: "crew, starts HH:MM", the small uppercase meta line of the directory. */
export function taskMeta(task: Task): string {
  return `${task.crew}, starts ${day(task.start)} ${clock(task.start)}`.trim();
}

/** One row per affected unit for the directory's first column. */
export function unitRows(units: string[], tasks: Task[]): { name: string; meta: string }[] {
  return units.map((unit) => {
    const own = tasks.filter((task) => (task.unit ?? "").toUpperCase() === unit.toUpperCase());
    return { name: `Unit ${unit}`, meta: own.length === 1 ? "1 task affected" : `${own.length} tasks affected` };
  });
}
