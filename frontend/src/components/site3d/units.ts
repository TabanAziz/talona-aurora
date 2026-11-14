import type { Flag, Plan, Project, Readiness, StartCheck, Task, WaitingItem } from "../../api/client";
import type { Geometry, Room } from "../plan3d/geometry";
import { levelFromLabel } from "../plan3d/floors";

export type Stage = "not_started" | "framing" | "rough_in" | "closed";

export type SiteState = "hold" | "inspection" | "confirmation" | "working" | "clear" | "unknown";

export interface SitePoint {
  kind: "flag" | "waiting" | "task" | "reason";
  id: string;
  label: string;
  detail: string;
  href: string;
}

export interface SiteUnit {
  unit: string;
  level: number;
  stage: Stage;
  state: SiteState;
  stateLabel: string;
  /** Where the unit sits on its plate, in millimetres of the drawing when level 3 gives a room label. */
  x: number;
  y: number;
  schematic: boolean;
  points: SitePoint[];
  tasks: Task[];
  crews: string[];
  /** The title of the flag that holds the unit, if one does. */
  heldBy: string | null;
}

export interface SiteFigure {
  id: string;
  kind: "crew" | "machine";
  label: string;
  unit: string;
  href: string;
}

export interface SiteModel {
  name: string;
  units: SiteUnit[];
  levels: number[];
  crews: SiteFigure[];
  machines: SiteFigure[];
  flags: Flag[];
  generatedAt: string;
  /** The day the plan is looked at: the day of the newest record entry the readiness read used. */
  day: string;
}

export interface SiteInput {
  project: Project;
  plan: Plan;
  flags: Flag[];
  waiting: WaitingItem[];
  readiness: Readiness;
  checks: StartCheck[];
  geometry: Geometry | null;
}

const STAGE_WORDS: [Stage, RegExp][] = [
  ["framing", /frame|stud|partition/i],
  ["rough_in", /rough|electrical|plumb/i],
  ["closed", /close|drywall|board|tape|finish/i],
];

/** The stage a unit is drawn in: the stage of its next open task, so a site with work ahead still shows it. */
export function stageOf(tasks: Task[]): Stage {
  const open = tasks.filter((task) => task.status !== "done").sort((a, b) => a.start.localeCompare(b.start));
  if (tasks.length > 0 && open.length === 0) return "closed";
  for (const task of open) {
    for (const [stage, pattern] of STAGE_WORDS) if (pattern.test(task.name)) return stage;
  }
  if (open.length > 0) return "framing";
  return "not_started";
}

/** The level a unit belongs to: the leading number of its name, or 1 when it has none. */
export function levelOf(unit: string): number {
  return Number(levelFromLabel(unit) ?? 1);
}

function askerKind(askedBy: string): "robot" | "agent" | "person" {
  if (/robot/i.test(askedBy)) return "robot";
  if (/agent|readiness/i.test(askedBy)) return "agent";
  return "person";
}

function dayOf(value: string): string {
  return (value ?? "").slice(0, 10);
}

/**
 * What a unit shows comes from the API, in this order: a flag that holds it, an open inspection, a
 * confirmation or another reason of the readiness check, work planned for the day, and clear when the
 * record says nothing about it. The readiness status supplies unknown, so no state is invented.
 */
export function stateOf(
  tasks: Task[],
  unit: string,
  flags: Flag[],
  readiness: Readiness,
  day: string,
): { state: SiteState; label: string; heldBy: string | null } {
  const held = flags.find((flag) => flag.status === "held" && flag.affected?.unit === unit);
  if (held) return { state: "hold", label: "Work on hold", heldBy: held.title };
  const items = (readiness.items ?? []).filter((item) => item.unit === unit || tasks.some((task) => task.id === item.task_id));
  const reasons = items.flatMap((item) => item.reasons ?? []);
  if (reasons.some((reason) => reason.kind === "inspection_open")) {
    return { state: "inspection", label: "Waiting for an inspection", heldBy: null };
  }
  const confirmation = reasons.some((reason) => reason.kind === "drawing_not_confirmed" || reason.kind === "superseded_drawing");
  if (confirmation) return { state: "confirmation", label: "Waiting for a confirmation", heldBy: null };
  if (reasons.length > 0) return { state: "confirmation", label: "Waiting on the site", heldBy: null };
  if (items.length > 0 && items.every((item) => item.status === "unknown")) {
    return { state: "unknown", label: "Unknown", heldBy: null };
  }
  const working = tasks.some((task) => task.status === "in_progress" || (task.start.slice(0, 10) <= day && day <= task.end.slice(0, 10)));
  if (working) return { state: "working", label: "In work today", heldBy: null };
  return { state: "clear", label: "Clear", heldBy: null };
}

