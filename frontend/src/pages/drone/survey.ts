import type { Geometry, Wall } from "../../components/plan3d/geometry";
import type { Machine, MachineReportRequest } from "./api";

export interface SurveyWall { unit: string; wall: Wall }

// Room labels locate walls within the registered area; the current drawing owns that assignment.
export function surveyWalls(geometry: Geometry, measured: Geometry, machine: Machine): SurveyWall[] {
  if (!(machine.sheets ?? []).includes(geometry.sheet)) return [];
  const rooms = (geometry.rooms ?? []).filter((room) => (machine.units ?? []).some(unit => unit.toUpperCase() === room.label.trim().toUpperCase()));
  return geometry.walls.flatMap((wall) => {
    const x = (wall.x1 + wall.x2) / 2;
    const y = (wall.y1 + wall.y2) / 2;
    const room = rooms.filter(room => !wall.level || !room.level || wall.level === room.level).sort((a, b) => Math.hypot(a.x - x, a.y - y) - Math.hypot(b.x - x, b.y - y))[0];
    const unit = room ? (machine.units ?? []).find(unit => unit.toUpperCase() === room.label.trim().toUpperCase()) : undefined;
    const observed = measured.walls.find((candidate) => candidate.id === wall.id);
    return unit && (machine.units ?? []).includes(unit) && observed ? [{ unit, wall: observed }] : [];
  });
}

export function wallReport(item: SurveyWall, sheet: string, flight: string, observedAt: string): MachineReportRequest {
  const { x1, y1, x2, y2 } = item.wall;
  return {
    report_id: `${flight}-${item.wall.id}`.slice(0, 40),
    kind: "wall", observed_at: observedAt, unit: item.unit, sheet, wall: item.wall.id,
    line: { x1, y1, x2, y2 },
  };
}
