const PROJECT_KEY = "aurora-project-id";

function savedProjectId(): string | null {
  const linked = new URLSearchParams(window.location.search).get("project");
  if (linked && /^[A-Za-z0-9][A-Za-z0-9_.-]{0,99}$/.test(linked)) {
    try { localStorage.setItem(PROJECT_KEY, linked); } catch { /* The link still selects this page's project. */ }
    return linked;
  }
  try { return localStorage.getItem(PROJECT_KEY) || null; }
  catch { return null; }
}

// Keep each open page bound to one project, even when another tab changes the saved selection.
const selectedProjectId = savedProjectId();
export function getSelectedProjectId(): string | null { return selectedProjectId; }

export function projectApiUrl(path: string): string {
  if (!selectedProjectId || !path.startsWith("/api/")) return path;
  return `${path}${path.includes("?") ? "&" : "?"}project=${encodeURIComponent(selectedProjectId)}`;
}

export function selectProject(id: string): void {
  if (!id.trim()) throw new Error("Choose a project to open.");
  localStorage.setItem(PROJECT_KEY, id);
  window.location.assign("/");
}

export function clearSelectedProject(): void {
  localStorage.removeItem(PROJECT_KEY);
  window.location.assign("/projects");
}
