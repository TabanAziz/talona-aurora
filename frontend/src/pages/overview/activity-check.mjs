import assert from "node:assert/strict";
import { chromium } from "playwright";

const base = process.env.BASE_URL || "http://127.0.0.1:5193";
const browser = await chromium.launch({ headless: true });
const page = await browser.newPage();
const pageErrors = [];
page.on("pageerror", error => pageErrors.push(error.message));
const flags = [{ id: "flag-1", type: "stale_drawing", status: "open", severity: "high", title: "Crew plans to build from revision B", summary: "A-201 revision C moved the partition in unit 3B. The crew still names revision B.", raised_at: "2026-11-14T09:00:00Z", work_starts_at: null, affected: { unit: "3B" }, evidence: [], numbers: {} }];
const records = Array.from({ length: 129 }, (_, i) => ({ id: `record-${i}`, kind: "change", title: `Recorded site change ${i + 1}`, at: "2026-11-14T09:00:00Z", actor: "Aurora", refs: {}, source_event_ids: [] }));
let failActivity = false;
const job = {
  id: "activity-1", event_id: "email-1", channel: "email", sender: "Elena Fischer",
  subject: "A-201 revision C", status: "processing", started_at: "2026-11-14T09:00:00Z",
  updated_at: "2026-11-14T09:00:01Z", finished_at: null, stage: "drawings",
  stages: [
    { id: "extract", label: "Read message", status: "completed" },
    { id: "drawings", label: "Compare drawings", status: "processing" },
    { id: "delivery", label: "Notify crew", status: "pending" },
  ],
  result: { flag_ids: [], diff_ids: [], message_ids: [], record_ids: [], outcome: "processed" },
};
try {
  await page.route("**/api/**", async route => {
    const path = new URL(route.request().url()).pathname;
    if (!path.startsWith("/api/")) return route.continue();
    if (path === "/api/activity" && failActivity) return route.fulfill({ status: 503, json: { detail: "Activity temporarily unavailable" } });
    const value = path === "/api/activity" ? { jobs: [job] }
      : path === "/api/project" ? { name: "Maple Court", id: "current" }
      : path === "/api/plan" ? { tasks: [], resources: [], handover: "" }
      : path === "/api/flags" ? flags
      : path === "/api/record" ? records
      : path === "/api/workspace/connections" ? { project_id: "custom-project", is_default: false, connections: [
        { id: "email", label: "Email", status: "unconfigured", inbound_enabled: false, outbound_enabled: false, detail: "Connect this project's own channel" },
        { id: "telegram", label: "Telegram", status: "unconfigured", inbound_enabled: false, outbound_enabled: false, detail: "Connect this project's own channel" },
        { id: "whatsapp", label: "WhatsApp", status: "unconfigured", inbound_enabled: false, outbound_enabled: false, detail: "Connect this project's own channel" },
      ] }
      : [];
    await route.fulfill({ json: value });
  });
  await page.route("**/health", route => route.fulfill({ json: { status: "ok", mocks: { email_api: false, telegram_api: true } } }));
  await page.goto(base);
  const activity = page.getByTestId("overview-activity");
  await activity.waitFor({ timeout: 6000 });
  await page.getByTestId("activity-current").filter({ hasText: "A-201 revision C" }).waitFor();
  assert.match(await activity.innerText(), /Compare drawings/);
  assert.equal(await activity.locator('[data-stage-state="processing"]').count(), 1);
  assert.equal(await activity.locator('[data-stage-state="pending"]').count(), 1);
  const connections = page.getByTestId("overview-connections");
  await connections.waitFor();
  assert.equal(await connections.getByText("Not connected", { exact: true }).count(), 3);
  assert.doesNotMatch(await connections.innerText(), /Enabled|Configured|Simulated/);
  assert.equal(await page.locator(".overview-history").getAttribute("open"), null);
  assert.match(await page.locator(".overview-history > summary").innerText(), /129 entries/);
  for (const width of [1280, 1920, 390]) {
    await page.setViewportSize({ width, height: width === 390 ? 844 : 800 });
    await page.screenshot({ path: `evidence/overview-processing-${width}.png`, fullPage: true });
  }
  failActivity = true;
  const stale = page.getByTestId("activity-stale");
  await stale.waitFor({ state: "visible", timeout: 6000 });
  assert.match(await page.getByTestId("activity-current").innerText(), /A-201 revision C/);
  assert.match(await stale.innerText(), /Last successful refresh/);
  assert.doesNotMatch(await activity.innerText(), /Listening for updates/);
  assert.equal(await activity.locator(".activity-stage-processing .activity-stage-mark > span").evaluate(element => getComputedStyle(element).animationName), "none");
  await page.screenshot({ path: "evidence/overview-stale-390.png", fullPage: true });
  failActivity = false;
  await page.getByTestId("activity-retry").click();
  await stale.waitFor({ state: "hidden", timeout: 6000 });
  job.status = "queued";
  job.stage = "readback";
  job.result.outcome = "awaiting_confirmation";
  job.stages = [{ id: "readback", label: "Confirm voice transcript", status: "waiting" }];
  await page.getByTestId("activity-current").filter({ hasText: "Waiting for confirmation" }).waitFor({ timeout: 6000 });
  assert.equal(await activity.locator('[data-stage-state="processing"]').count(), 0);
  assert.ok(await activity.locator('a[href="/crew"]').count());
  job.status = "completed";
  job.stage = null;
  job.result.outcome = "processed";
  job.result.diff_ids = ["a201-b-c"];
  job.stages = ["transcribe", "readback", "extract", "record", "drawings", "rules", "answer", "delivery"].map(id => ({ id, label: id === "drawings" ? "Compare drawings" : id, status: id === "transcribe" ? "skipped" : "completed" }));
  await page.getByTestId("activity-current").filter({ hasText: "Processed" }).waitFor({ timeout: 6000 });
  assert.ok(await activity.locator('a[href="/compare/a201-b-c"]').count());
  const completedDetails = page.getByTestId("activity-processing-details");
  await completedDetails.waitFor({ timeout: 6000 });
  assert.equal(await completedDetails.getAttribute("open"), null, "completed stage trace starts folded");
  assert.equal(await completedDetails.locator("li:visible").count(), 0);
  await completedDetails.locator("summary").click();
  assert.equal(await completedDetails.locator("li:visible").count(), 8, "all real stages can be reopened");
  await completedDetails.locator("summary").click();
  for (const width of [1280, 1920, 390]) {
    await page.setViewportSize({ width, height: width === 390 ? 844 : 800 });
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false, `page overflows at ${width}`);
    await page.screenshot({ path: `evidence/overview-activity-${width}.png`, fullPage: true });
  }
  await page.goto(base + "/#record-record-128");
  await page.locator("#record-record-128").waitFor({ state: "visible" });
  assert.equal(await page.locator("#record-record-128").evaluate(element => element === document.activeElement), true);
  assert.deepEqual(pageErrors, [], "overview raised browser errors");
  console.log("overview activity: actual stages; good-then-failed refresh retains result with stale timestamp and stops animation; retry recovers; result links; no horizontal overflow at 1280/1920/390");
} finally {
  await browser.close();
}
