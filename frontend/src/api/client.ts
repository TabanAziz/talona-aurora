import type { components } from "./schema";
import { getSelectedProjectId } from "./workspace";

type S = components["schemas"];
export type Project = S["Project"];
export type RecordEntry = S["RecordEntry"];
export type Machine = S["Machine"];
export type WaitingItem = S["WaitingItem"];
export type Flag = S["Flag"];
export type Evidence = S["Evidence"];
export type DrawingDiff = S["DrawingDiff"];
export type DiffRegion = S["DiffRegion"];
export type Plan = S["Plan"];
export type Task = S["Task"];
export type ResourceLine = S["ResourceLine"];
export type Proposal = S["Proposal"];
export type TaskShift = S["TaskShift"];
export type Decision = S["Decision"];
// The generated type marks fields with a server default as required; a request may leave them out.
export type DecisionRequest = Pick<S["DecisionRequest"], "flag_id" | "action"> & Partial<S["DecisionRequest"]>;
export type OutboundMessage = S["OutboundMessage"];
export type InboundEvent = S["InboundEvent"];
export type Attachment = S["Attachment"];
export type Answer = S["Answer"];
export type IngestResult = S["IngestResult"];
export type CommandResponse = S["CommandResponse"];
export type Autonomy = S["Autonomy"];
export type AutonomySuggestion = S["AutonomySuggestion"];
export type Authorization = S["Authorization"];
export type AuthorizationApplication = S["AuthorizationApplication"];
export type AutonomyGrantRequest = S["AutonomyGrantRequest"];
export type AutonomyRevokeRequest = S["AutonomyRevokeRequest"];
export type Insights = S["Insights"];
export type StandingRule = S["StandingRule"];
export type Pattern = S["Pattern"];
export type StartCheck = S["StartCheck"];
export type StartCheckRequest = S["StartCheckRequest"];
export type StartReason = S["StartReason"];
export type Readiness = S["Readiness"];
export type ReadinessItem = S["ReadinessItem"];

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

export async function request<T>(method: "GET" | "POST" | "PUT" | "PATCH" | "DELETE", path: string, body?: unknown): Promise<T> {
  let response: Response;
  const headers = new Headers();
  const selected = getSelectedProjectId();
  if (selected && !path.startsWith("/api/workspace/projects") && !path.startsWith("/api/workspace/import")) headers.set("X-Aurora-Project", selected);
  const multipart = typeof FormData !== "undefined" && body instanceof FormData;
  if (body !== undefined && !multipart) headers.set("Content-Type", "application/json");
  try {
    response = await fetch(path, {
      method,
      headers,
      body: body === undefined ? undefined : multipart ? body as FormData : JSON.stringify(body),
    });
  } catch {
    throw new ApiError(0, "The server did not answer. Check that the backend is running.");
  }
  if (!response.ok) {
    let detail = response.statusText;
    try {
      const data = await response.json();
      if (typeof data?.detail === "string") detail = data.detail;
      else if (Array.isArray(data?.detail)) detail = data.detail.map((item: { msg?: string }) => item.msg || "Invalid input").join(". ");
    } catch {
      // a non-JSON error body keeps the status text
    }
    throw new ApiError(response.status, `${detail} (HTTP ${response.status})`);
  }
  return (await response.json()) as T;
}

const id = encodeURIComponent;

export const api = {
  project: () => request<Project>("GET", "/api/project"),
  record: () => request<RecordEntry[]>("GET", "/api/record"),
  machines: () => request<Machine[]>("GET", "/api/machines"),
  waiting: () => request<WaitingItem[]>("GET", "/api/waiting"),
  flags: () => request<Flag[]>("GET", "/api/flags"),
  flag: (flagId: string) => request<Flag>("GET", `/api/flags/${id(flagId)}`),
  diffs: () => request<DrawingDiff[]>("GET", "/api/diffs"),
  diff: (diffId: string) => request<DrawingDiff>("GET", `/api/diffs/${id(diffId)}`),
  plan: () => request<Plan>("GET", "/api/plan"),
  proposals: () => request<Proposal[]>("GET", "/api/proposals"),
  proposal: (proposalId: string) => request<Proposal>("GET", `/api/proposals/${id(proposalId)}`),
  decisions: () => request<Decision[]>("GET", "/api/decisions"),
  decide: (body: DecisionRequest) => request<Decision>("POST", "/api/decisions", body),
  canStart: (body: StartCheckRequest) => request<StartCheck>("POST", "/api/context/can-start", body),
  checks: () => request<StartCheck[]>("GET", "/api/context/checks"),
  readiness: () => request<Readiness>("GET", "/api/readiness"),
  autonomy: () => request<Autonomy>("GET", "/api/autonomy"),
  grantAutonomy: (body: AutonomyGrantRequest) => request<Authorization>("POST", "/api/autonomy/grant", body),
  revokeAutonomy: (authorizationId: string, body: AutonomyRevokeRequest) =>
    request<Authorization>("POST", `/api/autonomy/${encodeURIComponent(authorizationId)}/revoke`, body),
  events: () => request<InboundEvent[]>("GET", "/api/events"),
  outbox: () => request<OutboundMessage[]>("GET", "/api/outbox"),
  answers: () => request<Answer[]>("GET", "/api/answers"),
  insights: () => request<Insights>("GET", "/api/insights"),
  command: (text: string) => request<CommandResponse>("POST", "/api/command", { text }),
  demoNext: () => request<IngestResult | null>("POST", "/api/demo/next"),
  demoReset: () => request<Project>("POST", "/api/demo/reset"),
};
