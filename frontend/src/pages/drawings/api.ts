import { request } from "../../api/client";
import { loadGeometry, type Geometry } from "../../components/plan3d/geometry";

export interface DrawingRevision {
  revision: string;
  pdf_url: string | null;
  image_url: string | null;
  geometry_url: string | null;
  received_at: string | null;
  source_event_ids: string[];
  has_geometry: boolean;
}
export interface DrawingSheet { id: string; title: string; current_revision: string | null; revisions: DrawingRevision[] }
export interface DrawingRegister { sheets: DrawingSheet[]; model_name?: string; model_summary?: string }
export const drawingsApi = { list: () => request<DrawingRegister>("GET", "/api/workspace/drawings") };

export async function loadProjectGeometry(): Promise<Geometry | null> {
  const register = await drawingsApi.list();
  const architectural = register.sheets.filter(sheet => /^A[-_]/i.test(sheet.id));
  const buildingSheets = architectural.length ? architectural : register.sheets;
  const urls = buildingSheets.map(sheet => sheet.revisions.find(revision => revision.revision === sheet.current_revision)?.geometry_url).filter((url): url is string => !!url);
  const drawings = await Promise.all([...new Set(urls)].map(loadGeometry));
  if (!drawings.length) return null;
  if (drawings.length === 1) return drawings[0];
  return {
    sheet: "Project", revision: drawings.map(drawing => `${drawing.sheet}:${drawing.revision}`).join(" / "), units: "mm",
    width: Math.max(...drawings.map(drawing => drawing.width)), height: Math.max(...drawings.map(drawing => drawing.height)),
    wall_height: Math.max(...drawings.map(drawing => drawing.wall_height)),
    walls: drawings.flatMap((drawing, index) => drawing.walls.map(wall => ({ ...wall, id: `${index}:${wall.id}`, level: wall.level ?? drawing.level }))),
    openings: drawings.flatMap((drawing, index) => (drawing.openings ?? []).map(opening => ({ ...opening, wall: `${index}:${opening.wall}` }))),
    rooms: drawings.flatMap(drawing => (drawing.rooms ?? []).map(room => ({ ...room, level: room.level ?? drawing.level }))),
    changed: drawings.flatMap((drawing, index) => (drawing.changed ?? []).map(id => `${index}:${id}`)),
  };
}