function pointsOf(
  unit: string,
  tasks: Task[],
  flags: Flag[],
  waiting: WaitingItem[],
  readiness: Readiness,
): SitePoint[] {
  const points: SitePoint[] = [];
  for (const flag of flags.filter((item) => item.affected?.unit === unit && (item.status === "held" || item.status === "open"))) {
    points.push({ kind: "flag", id: flag.id, label: flag.title, detail: `${flag.status}, ${flag.type.replace(/_/g, " ")}`, href: `/flags/${flag.id}` });
  }
  const crews = new Set(tasks.map((task) => task.crew));
  for (const item of waiting.filter((entry) => entry.status === "open" && crews.has(entry.on))) {
    points.push({ kind: "waiting", id: item.id, label: item.what, detail: `for ${item.on}, since ${item.since.slice(0, 10)}`, href: "/crew" });
  }
  const items = (readiness.items ?? []).filter((item) => item.unit === unit || tasks.some((task) => task.id === item.task_id));
  for (const reason of items.flatMap((item) => item.reasons ?? [])) {
    points.push({
      kind: "reason",
      id: `${reason.kind}-${reason.text.slice(0, 12)}`,
      label: reason.text,
      detail: reason.blocking ? "blocking" : "not blocking",
      href: reason.flag_id ? `/flags/${reason.flag_id}` : "/plan",
    });
  }
  for (const task of tasks) {
    points.push({ kind: "task", id: task.id, label: task.name, detail: `${task.status.replace(/_/g, " ")}, starts ${task.start.slice(0, 10)}`, href: "/plan" });
  }
  return points;
}

function roomOf(geometry: Geometry | null, unit: string): Room | undefined {
  return (geometry?.rooms ?? []).find((room) => room.label.trim().toUpperCase() === unit.toUpperCase());
}

export function buildSite(input: SiteInput): SiteModel {
  const { project, plan, flags, waiting, readiness, checks, geometry } = input;
  const tasks = plan.tasks ?? [];
  const day = dayOf(readiness.generated_at) || dayOf(tasks[0]?.start ?? "");
  const units: SiteUnit[] = [];
  const unitLevel = (unit: string) => {
    const value = roomOf(geometry, unit)?.level ?? geometry?.level;
    const parsed = value === null || value === undefined ? NaN : Number(value);
    return Number.isFinite(parsed) ? parsed : levelOf(unit);
  };
  const levels = [...new Set(project.units.map(unitLevel))].sort((a, b) => a - b);
  for (const level of levels) {
    const onLevel = project.units.filter((unit) => unitLevel(unit) === level);
    onLevel.forEach((unit, index) => {
      const unitTasks = tasks.filter((task) => task.unit === unit);
      const room = roomOf(geometry, unit);
      const x = room ? room.x : (index + 0.5) / Math.max(onLevel.length, 1);
      const y = room ? room.y : 0.5;
      const state = stateOf(unitTasks, unit, flags, readiness, day);
      units.push({
        unit,
        level,
        stage: stageOf(unitTasks),
        state: state.state,
        stateLabel: state.label,
        x,
        y,
        schematic: !room,
        points: pointsOf(unit, unitTasks, flags, waiting, readiness),
        tasks: unitTasks,
        crews: [...new Set(unitTasks.map((task) => task.crew))],
        heldBy: state.heldBy,
      });
    });
  }

  const todaysTasks = tasks.filter((task) => task.status === "in_progress" || (task.start.slice(0, 10) <= day && day <= task.end.slice(0, 10)));
  const crews: SiteFigure[] = [];
  for (const task of todaysTasks) {
    if (!task.unit) continue;
    const id = `${task.crew}-${task.unit}`;
    if (crews.some((figure) => figure.id === id)) continue;
    crews.push({ id, kind: "crew", label: task.crew, unit: task.unit, href: "/crew" });
  }
  const machines: SiteFigure[] = [];
  for (const check of checks) {
    if (askerKind(check.asked_by) !== "robot" || !check.unit) continue;
    if (machines.some((figure) => figure.label === check.asked_by)) continue;
    machines.push({ id: `${check.asked_by}-${check.unit}`, kind: "machine", label: check.asked_by, unit: check.unit, href: "/robot" });
  }

  return {
    name: project.name,
    units,
    levels,
    crews,
    machines,
    flags: flags.filter((flag) => (flag.status === "held" || flag.status === "open") && flag.affected?.unit),
    generatedAt: readiness.generated_at,
    day,
  };
}

export const STATE_LABELS: Record<SiteState, string> = {
  hold: "Work on hold",
  inspection: "Waiting for an inspection",
  confirmation: "Waiting for a confirmation",
  working: "In work today",
  clear: "Clear",
  unknown: "Unknown",
};

export const STAGE_LABELS: Record<Stage, string> = {
  not_started: "not started",
  framing: "framing",
  rough_in: "rough-in",
  closed: "closed",
};
