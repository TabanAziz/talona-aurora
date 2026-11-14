#!/usr/bin/env node
// Browser checks for the demo path: node frontend/e2e/ui.mjs <check>
// BASE_URL is the running app, EVIDENCE_DIR receives <check>.png. The caller prepares the state
// (reset, events, decisions) before each check; a check only looks and clicks.
import fs from "node:fs";
import path from "node:path";
import { chromium } from "playwright";

const BASE = (process.env.BASE_URL || `http://127.0.0.1:${process.env.PORT_BASE || 8000}`).replace(/\/$/, "");
const EVIDENCE = process.env.EVIDENCE_DIR || "evidence";
const TIMEOUT = 10000;
const READ_ONLY_DECISIONS = process.env.E2E_DECISIONS_READ_ONLY === "true";
const NOTICE_DELIVERY = process.env.E2E_NOTICE_DELIVERY || "simulated";
const REAL_STATE = process.env.E2E_REAL_STATE === "true";

class CheckError extends Error {}

function fail(reason) {
  throw new CheckError(reason);
}

async function open(page, route) {
  try {
    await page.goto(BASE + route, { waitUntil: "load", timeout: TIMEOUT });
  } catch (error) {
    if (!String(error.message).includes("net::ERR_CONNECTION_RESET")) throw error;
    console.log(`ui: retrying GET ${route} once after net::ERR_CONNECTION_RESET`);
    await page.goto(BASE + route, { waitUntil: "load", timeout: TIMEOUT });
  }
}

/** Waits until at least one element with the test id contains the text. */
async function expectText(page, testId, text) {
  try {
    await page.getByTestId(testId).filter({ hasText: text }).first().waitFor({ state: "visible", timeout: TIMEOUT });
  } catch {
    fail(`${new URL(page.url()).pathname}: no ${testId} contains "${text}"`);
  }
}

/** The handover the app holds, formatted the way the plan page writes it (UTC, month and day). */
async function planHandover() {
  const plan = await (await fetch(`${BASE}/api/plan`)).json();
  if (!plan.handover) fail("/api/plan: no handover to compare the page with");
  return plan.handover;
}

function dayOf(value) {
  return new Date(value).toLocaleDateString("en-US", { month: "short", day: "numeric", timeZone: "UTC" });
}

/** A4 at 96 dpi minus the 12 mm margins the print stylesheet sets, in CSS pixels. */
const A4_PRINTABLE_PX = Math.round((297 - 24) * (96 / 25.4));

/** The proof prints onto one A4 page with the top bar and the buttons gone. */
async function printFitsOnePage(page, label) {
  // The print rules hang off .app:has(.notice), so the proof must be on screen before the media switches.
  await page.getByTestId("notice-view").first().waitFor({ state: "visible", timeout: TIMEOUT })
    .catch(() => fail(`${label}: the proof of notice did not render`));
  await page.emulateMedia({ media: "print" });
  const chrome = await page.evaluate(() => {
    const shown = (selector) => {
      const element = document.querySelector(selector);
      if (!element) return false;
      const box = element.getBoundingClientRect();
      return getComputedStyle(element).display !== "none" && box.height > 0 && box.width > 0;
    };
    const notice = document.querySelector(".notice");
    return {
      bar: shown(".topbar"),
      actions: shown(".notice-actions"),
      height: notice ? Math.ceil(document.documentElement.scrollHeight) : null,
      crews: document.querySelectorAll('[data-testid="notice-crew"]').length,
    };
  });
  await page.emulateMedia({ media: null });
  if (chrome.bar) fail(`${label}: the top bar is still printed`);
  if (chrome.actions) fail(`${label}: the buttons are still printed`);
  if (chrome.height === null) fail(`${label}: no proof of notice to print`);
  if (chrome.height > A4_PRINTABLE_PX) {
    fail(`${label}: the print is ${chrome.height}px tall, one A4 page holds ${A4_PRINTABLE_PX}px`);
  }
  return chrome.crews;
}

async function expectVisible(page, testId) {
  try {
    await page.getByTestId(testId).first().waitFor({ state: "visible", timeout: TIMEOUT });
  } catch {
    fail(`${new URL(page.url()).pathname}: ${testId} is not visible`);
  }
}

/** The element lies completely inside the screen the page opens on, before anything is scrolled. */
async function expectInFirstScreen(page, locator, what) {
  const box = await locator.boundingBox();
  const height = page.viewportSize()?.height ?? 0;
  const scrolled = await page.evaluate(() => window.scrollY);
  if (!box || scrolled !== 0 || box.y < 0 || box.y + box.height > height) {
    fail(`${new URL(page.url()).pathname}: ${what} is not fully inside the first screen (top ${box?.y}, bottom ${box ? box.y + box.height : "none"}, screen height ${height}, scrolled ${scrolled})`);
  }
}

