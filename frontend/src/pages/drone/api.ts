import type { components } from "../../api/schema";
import { request } from "../../api/client";

type S = components["schemas"];
export type Machine = S["Machine"];
export type MachineReportRequest = S["MachineReportRequest"];
export type MachineReportResult = S["MachineReportResult"];
export const DRONE = "survey-drone-1";

async function call<T>(path: string, body?: unknown): Promise<T> {
  return request<T>(body === undefined ? "GET" : "POST", path, body);
}

export const droneApi = {
  machines: () => call<Machine[]>("/api/machines"),
  confirm: (sheet: string, revision: string, machine = DRONE) => call<S["MachineConfirmation"]>(`/api/machines/${encodeURIComponent(machine)}/confirm`, { sheet, revision }),
  report: (body: MachineReportRequest, machine = DRONE) => call<MachineReportResult>(`/api/machines/${encodeURIComponent(machine)}/reports`, body),
};
