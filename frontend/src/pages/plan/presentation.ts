import type { Task } from "../../api/client";

/** Translate specialist wording for the schedule without changing the stored task. */
export function workName(name: string, task?: Pick<Task, "id" | "crew">): string {
  if (task && (/^layout-/i.test(task.id) || /\brobot\b/i.test(task.crew))) {
    return name.replace(/frame partitions/gi, "Mark wall positions");
  }
  return name
    .replace(/frame partitions/gi, "Build internal wall frames")
    .replace(/first[- ]fix electrical/gi, "Install wiring inside the walls")
    .replace(/first[- ]fix plumbing/gi, "Install pipes inside the walls")
    .replace(/close partitions/gi, "Close internal walls")
    .replace(/board partitions/gi, "Fit plasterboard to internal walls");
}

export const TASK_STATUS: Record<Task["status"], string> = {
  planned: "Planned",
  on_hold: "On hold",
  in_progress: "In progress",
  done: "Completed",
};

export function locationLabel(unit: Task["unit"]): string {
  if (!unit) return "Whole site";
  return /^room\b/i.test(unit) ? unit : `Room / area: ${unit}`;
}

export function dayKey(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "Date unavailable" : date.toISOString().slice(0, 10);
}
