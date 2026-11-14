import { request, type Machine, type Plan, type Project } from "../../api/client";
import type { Geometry } from "../../components/plan3d/geometry";

export interface ProjectSummary {
  brand?: ProjectBrand | null;
  id: string;
  name: string;
  unit_count: number;
  crew_count: number;
  sheet_count: number;
  created_at: string;
  is_default: boolean;
  deleted_at?: string;
}

export interface ProjectBrand {
  title: string;
  description: string;
  primary: string;
  accent: string;
  background: string;
  paths: { d: string; color: "primary" | "accent"; filled: boolean }[];
}

export interface DraftDrawing { sheet: string; revision: string; title?: string; geometry?: Geometry }
export interface ImportDraft {
  draft_id: string;
  project: Project;
  plan: Plan;
  drawings: DraftDrawing[];
  assumptions: string[];
  warnings: string[];
  sources: { name: string; kind: string }[];
  model_used: boolean;
  model_name?: string;
  machines?: Machine[];
}

export const workspaceApi = {
  connectDemoChannels: (id: string) => request("POST", "/api/workspace/channel-target", { project_id: id, telegram: true, email: true, telegram_group: true }),
  logo: (id: string) => request<ProjectBrand>("POST", `/api/workspace/projects/${encodeURIComponent(id)}/logo`),
  projects: () => request<{ projects: ProjectSummary[]; deleted_projects?: ProjectSummary[] }>("GET", "/api/workspace/projects"),
  remove: (id: string) => request<ProjectSummary>("DELETE", `/api/workspace/projects/${encodeURIComponent(id)}`),
  restore: (id: string) => request<ProjectSummary>("POST", `/api/workspace/projects/${encodeURIComponent(id)}/restore`),
  import: (name: string, description: string, files: File[], designBuilding = false) => {
    const data = new FormData();
    data.set("name", name.trim());
    data.set("description", description.trim());
    data.set("design_building", String(designBuilding));
    files.forEach(file => data.append("files", file));
    return request<ImportDraft>("POST", "/api/workspace/import", data);
  },
  create: (draft: ImportDraft) => request<ProjectSummary>("POST", "/api/workspace/projects", {
    draft_id: draft.draft_id, project: draft.project, plan: draft.plan, drawings: draft.drawings, machines: draft.machines,
  }),
};