/** Polls the count, because lists fill in after the first render. */
async function expectCount(page, testId, test, wanted) {
  const deadline = Date.now() + TIMEOUT;
  let count = 0;
  while (Date.now() < deadline) {
    count = await page.getByTestId(testId).count();
    if (test(count)) return;
    await page.waitForTimeout(100);
  }
  fail(`${new URL(page.url()).pathname}: expected ${wanted} ${testId}, found ${count}`);
}

function flagCard(page, flagId) {
  return page.getByTestId("flag-card").and(page.locator(`[data-flag-id="${flagId}"]`));
}

const checks = {
  async load(page) {
    await open(page, "/");
    await expectVisible(page, "demo-badge");
    await expectText(page, "project-name", "Maple Court");
    await expectCount(page, "record-item", (n) => n >= 3, "at least 3");
  },

  async revision(page) {
    await open(page, "/");
    await expectText(page, "record-item", "A-201 Rev C");
    await open(page, "/compare/d-a201-b-c");
    await expectVisible(page, "compare-image");
    await page.getByTestId("compare-overlay").click();
    await expectCount(page, "compare-region", (n) => n >= 1, "at least 1");
    await expectText(page, "compare-outdated-sheet", "E-201");
    await page.getByTestId("compare-3d-switch").click();
    await expectVisible(page, "compare-3d");
    await expectCount(page, "compare-3d-label", (n) => n === 1, "exactly 1");
    // The change links straight to the status page of the revision it shows.
    await expectText(page, "compare-status", "Status");
    await page.getByTestId("compare-status").first().click({ timeout: TIMEOUT });
    await expectVisible(page, "sheet-status");
  },

  async notify(page) {
    if (!["sent", "simulated"].includes(NOTICE_DELIVERY)) fail("invalid E2E_NOTICE_DELIVERY");
    await open(page, "/");
    await expectText(page, "waiting-list", "Framing crew");
    await open(page, "/crew");
    await expectText(page, "crew-message", "Please confirm you have Rev C");
    await open(page, "/notice/d-a201-b-c");
    await expectText(page, "notice-crew", "Framing crew");
    await expectText(page, "notice-step", NOTICE_DELIVERY === "sent" ? "Notice sent" : "Notice simulated, not sent");
    await expectText(page, "notice-crew", "Not confirmed");
    await expectText(page, "notice-crew", "Electrical crew");
    await expectText(page, "notice-crew", "E-201 Rev B no longer matches A-201 Rev C");
    // The outcome of the crews that have not answered belongs in the first screen, not under the fold.
    const outcome = page.getByTestId("notice-outcome").first();
    await outcome.waitFor({ state: "visible", timeout: TIMEOUT }).catch(() => fail("/notice: no notice-outcome for the unconfirmed crews"));
    const box = await outcome.boundingBox();
    if (!box || box.y + box.height > 800) fail(`/notice: the outcome sits at ${box ? Math.round(box.y + box.height) : "?"} px, below the 800 px screen`);
    await expectText(page, "notice-outcome", "not confirmed");
    // The crews shown are exactly the open confirmations of this change, the same number the sheet page
    // prints. Machine rows carry notice-crew too (data-machine), and the sheet counts them apart, so the
    // crew comparison counts only the rows without that mark.
    const openAsks = (await (await fetch(`${BASE}/api/waiting`)).json())
      .filter((item) => item.status === "open" && /A-201/.test(String(item.what)) && /Rev C/.test(String(item.what)));
    const noticeRows = await page.getByTestId("notice-crew").count();
    if (noticeRows !== openAsks.length) fail(`/notice: ${noticeRows} rows shown, ${openAsks.length} open confirmations for A-201 Rev C`);
    const noticeCrews = await page.locator('[data-testid="notice-crew"]:not([data-machine="true"])').count();
    await open(page, "/sheet/A-201/C");
    const sheetCrews = Number((await page.getByTestId("sheet-crews").innerText()).match(/\d+/)?.[0] ?? "-1");
    if (sheetCrews !== noticeCrews) fail(`/sheet/A-201/C says ${sheetCrews} crews not confirmed, the proof of notice shows ${noticeCrews} crew rows`);
    await open(page, "/notice/d-a201-b-c");
    // The proof prints on one A4 page, and a fourth affected crew still fits on it.
    const crews = await printFitsOnePage(page, "/notice: three crews");
    if (crews < 3) fail(`/notice: ${crews} crews printed, expected at least 3`);
    if (REAL_STATE) {
      console.log("notice: actual API state and print checked; fourth-crew fixture belongs to canonical e2e");
      return;
    }
    const waiting = await (await fetch(`${BASE}/api/waiting`)).json();
    const outbox = await (await fetch(`${BASE}/api/outbox`)).json();
    const ask = waiting.find((item) => String(item.what || "").startsWith("Confirm "));
    const told = ask && outbox.find((message) => message.to === ask.on);
    if (!ask || !told) fail("/notice: no open confirmation to add a fourth crew to");
    await page.route("**/api/waiting", (route) => route.fulfill({ json: [...waiting, { ...ask, id: "w-fourth", on: "Concrete crew" }] }));
    await page.route("**/api/outbox", (route) => route.fulfill({ json: [...outbox, { ...told, id: "o-fourth", to: "Concrete crew" }] }));
    await open(page, "/notice/d-a201-b-c");
    await expectText(page, "notice-crew", "Concrete crew");
    const four = await printFitsOnePage(page, "/notice: four crews");
    if (four < 4) fail(`/notice: ${four} crews printed with a fourth crew added, expected 4`);
  },

  async flag(page) {
    await open(page, "/crew");
    await expectText(page, "crew-message", "I heard your voice note as");
    await open(page, "/");
    const card = flagCard(page, "f-stale-3b");
    await card.waitFor({ state: "visible", timeout: TIMEOUT }).catch(() => fail("/: no flag-card f-stale-3b"));
    await card.click();
    await expectVisible(page, "flag-detail");
    await expectCount(page, "evidence-item", (n) => n === 2, "exactly 2");
    await expectVisible(page, "flag-diff-link");
    await expectText(page, "flag-status", "open");
    // One click from the flag to the proof of what that crew was told, without knowing the change id.
    await page.getByTestId("flag-notice-link").click({ timeout: TIMEOUT });
    await page.waitForURL("**/notice/d-a201-b-c", { timeout: TIMEOUT })
      .catch(() => fail("/flags/f-stale-3b: the notice link did not open the proof of that change"));
    await expectVisible(page, "notice-view");
    await expectText(page, "notice-crew", "Framing crew");
  },

  async decide(page) {
    await open(page, "/flags/f-stale-3b");
    if (!READ_ONLY_DECISIONS) await page.getByTestId("flag-accept").click({ timeout: TIMEOUT });
    await expectText(page, "flag-status", "held");
    await open(page, "/crew");
    await expectText(page, "crew-message", "Hold on 3B");
  },

  async deviation(page) {
    await open(page, "/flags/f-crane");
    await expectVisible(page, "flag-numbers");
    await expectText(page, "flag-proposal", "Calculated");
    await open(page, "/plan");
    await expectText(page, "plan-resource-row", "Mobile crane");
    const trucks = page.getByTestId("plan-resource-row").filter({ hasText: "Concrete trucks" }).first();
    const reported = trucks.getByTestId("plan-actual-reported");
    await reported.waitFor({ state: "visible", timeout: TIMEOUT }).catch(() => fail("/plan: the concrete truck line shows no reported value"));
    const [planned, actual, difference] = await Promise.all(
      [2, 3, 4].map(async (column) => (await trucks.locator("td").nth(column).innerText()).replace(/\s+/g, " ").trim()),
    );
    if (!/^3\b/.test(planned) || !/^4\b.*reported/.test(actual) || !/^\+1\b/.test(difference)) {
      fail(`/plan: the concrete truck line reads planned "${planned}", actual "${actual}", difference "${difference}", expected 3, 4 reported, +1`);
    }
    if ((await reported.getByRole("link").getAttribute("href")) !== "/flags/f-trucks") fail("/plan: the reported truck count does not link to f-trucks");
    await expectText(page, "plan-chain", "Roof truss lift");
    const flag = await (await page.request.get(BASE + "/api/flags/f-crane")).json();
    const proposal = await (await page.request.get(BASE + `/api/proposals/${encodeURIComponent(flag.proposal_id)}`)).json();
    const card = page.getByTestId("plan-proposal").and(page.locator(`[data-proposal-id="${proposal.id}"]`));
    if (new Date(proposal.handover_new).valueOf() !== new Date(proposal.handover_old).valueOf()) {
      await card.getByTestId("plan-handover-new").waitFor({ state: "visible", timeout: TIMEOUT });
    } else {
      const day = new Date(proposal.handover_old).toLocaleDateString("en-US", { weekday: "short", month: "short", day: "numeric", timeZone: "UTC" });
      await card.getByText(`Handover stays ${day}.`, { exact: true }).waitFor({ state: "visible", timeout: TIMEOUT });
    }
  },

  async reschedule(page) {
    const flagResponse = await page.request.get(BASE + "/api/flags/f-crane");
    if (!flagResponse.ok()) fail("crane flag is unavailable");
    const flag = await flagResponse.json();
    const proposalResponse = await page.request.get(BASE + `/api/proposals/${encodeURIComponent(flag.proposal_id)}`);
    if (!proposalResponse.ok()) fail("crane proposal is unavailable");
    const proposal = await proposalResponse.json();
    const expected = process.env.E2E_EXPECTED_HANDOVER || proposal.handover_new;
    if (!expected) fail("proposal has no handover to verify");
    await open(page, "/flags/f-crane");
    if (!READ_ONLY_DECISIONS) await page.getByTestId("flag-accept").click({ timeout: TIMEOUT });
    await expectText(page, "flag-status", "resolved");
    const planResponse = await page.request.get(BASE + "/api/plan");
    if (!planResponse.ok() || new Date((await planResponse.json()).handover).valueOf() !== new Date(expected).valueOf()) {
      fail("the plan does not match the accepted handover");
    }
    await open(page, "/plan");
    await expectText(page, "plan-handover", dayOf(expected));
    const crane = page.getByTestId("plan-resource-row").filter({ hasText: "Mobile crane" }).first();
    await crane.waitFor({ state: "visible", timeout: TIMEOUT }).catch(() => fail("/plan: no Mobile crane line"));
    if ((await crane.getByTestId("plan-actual-reported").count()) > 0) fail("/plan: the crane line is still marked reported after the accepted plan");
    await page.screenshot({ path: path.join(EVIDENCE, "reschedule-plan.png"), fullPage: true });
    await open(page, "/crew");
    await expectText(page, "crew-message", proposal.shifts[0].name);
  },

  async question(page) {
    await open(page, "/crew");
    await expectText(page, "crew-message", "I heard your voice note as");
    await expectText(page, "crew-message", "Not yet. The rough plumbing inspection for 2A");
    // The payoff of this step is Aurora's answer, so it has to be on the first screen without scrolling.
    await expectInFirstScreen(page, page.getByTestId("crew-message").filter({ hasText: "Not yet. The rough plumbing inspection for 2A" }).first(), "the answer Not yet");
    // The Drywall crew has the open out-of-sequence flag, so its chat is the first one.
    const firstChat = page.getByTestId("crew-thread").first();
    if ((await firstChat.getAttribute("data-open-flag")) !== "true") fail("/crew: the first chat is not a crew with an open flag");
    if ((await firstChat.getByTestId("crew-message").filter({ hasText: "Not yet. The rough plumbing inspection for 2A" }).count()) === 0) {
      fail("/crew: the first chat does not hold the answer Not yet");
    }
    await open(page, "/");
    await flagCard(page, "f-seq-2a")
      .waitFor({ state: "visible", timeout: TIMEOUT })
      .catch(() => fail("/: no flag-card f-seq-2a"));
  },

  async learn(page) {
    await open(page, "/flags/f-seq-2a");
    if (!READ_ONLY_DECISIONS) {
      await page.getByTestId("flag-standing-rule").check({ timeout: TIMEOUT });
      await page.getByTestId("flag-accept").click({ timeout: TIMEOUT });
    }
    await expectText(page, "flag-status", "held");
  },

  async learned(page) {
    await open(page, "/crew");
    const response = await page.request.get(BASE + "/api/answers");
    if (!response.ok()) fail("could not read the crew answer");
    const answer = (await response.json()).find((item) => item.event_id === (process.env.E2E_LEARN_EVENT_ID || "e07"));
    if (!answer || answer.basis !== "standing_rule" || answer.escalated || !answer.text.trim()) {
      fail("the follow-up question has no answer from the standing rule");
    }
    if (!answer.text.toLowerCase().includes("superintendent decided")) {
      fail("the follow-up answer does not explain the earlier decision");
    }
    await expectText(page, "crew-message", answer.text);
  },

  async control(page) {
    await open(page, "/crew");
    await expectText(page, "crew-message", "Yes. The rough plumbing inspection for 1C passed");
    await open(page, "/");
    await expectVisible(page, "flags-list");
    const count = await page.getByTestId("flag-card").filter({ hasText: "1C" }).count();
    if (count > 0) fail(`/: ${count} flag-card mention 1C, expected none`);
  },

  // The change order attachment: the built work, the hours before the revision, and both sources.
  async rework(page) {
    const work = {
      id: "e-work", channel: "telegram", sent_at: "2026-11-10T00:30:00Z", received_at: "2026-11-10T00:30:00Z",
      sender: "Marco Ruiz", sender_role: "Framing foreman",
      text: "We built the partitions in 3B today, per the Rev B sheets.",
    };
    const revision = {
      id: "e-rev", channel: "email", sent_at: "2026-11-10T09:00:00Z", received_at: "2026-11-10T09:00:00Z",
      sender: "Dana Whitfield", sender_role: "Architect",
      text: "Attached A-201 Rev C. The partition between bedroom and living room in 3B shifts 300 mm north. Rev C replaces Rev B.",
    };
    const diff = {
      id: "d-a201-b-c", sheet: "A-201", title: "Level 3 floor plan", from_rev: "B", to_rev: "C",
      before_url: "/media/mock/a201-rev-b.svg", after_url: "/media/mock/a201-rev-c.svg",
      overlay_url: "/media/mock/a201-overlay.svg",
      regions: [{ x: 0.5, y: 0.29, w: 0.2, h: 0.12, kind: "moved", label: "Partition 3B, 300 mm north" }],
      summary: "One wall moved in unit 3B.",
    };
    const entry = {
      id: "r-rework-rw-1", at: revision.received_at, kind: "change", title: "Built before the change", actor: "Aurora",
      refs: { rework: "rw-1", diff: diff.id, unit: "3B", task: "T-031" },
      source_event_ids: [work.id, revision.id],
    };
    const plan = {
      handover: "2026-12-18T16:00:00Z",
      tasks: [
        { id: "T-031", name: "Frame partitions 3B", crew: "Framing crew", unit: "3B", start: "2026-11-13T06:00:00Z", end: "2026-11-13T15:00:00Z", status: "planned" },
        { id: "T-032", name: "Rough electrical 3B", crew: "Electrical crew", unit: "3B", depends_on: ["T-031"], start: "2026-11-16T06:00:00Z", end: "2026-11-16T14:00:00Z", status: "planned" },
      ],
      resources: [],
    };
    await page.route("**/api/record", (route) => route.fulfill({ json: [entry] }));
    await page.route("**/api/diffs/d-a201-b-c", (route) => route.fulfill({ json: diff }));
    await page.route("**/api/events", (route) => route.fulfill({ json: [work, revision] }));
    await page.route("**/api/outbox", (route) => route.fulfill({ json: [] }));
    await page.route("**/api/waiting", (route) => route.fulfill({ json: [] }));
    await page.route("**/api/plan", (route) => route.fulfill({ json: plan }));
    await open(page, "/rework/d-a201-b-c/3B");
    await expectVisible(page, "rework-view");
    await expectText(page, "rework-overlay", "Unit 3B");
    await expectText(page, "rework-gap", "8.5 hours");
    await expectCount(page, "rework-source", (n) => n >= 2, "at least 2");
    await expectText(page, "rework-cost", "Rework hours: 17 hours");
    await page.getByTestId("rework-rate").fill("50");
    await expectText(page, "rework-amount", "850");
  },

  // The site view: every unit of the project in 3D with its state, and the open points of the one clicked.
  async site(page) {
    await open(page, "/site");
    await expectVisible(page, "site-view");
    await expectVisible(page, "site-legend");
    const units = await page.getByTestId("site-unit").count();
    if (units < 1) fail("/site: no unit is shown");
    const states = await page.getByTestId("site-unit").evaluateAll((nodes) => nodes.map((node) => node.dataset.state));
    if (!states.every((state) => ["hold", "inspection", "confirmation", "working", "clear", "unknown"].includes(state))) {
      fail(`/site: a unit carries an unknown state ${states.join(", ")}`);
    }
    await page.getByTestId("site-unit").first().click();
    await expectVisible(page, "site-selected");
    await expectText(page, "site-selected", "Open points");
  },

  // What Aurora may do alone: the earned suggestion, one grant, its applications and the revoke.
  async autonomy(page) {
    const grant = {
      id: "auth-000000000001", action: "hold_work", flag_type: "stale_drawing", scope: { unit: "3B" },
      statement: "Hold work in 3B that rests on a superseded drawing.",
      rule_id: "rule-d-3", evidence_decision_ids: ["d-1", "d-2", "d-3"], evidence_flag_ids: ["f-stale-3b", "f-stale-3b", "f-stale-3b"],
      granted_by: "Superintendent", granted_at: "2026-11-12T16:00:00Z", status: "active",
      revoked_by: null, revoked_at: null, superseded_by: null, applications: [],
    };
    const suggestion = {
      id: "sug-000000000001", action: "hold_work", flag_type: "stale_drawing", scope: { unit: "3B" },
      statement: "Hold work in 3B that rests on a superseded drawing.",
      evidence_decision_ids: ["d-1", "d-2", "d-3"], evidence_flag_ids: ["f-stale-3b", "f-stale-3b", "f-stale-3b"],
      last_decided_at: "2026-11-12T15:00:00Z",
    };
    let granted = false;
    let revoked = false;
    let attempts = 0;
    const posts = [];
    const body = () => ({
      generated_at: "2026-11-13T08:40:00Z",
      suggestions: granted ? [] : [suggestion],
      authorizations: granted || revoked
        ? [{
            ...grant,
            status: revoked ? "revoked" : "active",
            revoked_by: revoked ? "Superintendent" : null,
            revoked_at: revoked ? "2026-11-13T09:00:00Z" : null,
            applications: [{ decision_id: "d-9", flag_id: "f-stale-3b", record_entry_id: "r-dec-d-9", at: "2026-11-13T08:40:00Z" }],
          }]
        : [],
      automatic_holds_today: granted ? 1 : 0,
      daily_limit: 5,
    });
    await page.route("**/api/autonomy", (route) => route.fulfill({ json: body() }));
    await page.route("**/api/autonomy/grant", (route) => {
      posts.push({ path: "grant", body: route.request().postDataJSON() });
      attempts += 1;
      if (attempts === 1) return route.fulfill({ status: 409, json: { detail: "That suggestion is not supported by the record any more. Nothing was granted." } });
      granted = true;
      return route.fulfill({ json: grant });
    });
    await page.route("**/api/autonomy/*/revoke", (route) => {
      posts.push({ path: "revoke", body: route.request().postDataJSON() });
      revoked = true;
      return route.fulfill({ json: { ...grant, status: "revoked" } });
    });
    await open(page, "/autonomy");
    await expectVisible(page, "autonomy-view");
    await expectText(page, "autonomy-suggestion", "Hold work in 3B");
    await expectCount(page, "autonomy-decision", (n) => n === 3, "3 decisions");
    if (posts.length !== 0) fail("/autonomy: a request was sent before a click");
    // The grant asks once, and a failed request changes nothing until Retry.
    await page.getByTestId("autonomy-grant").click();
    await expectCount(page, "autonomy-confirm", (n) => n === 1, "1 confirmation");
    await page.getByTestId("autonomy-confirm").click();
    await expectVisible(page, "autonomy-error");
    await expectVisible(page, "autonomy-suggestion");
    await expectCount(page, "autonomy-rule", (n) => n === 0, "no authorization");
    await page.getByTestId("autonomy-retry").click();
    await expectVisible(page, "autonomy-rule");
    await expectText(page, "autonomy-applied", "r-dec-d-9");
    if (posts.length !== 2 || posts[0].path !== "grant" || posts[1].body.granted_by.length === 0) {
      fail("/autonomy: the grant requests are wrong");
    }
    // Revoking asks once too, and the authorization is greyed with its end time.
    await page.getByTestId("autonomy-revoke").click();
    await expectCount(page, "autonomy-confirm", (n) => n === 1, "1 confirmation");
    await page.getByTestId("autonomy-confirm").click();
    await expectText(page, "autonomy-rule", "Revoked");
    const status = await page.getByTestId("autonomy-rule").first().getAttribute("data-status");
    if (status !== "revoked") fail(`/autonomy: the authorization is ${status} after the revoke`);
    if (posts.length !== 3 || posts[2].path !== "revoke" || posts[2].body.revoked_by.length === 0) {
      fail("/autonomy: the revoke request is wrong");
    }
  },

  // A printed label scans to this page; it must say whether its revision may still be built from.
  async sheet(page) {
    let dataLoads = 0;
    page.on("request", (request) => {
      if (request.url().includes("/api/diffs")) dataLoads += 1;
    });
    await open(page, "/sheet/A-201/B");
    await expectText(page, "sheet-status", "Superseded");
    await expectText(page, "sheet-current-rev", "Rev C");
    // The band has to name both: which revision is the newest of which sheet.
    await expectText(page, "sheet-view", "Rev C is the newest revision of A-201");
    await expectVisible(page, "sheet-overlay");
    await expectVisible(page, "sheet-compare-link");
    // The two actions come before the change overlay, so a laptop opened on site shows them without scrolling.
    await expectInFirstScreen(page, page.getByTestId("sheet-label-link"), "the label link");
    await expectInFirstScreen(page, page.getByTestId("sheet-actions-compare"), "the comparison link");
    const before = dataLoads;
    await page.waitForTimeout(6000);
    if (dataLoads <= before) fail("/sheet/A-201/B: the page did not reload its data within 6 s");

    await open(page, "/sheet/A-201/C");
    await expectText(page, "sheet-status", "Current");
    await expectText(page, "sheet-current-rev", "Rev C");
    await expectInFirstScreen(page, page.getByTestId("sheet-label-link"), "the label link");
    await expectInFirstScreen(page, page.getByTestId("sheet-actions-compare"), "the comparison link");
    await open(page, "/sheet/A-201/A");
    await expectText(page, "sheet-status", "No newer revision on record");
    await expectInFirstScreen(page, page.getByTestId("sheet-label-link"), "the label link");
    await expectCount(page, "sheet-actions-compare", (n) => n === 0, "0 comparison links");
    await open(page, "/sheet/X-999/A");
    await expectText(page, "sheet-status", "Unknown sheet");
    await expectInFirstScreen(page, page.getByTestId("sheet-label-link"), "the label link");

    await open(page, "/sheet/A-201/B/label");
    const qr = page.getByTestId("sheet-qr");
    await qr.waitFor({ state: "visible", timeout: TIMEOUT }).catch(() => fail("/sheet/A-201/B/label: sheet-qr is not visible"));
    const value = await qr.getAttribute("data-qr-value");
    // The page points the label at VITE_PUBLIC_URL when the build has one, and at its own origin otherwise.
    const labelBase = (process.env.VITE_PUBLIC_URL || BASE).replace(/\/+$/, "");
    if (value !== `${labelBase}/sheet/A-201/B`) {
      fail(`/sheet/A-201/B/label: data-qr-value is ${value}, expected ${labelBase}/sheet/A-201/B`);
    }
    // A scanner needs four light modules around the code and the drawing has to include them.
    const quiet = Number(await qr.getAttribute("data-quiet-zone"));
    const modules = Number(await qr.getAttribute("data-qr-modules"));
    const size = Number(await qr.getAttribute("data-qr-size"));
    if (quiet !== 4) fail(`/sheet/A-201/B/label: the quiet zone is ${quiet} modules, expected 4`);
    if (!(modules > 0) || size !== modules + quiet * 2) {
      fail(`/sheet/A-201/B/label: the drawing is ${size} wide for ${modules} modules, expected ${modules + quiet * 2}`);
    }
    await expectText(page, "sheet-label", "Rev B");
    await expectText(page, "sheet-label", "Scan before you build");
    // The printed label is one click away from the status page it stands for.
    await page.getByTestId("sheet-open-status").click({ timeout: TIMEOUT });
    await expectVisible(page, "sheet-status");
    await expectText(page, "sheet-status", "Superseded");
    await open(page, "/sheet/A-201/B?state=empty");
    await expectVisible(page, "state-empty");
  },

  daily: async (page) => {
    const record = await (await fetch(`${BASE}/api/record`)).json();
    if (!record.length) fail("/daily: the record is empty, so no day can be opened");
    const flags = await (await fetch(`${BASE}/api/flags`)).json();
    // The day of the newest flag, from the API: the demo week moves with DEMO_ANCHOR, so no literal date.
    const day = flags
      .map((flag) => String(flag.raised_at ?? "").slice(0, 10))
      .filter((value) => /^\d{4}-\d{2}-\d{2}$/.test(value))
      .sort()
      .pop();
    if (!day) fail("/daily: the API has no flag, so no day with flags can be opened");
    const dayFlags = flags.filter((flag) => String(flag.raised_at).slice(0, 10) === day);
    await open(page, `/daily/${day}`);
    await expectVisible(page, "nav-daily");
    await expectVisible(page, "daily-view");
    const lines = page.getByTestId("daily-line");
    const total = await lines.count();
    if (total === 0) fail(`/daily/${day}: the report has no line`);
    const flagSection = page.getByTestId("daily-section").filter({ hasText: "Flags and the decision taken" });
    const flagLines = await flagSection.getByTestId("daily-line").count();
    if (flagLines !== dayFlags.length) {
      fail(`/daily/${day}: ${flagLines} flag lines, the API has ${dayFlags.length} flags raised that day`);
    }
    const flagTexts = await flagSection.getByTestId("daily-line").allInnerTexts();
    for (const flag of dayFlags) {
      if (!flagTexts.some((text) => text.startsWith(flag.title))) {
        fail(`/daily/${day}: no flag line for "${flag.title}" (${flag.id}), lines: ${flagTexts.join(" | ")}`);
      }
    }
    for (let index = 0; index < total; index += 1) {
      const links = await lines.nth(index).getByTestId("daily-source").count();
      if (links !== 1) fail(`/daily/${day}: line ${index + 1} has ${links} source links, expected one`);
    }
  },

  // The evaluation page shows only committed reports, so it is the same on every machine.
  // Every number on the page comes from the committed bundle, so the check compares each row with it.
  async evaluation(page) {
    await open(page, "/evaluation");
    await expectVisible(page, "nav-evaluation");
    await expectVisible(page, "evaluation-view");
    const bundle = JSON.parse(fs.readFileSync(new URL("../src/pages/evaluation/reports/data.json", import.meta.url), "utf8"));
    const pipeline = bundle.pipeline;
    const stress = bundle.stress;
    if (!pipeline || !pipeline.summary || !pipeline.meta?.when) {
      await expectText(page, "evaluation-detection", "Not run yet");
    } else {
      const s = pipeline.summary;
      await expectText(page, "evaluation-run", pipeline.meta.when);
      await expectText(page, "evaluation-run", pipeline.meta.mode);
      if (pipeline.meta.commit) await expectText(page, "evaluation-run", pipeline.meta.commit.slice(0, 12));
      const areas = await page.getByTestId("evaluation-areas").innerText();
      for (const area of pipeline.meta.real_areas ?? []) {
        if (!areas.includes(area)) fail(`/evaluation: the real area ${area} is not named in the areas line`);
      }
      for (const area of pipeline.meta.mock_areas ?? []) {
        if (!areas.includes(area)) fail(`/evaluation: the mocked area ${area} is not named in the areas line`);
      }
      const expected = [
        ["Cases passed", `${s.cases_passed} of ${s.cases}`],
        ["Flags found", `${s.flags_found} of ${s.expected_flags}`],
        ["Missed problems", String(s.missed_problems)],
        ["False alarms", `${s.false_alarms} in ${s.no_problem_cases_with_a_flag} of ${s.cases_without_problem}`],
        ["Raised by the completing event", s.timing_on_expected_event],
        ["Not before its evidence", s.timing_not_before_information],
        ["Before the work starts", s.timing_before_work_start],
        ["Evidence cites arrived events", s.evidence_cites_arrived_events],
      ];
      const shown = await page.getByTestId("evaluation-measure").evaluateAll((nodes) =>
        nodes.map((node) => [node.dataset.measure, node.querySelector(".evaluation-value")?.textContent?.trim() ?? ""]),
      );
      if (JSON.stringify(shown) !== JSON.stringify(expected)) {
        fail(`/evaluation: the measures differ from the bundle, shown ${JSON.stringify(shown)}`);
      }
    }
    if (!stress || !Array.isArray(stress.kinds)) {
      await expectText(page, "evaluation-stress", "Not run yet");
    } else {
      const rows = await page.getByTestId("evaluation-kind").count();
      if (rows !== stress.kinds.length) fail(`/evaluation: ${rows} stress variants, the bundle has ${stress.kinds.length}`);
      for (const kind of stress.kinds) {
        const summary = kind.summary ?? {};
        const skipped = (kind.skipped_cases ?? []).length;
        const expected = [
          `${summary.cases} of ${summary.cases + skipped}`,
          `${summary.flags_found} of ${summary.expected_flags}`,
          String(summary.missed_problems),
          String(summary.false_alarms),
          String(skipped),
        ];
        const cells = await page.locator(`[data-testid="evaluation-kind"][data-kind="${kind.kind}"] td`).allTextContents();
        if (JSON.stringify(cells.slice(1).map((text) => text.trim())) !== JSON.stringify(expected)) {
          fail(`/evaluation: the stress row ${kind.kind} differs from the bundle`);
        }
      }
    }
    const voice = bundle.voice;
    if (!voice || !Array.isArray(voice.levels)) {
      await expectText(page, "evaluation-voice", "Not run yet");
    } else {
      await expectCount(page, "evaluation-level", (n) => n === voice.levels.length, "all measured noise levels");
      for (const level of voice.levels) {
        const cells = await page.locator(`[data-testid="evaluation-level"][data-snr="${level.added_snr_db}"] td`).allTextContents();
        const expected = [level.added_snr_db + " dB", level.n, level.keys_retained, level.same_facts,
          level.safe_failures, level.wrong_critical_facts].map(String);
        if (JSON.stringify(cells.map((text) => text.trim())) !== JSON.stringify(expected)) {
          fail(`/evaluation: displayed voice results differ at ${level.added_snr_db} dB`);
        }
      }
      if (voice.scope) await expectText(page, "evaluation-voice-scope", voice.scope);
    }
    await expectText(page, "evaluation-limitations", "Sample size is 22 synthetic cases");
    await expectText(page, "evaluation-limitations", "p10-too-few-trucks");
    await expectCount(page, "evaluation-case", (n) => n === 22, "22 cases");
    await open(page, "/evaluation?state=empty");
    await expectVisible(page, "state-empty");
  },
};

const name = process.argv[2];
if (!name || !checks[name]) {
  console.error(`usage: node frontend/e2e/ui.mjs <${Object.keys(checks).join("|")}>`);
  process.exit(2);
}

fs.mkdirSync(EVIDENCE, { recursive: true });
const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1280, height: 800 } });
let exitCode = 0;
try {
  await checks[name](page);
  console.log(`ui ${name}: ok`);
} catch (error) {
  exitCode = 1;
  const reason = error instanceof CheckError ? error.message : String(error?.message ?? error).split("\n")[0];
  console.error(`ui ${name}: FAILED, ${reason}`);
} finally {
  await page.screenshot({ path: path.join(EVIDENCE, `${name}.png`), fullPage: true }).catch(() => {});
  await browser.close();
}
process.exit(exitCode);
