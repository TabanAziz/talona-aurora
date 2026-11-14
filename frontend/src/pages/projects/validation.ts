import type { ImportDraft } from "./api";

export function validateDraft(draft: ImportDraft): string | null {
  if (!draft.project.name.trim()) return "Give the project a name before creating it.";
  const tasks = draft.plan.tasks ?? [];
  for (const task of tasks) {
    if (!task.name.trim()) return "Every task needs a name.";
    if (!Number.isFinite(Date.parse(task.start)) || !Number.isFinite(Date.parse(task.end)) || Date.parse(task.end) <= Date.parse(task.start))
      return `The end of ${task.name} must be after its start.`;
    if (!draft.project.crews.includes(task.crew)) return `Choose a listed crew for ${task.name}.`;
    if (task.unit && !draft.project.units.includes(task.unit)) return `Choose a listed room or area for ${task.name}.`;
    if (task.depends_on?.some(id => id === task.id || !tasks.some(item => item.id === id))) return `Check the dependency of ${task.name}.`;
  }
  for (const drawing of draft.drawings) {
    if (drawing.geometry && [drawing.geometry.width, drawing.geometry.height, drawing.geometry.wall_height].some(value => !Number.isFinite(value) || value <= 0))
      return `Check the dimensions of ${drawing.sheet}. Every dimension must be greater than zero.`;
  }
  for (const machine of draft.machines ?? []) {
    if (machine.units?.some(unit => !draft.project.units.includes(unit))) return `Check machine ${machine.name}: every room or area must belong to this project.`;
    if (machine.sheets?.some(sheet => !draft.project.sheets.includes(sheet))) return `Check machine ${machine.name}: every drawing must belong to this project.`;
  }
  return null;
}
