import { api, request } from "../../api/client";
import type { components } from "../../api/schema";

type MachineNotice = components["schemas"]["MachineNotice"];
type MachineConfirmation = components["schemas"]["MachineConfirmation"];

export interface Load {
  /** The revision of the sheet the robot holds, or null when it never confirmed one. */
  revision: string | null;
  /** Set when this visit took a notice: what the robot was told and that it confirmed. */
  notice: MachineNotice | null;
  confirmation: MachineConfirmation | null;
}

async function call<T>(method: "GET" | "POST", path: string, body?: unknown): Promise<T> {
  return request<T>(method, path, body);
}

export async function confirmDrawing(machine: string, sheet: string, revision: string): Promise<MachineConfirmation> {
  return call<MachineConfirmation>("POST", `/api/machines/${encodeURIComponent(machine)}/confirm`, { sheet, revision });
}

/**
 * The robot takes its notices like a crew reads its messages: the newest revision of the sheet it was told about
 * is loaded and confirmed by naming it. It can only load a revision whose geometry the page has, so a notice for
 * any other revision stays unconfirmed and the start check keeps saying so.
 */
export async function takeNotices(machine: string, sheet: string, loadable: string): Promise<Load> {
  const path = `/api/machines/${encodeURIComponent(machine)}`;
  const notices = (await call<MachineNotice[]>("GET", `${path}/notices`)).filter((notice) => notice.sheet === sheet);
  const notice = notices[notices.length - 1];
  if (notice && notice.revision === loadable) {
    const confirmation = await call<MachineConfirmation>("POST", `${path}/confirm`, { sheet, revision: loadable });
    return { revision: confirmation.revision, notice, confirmation };
  }
  // No notice to take: the robot holds what it confirmed last, which the record keeps with the robot as actor.
  const loads = (await api.record())
    .filter((entry) => entry.kind === "acknowledgement" && entry.actor === machine && entry.refs?.sheet === sheet)
    .sort((a, b) => new Date(a.at).getTime() - new Date(b.at).getTime());
  return { revision: loads[loads.length - 1]?.refs?.revision ?? null, notice: null, confirmation: null };
}
