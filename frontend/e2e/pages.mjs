#!/usr/bin/env node
// Every page brings its own checks: node frontend/e2e/pages.mjs
//
// A page folder may hold
//   check.mjs      its own browser check, run with BASE_URL and EVIDENCE_DIR set
//   ui-pages.json  its own layout pages, merged into the one uicheck run
// so adding a page never edits a shared file. Existing checks that a demo step runs and the entries in
// frontend/ui-pages.json stay where they are; this runner only adds what the folders announce.
// A check reads its fixtures from the repo with path.resolve(import.meta.dirname, ...): the .pathname of
// import.meta.url keeps the escape in a folder name, so every read failed with ENOENT on a checkout in a
// folder with a space. The runner refuses that idiom before it starts a browser.
import { execFileSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";

const ROOT = path.resolve(import.meta.dirname, "..", "..");
const PAGES = path.join(ROOT, "frontend", "src", "pages");
const BASE = (process.env.BASE_URL || `http://127.0.0.1:${process.env.PORT_BASE || 8000}`).replace(/\/$/, "");
const EVIDENCE = process.env.EVIDENCE_DIR || path.join(ROOT, "evidence");

function folders() {
  return fs.readdirSync(PAGES, { withFileTypes: true })
    .filter((entry) => entry.isDirectory())
    .map((entry) => entry.name)
    .sort();
}

/** A page check that reads the repo through the .pathname of a file URL opens an escaped folder name. */
function pathIssues() {
  const found = [];
  for (const name of folders()) {
    const file = path.join(PAGES, name, "check.mjs");
    if (!fs.existsSync(file)) continue;
    if (/import\.meta\.url\s*\)\s*\.pathname/.test(fs.readFileSync(file, "utf8"))) {
      found.push(`${path.relative(ROOT, file)}: read the repo with path.resolve(import.meta.dirname, ...), not with the .pathname of import.meta.url, which keeps the escape in a folder name and makes every read fail with ENOENT`);
    }
  }
  return found;
}

/** Runs every check.mjs a page announces, one after the other, and reports each on its own line. */
function pageChecks() {
  const ran = [];
  const failed = [];
  const issues = pathIssues();
  for (const issue of issues) console.log(`pages: FAILED path of ${issue}`);
  if (issues.length > 0) return { ran, failed: issues };
  for (const name of folders()) {
    const file = path.join(PAGES, name, "check.mjs");
    if (!fs.existsSync(file)) continue;
    const out = path.join(EVIDENCE, `page-${name}`);
    fs.mkdirSync(out, { recursive: true });
    try {
      execFileSync(process.execPath, [file], {
        cwd: ROOT,
        env: { ...process.env, BASE_URL: BASE, EVIDENCE_DIR: out },
        stdio: "pipe",
        timeout: 180000,
      });
      console.log(`pages: ok ${name}`);
      ran.push(name);
    } catch (error) {
      const text = `${error.stdout ?? ""}${error.stderr ?? ""}`.trim().split("\n").slice(-3).join(" ");
      console.log(`pages: FAILED ${name}: ${text || error.message}`);
      failed.push(name);
    }
  }
  return { ran, failed };
}

/**
 * Merges every ui-pages.json under the pages into one config and checks the layout once.
 * The shared frontend/ui-pages.json stays the base, so its pages and viewports are untouched.
 */
function pageLayout() {
  const base = path.join(ROOT, "frontend", "ui-pages.json");
  const config = fs.existsSync(base) ? JSON.parse(fs.readFileSync(base, "utf8")) : { viewports: [], pages: [] };
  const pages = [...(config.pages ?? [])];
  const seen = new Set(pages.map((page) => page.path));
  const owners = [];
  for (const name of folders()) {
    const file = path.join(PAGES, name, "ui-pages.json");
    if (!fs.existsSync(file)) continue;
    const own = JSON.parse(fs.readFileSync(file, "utf8"));
    let added = 0;
    for (const page of own.pages ?? []) {
      if (seen.has(page.path)) continue;
      seen.add(page.path);
      pages.push(page);
      added += 1;
    }
    owners.push(`${name} (${added})`);
  }
  if (owners.length === 0) return { ran: [], failed: [] };
  const merged = path.join(EVIDENCE, "ui-pages-merged.json");
  fs.mkdirSync(EVIDENCE, { recursive: true });
  fs.writeFileSync(merged, JSON.stringify({ ...config, pages }, null, 1));
  const viewports = (config.viewports ?? []).join(",");
  const args = [path.join(ROOT, "scripts", "uicheck.mjs"), "--config", merged, "--out", path.join(EVIDENCE, "ui-pages")];
  if (viewports) args.push("--viewports", viewports);
  try {
    execFileSync(process.execPath, args, { cwd: ROOT, env: process.env, stdio: "pipe", timeout: 600000 });
    console.log(`pages: ok layout from ${owners.join(", ")}`);
    return { ran: owners, failed: [] };
  } catch (error) {
    const text = `${error.stdout ?? ""}${error.stderr ?? ""}`.trim().split("\n").slice(-5).join(" ");
    console.log(`pages: FAILED layout from ${owners.join(", ")}: ${text || error.message}`);
    return { ran: owners, failed: ["layout"] };
  }
}

// The checks want the record the demo path built; the merged layout wants the end state, so the gate calls
// this twice, once with --checks and once with --layout.
const mode = process.argv.includes("--checks") ? "checks" : process.argv.includes("--layout") ? "layout" : "both";
const results = [];
if (mode !== "layout") results.push(pageChecks());
if (mode !== "checks") results.push(pageLayout());
const failed = results.flatMap((result) => result.failed);
const label = mode === "checks" ? "page checks" : mode === "layout" ? "layout configs" : "page checks and layout configs";
console.log(`pages: ${label}, ${results.length} entries, ${failed.length} failed`);
process.exit(failed.length === 0 ? 0 : 1);
