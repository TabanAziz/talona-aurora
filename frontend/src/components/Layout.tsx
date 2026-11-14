import { useEffect, useRef, useState } from "react";
import { Link, NavLink, Outlet, useLocation } from "react-router-dom";
import { api, request } from "../api/client";
import { getSelectedProjectId, selectProject } from "../api/workspace";
import { useQuery } from "../api/useQuery";
import "./project/project.css";

type Theme = "light" | "dark";
type ProjectItem = { id: string; name: string; unit_count?: number };
const NAVIGATION = [
  { id: "overview", to: "/", label: "Overview", icon: "overview", testId: "nav-overview", items: [
    { to: "/", label: "Project overview", detail: "Latest activity and issues to review", testId: "nav-overview-home" },
    { to: "/daily", label: "Daily report", detail: "A sourced account of the day", testId: "nav-daily" },
    { to: "/timelapse", label: "Project timeline", detail: "See the site change over time", testId: "nav-timelapse" },
    { to: "/learned", label: "Saved rules", detail: "Decisions applied to similar work", testId: "nav-learned" },
    { to: "/evaluation", label: "Quality checks", detail: "Inspect the recorded check results", testId: "nav-evaluation" },
  ] },
  { id: "messages", to: "/crew", label: "Messages", icon: "messages", testId: "nav-crew", items: [
    { to: "/crew", label: "Conversations", detail: "Site messages and crew updates", testId: "nav-conversations" },
    { to: "/instructions", label: "Give an instruction", detail: "Review a proposed site decision", testId: "nav-instructions" },
  ] },
  { id: "plans", to: "/drawings", label: "Plans", icon: "drawings", testId: "nav-drawings", items: [
    { to: "/drawings", label: "Drawings & revisions", detail: "Current sheets and drawing changes", testId: "nav-drawing-library" },
    { to: "/site", label: "Building & live site", detail: "Explore the project in 3D", testId: "nav-site" },
    { to: "/machines", label: "Equipment", detail: "Robots, sensors and start checks", testId: "nav-machines" },
    { to: "/robot", label: "Layout robot", detail: "Review layout work before starting", testId: "nav-robot" },
    { to: "/drone", label: "Survey drone", detail: "Compare a measured wall position", testId: "nav-drone" },
  ] },
  { id: "schedule", to: "/plan", label: "Schedule", icon: "schedule", testId: "nav-plan", items: [
    { to: "/plan", label: "Work schedule", detail: "Tasks, dependencies and resources", testId: "nav-work-schedule" },
    { to: "/autonomy", label: "Automation", detail: "Review what Aurora may do", testId: "nav-autonomy" },
  ] },
] as const;
type Menu = "project" | typeof NAVIGATION[number]["id"] | null;
function initialTheme(): Theme {
  const asked = new URLSearchParams(window.location.search).get("theme");
  if (asked === "light" || asked === "dark") return asked;
  try { return localStorage.getItem("aurora-theme") === "dark" ? "dark" : "light"; }
  catch { return "light"; }
}
function Icon({ kind }: { kind: "overview" | "messages" | "drawings" | "schedule" }) {
  const paths = {
    overview: "M3 3h7v7H3z M14 3h7v7h-7z M3 14h7v7H3z M14 14h7v7h-7z",
    messages: "M4 4h16v12H9l-5 4z M8 8h8 M8 12h5",
    drawings: "M5 3h10l4 4v14H5z M14 3v5h5 M8 17v-6h7v6z",
    schedule: "M4 5h16v16H4z M8 3v4 M16 3v4 M4 10h16 M8 14h3 M13 17h3",
  };
  return <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d={paths[kind]} /></svg>;
}
export function Layout() {
  const [theme, setTheme] = useState<Theme>(initialTheme);
  const [menu, setMenu] = useState<Menu>(null);
  const [projects, setProjects] = useState<ProjectItem[]>([]);
  const container = useRef<HTMLDivElement>(null);
  const { pathname } = useLocation();
  const project = useQuery(api.project, []);
  const projectPage = pathname.startsWith("/projects");
  const selected = getSelectedProjectId();
  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    try { localStorage.setItem("aurora-theme", theme); } catch { /* Appearance remains local to this view. */ }
  }, [theme]);
  useEffect(() => { setMenu(null); }, [pathname]);
  useEffect(() => {
    if (menu !== "project") return;
    let cancelled = false;
    request<{ projects: ProjectItem[] }>("GET", "/api/workspace/projects")
      .then((value) => { if (!cancelled) setProjects(value.projects); }).catch(() => {});
    return () => { cancelled = true; };
  }, [menu]);
  useEffect(() => {
    if (!menu) return;
    function outside(event: PointerEvent) { if (!container.current?.contains(event.target as Node)) setMenu(null); }
    function key(event: KeyboardEvent) {
      const trigger = container.current?.querySelector<HTMLButtonElement>(`[data-menu-trigger="${menu}"]`);
      const items = [...(container.current?.querySelectorAll<HTMLElement>(`[data-menu="${menu}"] [role="menuitem"]`) ?? [])];
      if (!container.current?.contains(event.target as Node)) return;
      if (event.key === "Escape") { event.preventDefault(); setMenu(null); trigger?.focus(); return; }
      if (!["ArrowDown", "ArrowUp", "Home", "End"].includes(event.key) || !items.length) return;
      event.preventDefault();
      const index = items.indexOf(document.activeElement as HTMLElement);
      const next = event.key === "Home" ? 0 : event.key === "End" ? items.length - 1 : index < 0 ? event.key === "ArrowUp" ? items.length - 1 : 0 : (index + (event.key === "ArrowUp" ? -1 : 1) + items.length) % items.length;
      items[next]?.focus();
    }
    document.addEventListener("pointerdown", outside); document.addEventListener("keydown", key);
    return () => { document.removeEventListener("pointerdown", outside); document.removeEventListener("keydown", key); };
  }, [menu]);
  return <div className="app project-app">
    <a className="project-skip" href="#project-content">Skip to content</a>
    <header className="project-shell" ref={container}>
      <div className="project-shell-top">
        <Link to="/projects" className="project-brand" aria-label="Aurora projects">
          <svg viewBox="0 0 32 32" width="32" height="32" aria-hidden="true"><path d="M5 26 14 6h4l9 20h-5l-3-7h-7l-3 7z" fill="currentColor" /><path d="M13 16h5l-2.5-6z" fill="var(--bg)" /></svg><span>Aurora</span>
        </Link>
        {!projectPage && <span className="project-shell-divider" />}
        {!projectPage && <div className="project-switch-wrap" onBlur={event => { if (!event.currentTarget.contains(event.relatedTarget)) setMenu(value => value === "project" ? null : value); }}>
          <button type="button" className="project-switch" data-testid="project-switch" data-menu-trigger="project" aria-expanded={menu === "project"} aria-haspopup="menu" onClick={() => setMenu(menu === "project" ? null : "project")}>
            <span className="project-switch-mark" aria-hidden="true">{(project.data?.name || "P").slice(0, 1)}</span>
            <span data-testid="project-name">{project.data?.name || "Your projects"}</span><span className="project-chevron" aria-hidden="true">⌄</span>
          </button>
          {menu === "project" && <div className="project-popover" role="menu" data-menu="project" aria-label="Choose a project">
            <p className="project-menu-title">Your projects</p>
            {projects.map((item) => <button key={item.id} type="button" role="menuitem" className="project-menu-item" onClick={() => selectProject(item.id)}><span>{item.name}</span>{(selected === item.id || !selected && item.id === project.data?.id) && <span aria-label="Current project">✓</span>}</button>)}
            {!projects.length && project.data && <div className="project-menu-item"><span>{project.data.name}</span><span>✓</span></div>}
            <Link to="/projects" role="menuitem" className="project-menu-item">All projects</Link>
            <Link to="/projects/new" role="menuitem" className="project-menu-item project-create">+ Create a project</Link>
          </div>}
        </div>}
        <div className="project-shell-actions">
          <button type="button" className="project-theme" data-testid="theme-toggle" aria-label={theme === "dark" ? "Use light appearance" : "Use dark appearance"} aria-pressed={theme === "dark"} onClick={() => setTheme(theme === "dark" ? "light" : "dark")}>{theme === "dark" ? <span aria-hidden="true">☼</span> : <svg viewBox="0 0 24 24" width="19" height="19" fill="none" stroke="currentColor" strokeWidth="1.6" aria-hidden="true"><path d="M20 15.4A8.5 8.5 0 0 1 8.6 4a8.5 8.5 0 1 0 11.4 11.4Z" /></svg>}</button>
        </div>
      </div>
      {!projectPage && <nav className="project-navigation" aria-label="Main">
        {NAVIGATION.map(group => {
          const selectedGroup = group.items.some(item => item.to === "/" ? pathname === "/" || pathname.startsWith("/flags/") : pathname === item.to || pathname.startsWith(`${item.to}/`)) || group.id === "plans" && ["/compare/", "/sheet/", "/rework/"].some(prefix => pathname.startsWith(prefix)) || group.id === "messages" && pathname.startsWith("/notice/");
          return <div key={group.id} className="project-nav-group" data-active={selectedGroup} onPointerEnter={event => { if (event.pointerType === "mouse") setMenu(group.id); }} onPointerLeave={event => { if (!event.currentTarget.contains(document.activeElement)) setMenu(value => value === group.id ? null : value); }} onFocus={event => { if (event.target instanceof HTMLAnchorElement) setMenu(group.id); }} onBlur={event => { if (!event.currentTarget.contains(event.relatedTarget)) setMenu(value => value === group.id ? null : value); }}>
            <div className="project-nav-tab">
              <NavLink to={group.to} end={group.to === "/"} data-testid={group.testId}><Icon kind={group.icon} /><span>{group.label}</span></NavLink>
              <button type="button" className="project-nav-expand" data-menu-trigger={group.id} aria-label={`${group.label} pages`} aria-expanded={menu === group.id} aria-controls={`navigation-${group.id}`} aria-haspopup="menu" onClick={() => setMenu(group.id)}><svg viewBox="0 0 16 16" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="1.6" aria-hidden="true"><path d="m4 6 4 4 4-4" /></svg></button>
            </div>
            {menu === group.id && <div id={`navigation-${group.id}`} className="project-popover project-nav-menu" role="menu" data-menu={group.id} aria-label={`${group.label} pages`}><p className="project-menu-title">{group.label}</p>{group.items.map(item => <NavLink key={item.to} to={item.to} end={item.to === "/"} role="menuitem" data-testid={item.testId} className="project-tool-item" onClick={() => setMenu(null)}><span>{item.label}</span><small>{item.detail}</small></NavLink>)}</div>}
          </div>;
        })}
      </nav>}
    </header>
    <main className="page project-content" id="project-content"><div className="project-route" key={pathname}><Outlet /></div></main>
    <footer className="project-footer"><span>Aurora</span><span>One project. A shared understanding.</span></footer>
  </div>;
}
