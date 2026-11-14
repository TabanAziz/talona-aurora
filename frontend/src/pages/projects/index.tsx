import { useEffect, useRef, useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import type { Machine, Task } from "../../api/client";
import { getSelectedProjectId, selectProject } from "../../api/workspace";
import { GeometryScene } from "../drawings/GeometryView";
import { Immersive } from "../../components/immersive/Immersive";
import { ProjectMark } from "../../components/project/ProjectMark";
import type { Geometry } from "../../components/plan3d/geometry";
import { workspaceApi, type ImportDraft, type ProjectSummary } from "./api";
import { validateDraft } from "./validation";
import "./projects.css";

const productText = (value: string) => value.replace(/\bdeepseek-[\w.-]+\b/gi, "Aurora").replace(/\bDeepSeek\b/gi, "Aurora");
const errorText = (reason: unknown) => reason instanceof Error ? productText(reason.message) : "Something went wrong. Please try again.";
const lines = (value: string) => [...new Set(value.split("\n").map(item => item.trim()).filter(Boolean))];
const reviewTabs = [["project", "Project & teams"], ["programme", "Programme"], ["drawings", "Drawings & 3D"]];

export function Projects() {
  const [projects, setProjects] = useState<ProjectSummary[] | null>(null);
  const [error, setError] = useState("");
  const [query, setQuery] = useState("");
  const [branding, setBranding] = useState<string | null>(null);
  const [logoError, setLogoError] = useState("");
  const [deleted, setDeleted] = useState<ProjectSummary[]>([]);
  const [pendingDelete, setPendingDelete] = useState<ProjectSummary | null>(null);
  const [projectAction, setProjectAction] = useState<string | null>(null);
  const [actionError, setActionError] = useState("");
  const active = getSelectedProjectId();
  function load() {
    setError("");
    setProjects(null);
    workspaceApi.projects().then(data => { setProjects(data.projects); setDeleted(data.deleted_projects ?? []); }).catch(reason => setError(errorText(reason)));
  }
  useEffect(load, []);
  async function removeProject() {
    if (!pendingDelete) return;
    setProjectAction(pendingDelete.id); setActionError("");
    try {
      const removed = await workspaceApi.remove(pendingDelete.id);
      setProjects(current => current?.filter(project => project.id !== removed.id) ?? null);
      setDeleted(current => [removed, ...current.filter(project => project.id !== removed.id)]);
      setPendingDelete(null);
    } catch (reason) { setActionError(errorText(reason)); }
    finally { setProjectAction(null); }
  }
  async function restoreProject(project: ProjectSummary) {
    setProjectAction(project.id); setActionError("");
    try {
      await workspaceApi.restore(project.id);
      const data = await workspaceApi.projects();
      setProjects(data.projects); setDeleted(data.deleted_projects ?? []);
    } catch (reason) { setActionError(errorText(reason)); }
    finally { setProjectAction(null); }
  }
  async function makeLogo(id: string) {
    setBranding(id); setLogoError("");
    try {
      const brand = await workspaceApi.logo(id);
      setProjects(current => current?.map(project => project.id === id ? { ...project, brand } : project) ?? null);
    } catch (reason) { setLogoError(errorText(reason)); }
    finally { setBranding(null); }
  }
  const shown = projects?.filter(project => project.name.toLocaleLowerCase().includes(query.toLocaleLowerCase()));
  return <section className="workspace-page" data-testid="projects-page">
    <header className="workspace-heading"><div><p className="workspace-eyebrow">Your workspace</p><h1>Projects</h1><p className="muted">Open a site, or bring a new one into Aurora.</p></div><Link className="button button-primary workspace-primary" to="/projects/new">New project <span aria-hidden="true">+</span></Link></header>
    <div className="workspace-toolbar"><label className="workspace-search">Find a project<input type="search" placeholder="Search by project name" value={query} onChange={event => setQuery(event.target.value)} /></label><p className="muted">{projects ? `${projects.length} ${projects.length === 1 ? "project" : "projects"}` : "Loading workspace"}</p></div>
    {logoError && <p className="workspace-error-text" role="alert">{logoError}</p>}
    {actionError && !pendingDelete && <p className="workspace-error-text" role="alert">{actionError}</p>}
    {error ? <Failure text={error} retry={load} /> : !projects ? <div className="workspace-loading" role="status"><div /><div /><div /><p>Loading your projects…</p></div> : !shown?.length ? <div className="workspace-empty"><h2>{query ? "No matching projects" : "Your next site starts here"}</h2><p className="muted">{query ? "Try another project name." : "Import drawings, a programme, or a project description to create your first project."}</p>{query ? <button className="button" onClick={() => setQuery("")}>Clear search</button> : <Link className="button" to="/projects/new">Create a project</Link>}</div> : <div className="workspace-project-grid">{shown.map(project => {
      const current = project.id === active || (!active && project.is_default);
      return <article className="workspace-project" key={project.id} data-testid="project-card">
        <ProjectMark brand={project.brand} name={project.name} />
        {!project.brand && <button className="button" disabled={branding !== null} onClick={() => void makeLogo(project.id)}>{branding === project.id ? "Aurora is drawing…" : "Create project logo"}</button>}
        <div className="workspace-project-title"><h2>{project.name}</h2>{current && <span className="workspace-pill">Current project</span>}</div>
        <p className="muted">{project.is_default ? "Original project" : "Imported project"}</p>
        <dl className="workspace-counts"><div><dt>Rooms & areas</dt><dd>{project.unit_count}</dd></div><div><dt>Teams</dt><dd>{project.crew_count}</dd></div><div><dt>Drawings</dt><dd>{project.sheet_count}</dd></div></dl>
        <div className="workspace-project-actions"><button className="button workspace-open" data-testid={`project-select-${project.id}`} onClick={() => selectProject(project.id)}>Open project <span aria-hidden="true">↗</span></button><button className="button workspace-delete" aria-label={`Delete ${project.name}`} onClick={() => { setActionError(""); setPendingDelete(project); }}>Delete</button></div>
      </article>;
    })}</div>}
    {deleted.length > 0 && <details className="workspace-trash"><summary>Deleted projects ({deleted.length})</summary><p className="muted">Restore a project with its drawings, programme and history.</p><ul>{deleted.map(project => <li key={project.id}><strong>{project.name}</strong><button className="button" disabled={projectAction !== null} onClick={() => void restoreProject(project)}>{projectAction === project.id ? "Restoring…" : "Restore project"}</button></li>)}</ul></details>}
    {pendingDelete && <DeleteProjectDialog project={pendingDelete} busy={projectAction !== null} error={actionError} onCancel={() => setPendingDelete(null)} onConfirm={() => void removeProject()} />}
  </section>;
}

function DeleteProjectDialog({ project, busy, error, onCancel, onConfirm }: { project: ProjectSummary; busy: boolean; error: string; onCancel: () => void; onConfirm: () => void }) {
  const dialog = useRef<HTMLDialogElement>(null);
  useEffect(() => { dialog.current?.showModal(); }, []);
  return <dialog ref={dialog} className="workspace-delete-dialog" aria-labelledby="delete-project-heading" onCancel={event => { event.preventDefault(); if (!busy) onCancel(); }}>
    <h2 id="delete-project-heading">Delete project?</h2><p><strong>{project.name}</strong> will be removed from your workspace.</p><p className="muted">You can restore it from Deleted projects with its drawings, programme and history.</p>
    {error && <p className="workspace-error-text" role="alert">{error}</p>}
    <div className="workspace-actions"><button type="button" className="button" autoFocus disabled={busy} onClick={onCancel}>Keep project</button><button type="button" className="button workspace-delete" disabled={busy} onClick={onConfirm}>{busy ? "Deleting…" : "Delete project"}</button></div>
  </dialog>;
}

export function NewProject() {
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [designBuilding, setDesignBuilding] = useState(() => new URLSearchParams(window.location.search).get("design") !== "0");
  const [files, setFiles] = useState<File[]>([]);
  const [dragging, setDragging] = useState(false);
  const [draft, setDraft] = useState<ImportDraft | null>(null);
  const [created, setCreated] = useState<ProjectSummary | null>(null);
  const [connectChannels, setConnectChannels] = useState(false);
  const [channelsBound, setChannelsBound] = useState(false);
  const [busy, setBusy] = useState<"import" | "create" | null>(null);
  const [error, setError] = useState("");
  const [reviewed, setReviewed] = useState(false);
  const [tab, setTab] = useState("project");
  const step = created ? 3 : draft ? 2 : 1;
  const focus = useRef<HTMLHeadingElement>(null);
  const picker = useRef<HTMLInputElement>(null);
  useEffect(() => { focus.current?.focus(); }, [step]);
  function addFiles(incoming: FileList | File[]) {
    const additions = Array.from(incoming);
    setFiles(current => [...current, ...additions.filter(file => !current.some(item => item.name === file.name && item.size === file.size && item.lastModified === file.lastModified))]);
  }
  async function importProject(event: FormEvent) {
    event.preventDefault();
    setError(""); setBusy("import");
    try { setDraft(await workspaceApi.import(name, description, files, designBuilding)); setReviewed(false); setTab("project"); }
    catch (reason) { setError(errorText(reason)); }
    finally { setBusy(null); }
  }
  async function createProject() {
    if (!draft) return;
    const invalid = validateDraft(draft);
    if (invalid) { setError(invalid); return; }
    setError(""); setBusy("create");
    try {
      const saved = await workspaceApi.create(draft);
      setCreated(saved);
      if (connectChannels) { await workspaceApi.connectDemoChannels(saved.id); setChannelsBound(true); }
    }
    catch (reason) { setError(errorText(reason)); }
    finally { setBusy(null); }
  }
  function change(next: ImportDraft) { setDraft(next); setReviewed(false); setError(""); }
  async function retryChannels() {
    if (!created) return;
    setBusy("create"); setError("");
    try { await workspaceApi.connectDemoChannels(created.id); setChannelsBound(true); }
    catch (reason) { setError(errorText(reason)); }
    finally { setBusy(null); }
  }
  return <section className="workspace-page workspace-setup" data-testid="new-project-page">
    <Link className="workspace-back" to="/projects">← All projects</Link>
    <header className="workspace-heading"><div><p className="workspace-eyebrow">A new beginning</p><h1 ref={focus} tabIndex={-1}>{created ? "Your project is ready" : draft ? "Make it yours" : "Create a project"}</h1><p className="muted">{created ? "Saved separately. Your other projects are still available." : draft ? "Review the imported information before it becomes your working project." : "Bring your plans and programme. Aurora will prepare a draft for you to review."}</p></div></header>
    <ol className="workspace-steps" aria-label="Project setup">{["Add your material", "Review the draft", "Open your project"].map((label, index) => <li key={label} aria-current={step === index + 1 ? "step" : undefined} className={step >= index + 1 ? "is-active" : ""}><span>{step > index + 1 ? "✓" : index + 1}</span>{label}</li>)}</ol>
    {error && <Failure text={error} />}
    {created ? <div className="workspace-complete" data-testid="project-created"><div className="workspace-complete-mark" aria-hidden="true">✓</div><p className="workspace-eyebrow">Project created</p><h2>{created.name}</h2><p className="muted">{created.unit_count} rooms & areas · {created.crew_count} teams · {created.sheet_count} drawings</p><button className="button button-primary workspace-primary" data-testid="project-open" onClick={() => selectProject(created.id)}>Open project <span aria-hidden="true">→</span></button>{connectChannels && <p className="muted">{channelsBound ? "The demo inbox and Telegram group are assigned to this project." : "The project was saved. Channel assignment did not finish; retry the channel assignment below."}</p>}{connectChannels && !channelsBound && <button className="button" disabled={!!busy} onClick={() => void retryChannels()}>Retry channel assignment</button>}<Link to="/projects">Back to all projects</Link></div> : !draft ? <form onSubmit={importProject} className="workspace-input-grid">
      <div className="workspace-input-main"><label className="workspace-field">Project name<input autoComplete="off" required value={name} onChange={event => setName(event.target.value)} placeholder="e.g. Riverside retrofit" disabled={!!busy} /></label><label className="workspace-field">Tell us about the site<textarea rows={6} value={description} onChange={event => setDescription(event.target.value)} placeholder="Describe the building, rooms, teams, and planned work. Include known dates and dimensions." disabled={!!busy} /><span className="muted">Use your own brief, upload files, or combine both.</span></label>
      <label className="workspace-confirm"><input type="checkbox" checked={designBuilding} disabled={!!busy} onChange={event => setDesignBuilding(event.target.checked)} /><span>Let Aurora design the building in 3D</span></label><p className="muted">{designBuilding ? "Aurora designs a conceptual building where geometry is missing. Supplied wall coordinates and differences between floors stay preserved." : "Aurora analyses your material and keeps supplied geometry. Enable building design to create a new layout from your brief."}</p>
      <div className={`workspace-drop${dragging ? " is-dragging" : ""}`} onDragOver={event => { event.preventDefault(); if (!busy) setDragging(true); }} onDragLeave={() => setDragging(false)} onDrop={event => { event.preventDefault(); setDragging(false); if (!busy) addFiles(event.dataTransfer.files); }}><svg aria-hidden="true" viewBox="0 0 32 32"><path d="M16 22V5m-6 6 6-6 6 6M5 21v6h22v-6" /></svg><strong>Drop your project files here</strong><p className="muted">PDF drawings, XLSX or CSV schedules, JSON, or text</p><button type="button" className="button workspace-file-button" onClick={() => picker.current?.click()} disabled={!!busy}>Choose files</button><input ref={picker} type="file" multiple hidden aria-label="Project files" accept=".pdf,.xlsx,.csv,.json,.txt,.md" onChange={event => { if (event.target.files) addFiles(event.target.files); event.target.value = ""; }} disabled={!!busy} /></div>
      {!!files.length && <ul className="workspace-files" aria-label="Selected files">{files.map((file, index) => <li key={`${file.name}-${index}`}><span><strong>{file.name}</strong><small>{formatBytes(file.size)}</small></span><button type="button" className="button" aria-label={`Remove ${file.name}`} disabled={!!busy} onClick={() => setFiles(items => items.filter((_, itemIndex) => itemIndex !== index))}>Remove</button></li>)}</ul>}
      <div className="workspace-actions"><button className="button button-primary workspace-primary" type="submit" data-testid="project-import" disabled={!!busy || !name.trim() || (!description.trim() && !files.length)}>{busy ? "Aurora is preparing your project…" : "Prepare project"}<span aria-hidden="true">→</span></button></div>
      {busy && <p className="workspace-processing" role="status">Aurora is analysing your material and preparing the requested building layout. This can take a moment. The project will only be saved after your review.</p>}</div>
      <aside className="workspace-aside"><h2>A considered start</h2><p>Aurora prepares rooms, teams, and a programme from your actual material.</p><div><span>01</span><p>Add the information you have.</p></div><div><span>02</span><p>Check sources, assumptions, dimensions, and dates.</p></div><div><span>03</span><p>Create a separate project and start working.</p></div><p className="muted">A 3D preview is available when the imported drawings contain geometry. Missing information stays visible.</p></aside>
    </form> : <div data-testid="project-review" className="workspace-review">
      <div className="workspace-review-summary"><div><h2>{draft.project.name}</h2><p className="muted">{draft.model_used ? "Prepared by Aurora" : "Imported from structured project data"}</p></div><p>{draft.project.units.length} rooms & areas · {draft.project.crews.length} teams · {draft.plan.tasks?.length ?? 0} tasks</p></div>
      <div className="workspace-review-tabs" role="tablist" aria-label="Review project details" onKeyDown={event => {
        if (busy || !["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
        event.preventDefault();
        const current = reviewTabs.findIndex(([value]) => value === tab);
        const next = event.key === "Home" ? 0 : event.key === "End" ? reviewTabs.length - 1 : (current + (event.key === "ArrowRight" ? 1 : -1) + reviewTabs.length) % reviewTabs.length;
        setTab(reviewTabs[next][0]);
        event.currentTarget.querySelectorAll<HTMLButtonElement>("[role=tab]")[next]?.focus();
      }}>{reviewTabs.map(([value, label]) => <button type="button" key={value} role="tab" tabIndex={tab === value ? 0 : -1} disabled={busy === "create"} aria-selected={tab === value} aria-controls={`review-${value}`} id={`tab-${value}`} className={tab === value ? "is-active" : ""} onClick={() => setTab(value)}>{label}</button>)}</div>
      <fieldset disabled={busy === "create"} role="tabpanel" id={`review-${tab}`} aria-labelledby={`tab-${tab}`} className="workspace-review-panel">
      {tab === "project" ? <div className="workspace-review-grid"><div className="workspace-editor"><label className="workspace-field">Project name<input value={draft.project.name} onChange={event => change({ ...draft, project: { ...draft.project, name: event.target.value } })} /></label><label className="workspace-field">Description<textarea rows={4} value={draft.project.description} onChange={event => change({ ...draft, project: { ...draft.project, description: event.target.value } })} /></label><div className="workspace-two-fields"><ListField label="Rooms & areas" hint="One room or area per line." items={draft.project.units} onChange={units => change({ ...draft, project: { ...draft.project, units } })} /><ListField label="Teams" hint="One team per line." items={draft.project.crews} onChange={crews => change({ ...draft, project: { ...draft.project, crews } })} /></div></div><ReviewNotes draft={draft} /></div> : tab === "programme" ? <Programme draft={draft} onChange={change} /> : <Drawings draft={draft} onChange={change} />}
      {!!draft.machines?.length && tab === "project" && <MachineCoverage draft={draft} onChange={change} />}
      </fieldset>
      <label className="workspace-confirm"><input type="checkbox" checked={connectChannels} disabled={!!busy} onChange={event => setConnectChannels(event.target.checked)} /><span>Use the configured demo Telegram group and email inbox for this project. This moves incoming demo messages from the previously connected project.</span></label><footer className="workspace-review-footer"><label className="workspace-confirm"><input type="checkbox" checked={reviewed} disabled={!!busy} onChange={event => setReviewed(event.target.checked)} data-testid="project-confirm" /><span>I have checked the draft, its assumptions, and available dimensions.</span></label><div className="workspace-actions"><button className="button" disabled={!!busy} onClick={() => { setDraft(null); setError(""); }}>Back to material</button><button className="button button-primary workspace-primary" data-testid="project-create" disabled={!reviewed || !!busy} onClick={createProject}>{busy === "create" ? "Saving project…" : "Create project"}<span aria-hidden="true">→</span></button></div></footer>
    </div>}
  </section>;
}

function ListField({ label, hint, items, onChange }: { label: string; hint: string; items: string[]; onChange: (items: string[]) => void }) {
  const [text, setText] = useState(items.join("\n"));
  return <label className="workspace-field">{label}<textarea rows={5} value={text} onChange={event => { setText(event.target.value); onChange(lines(event.target.value)); }} /><span className="muted">{hint}</span></label>;
}

function MachineCoverage({ draft, onChange }: { draft: ImportDraft; onChange: (draft: ImportDraft) => void }) {
  function edit(index: number, patch: Partial<Machine>) {
    onChange({ ...draft, machines: draft.machines?.map((machine, i) => i === index ? { ...machine, ...patch } : machine) });
  }
  return <details className="workspace-geometry-detail workspace-machine-coverage"><summary>Imported machine coverage ({draft.machines?.length})</summary><p className="muted">If you change a room name, update the machines that work there too. Use names from this project's rooms and drawings.</p><p className="muted">Available drawing sheets: {draft.project.sheets.length ? draft.project.sheets.join(", ") : "No drawing sheets in this project"}.</p>{draft.machines?.map((machine, index) => <fieldset key={machine.id} className="workspace-task"><legend>{machine.name}</legend><ListField label="Rooms & areas" hint="One covered room or area per line." items={machine.units ?? []} onChange={units => edit(index, { units })} /><ListField label="Drawing sheets" hint="One sheet per line. Keep the source sheet identifiers." items={machine.sheets ?? []} onChange={sheets => edit(index, { sheets })} /><p className="muted">{machine.kind} · {machine.simulated ? "Simulated" : "Registered machine"}</p></fieldset>)}</details>;
}

function ReviewNotes({ draft: sourceDraft }: { draft: ImportDraft }) {
  const draft = { ...sourceDraft, assumptions: sourceDraft.assumptions.map(productText), warnings: sourceDraft.warnings.map(productText) };
  return <aside className="workspace-notes"><h3>What to check</h3><section><h3>Assumptions</h3>{draft.assumptions.length ? <ul>{draft.assumptions.map((item, index) => <li key={index}>{item}</li>)}</ul> : <p className="muted">No assumptions reported by the importer.</p>}</section><section><h3>Warnings & missing information</h3>{draft.warnings.length ? <ul className="workspace-warnings">{draft.warnings.map((item, index) => <li key={index}>{item}</li>)}</ul> : <p className="muted">No warnings reported. Check the details against your source material.</p>}</section><section><h3>Sources</h3>{draft.sources.length ? <ul>{draft.sources.map((source, index) => <li key={index}>{source.name}<span className="muted"> · {source.kind}</span></li>)}</ul> : <p className="muted">No source list was returned.</p>}</section></aside>;
}

function Programme({ draft, onChange }: { draft: ImportDraft; onChange: (draft: ImportDraft) => void }) {
  const tasks = draft.plan.tasks ?? [];
  function update(index: number, changes: Partial<Task>) { onChange({ ...draft, plan: { ...draft.plan, tasks: tasks.map((task, i) => i === index ? { ...task, ...changes } : task) } }); }
  function add() { onChange({ ...draft, plan: { ...draft.plan, tasks: [...tasks, { id: `task-${crypto.randomUUID()}`, name: "", unit: draft.project.units[0] ?? null, crew: draft.project.crews[0] ?? "", start: "", end: "", status: "planned", depends_on: [] }] } }); }
  return <div className="workspace-programme"><div className="workspace-section-heading"><div><h3>Programme</h3><p className="muted">Dates are displayed in your local time. Check sequencing against the source programme.</p></div><button className="button" onClick={add}>Add task</button></div><label className="workspace-field workspace-handover">Planned handover<input type="datetime-local" value={localDate(draft.plan.handover)} onChange={event => onChange({ ...draft, plan: { ...draft.plan, handover: isoDate(event.target.value) } })} /></label>{!tasks.length && <p className="workspace-empty">No tasks were imported. Add tasks or go back to include a programme.</p>}{tasks.map((task, index) => <fieldset key={task.id} className="workspace-task"><legend>Task {index + 1}</legend><label className="workspace-field">Task name<input value={task.name} onChange={event => update(index, { name: event.target.value })} /></label><label className="workspace-field">Room or area<select value={task.unit ?? ""} onChange={event => update(index, { unit: event.target.value || null })}><option value="">Whole site</option>{task.unit && !draft.project.units.includes(task.unit) && <option value={task.unit}>{task.unit} (not in project)</option>}{draft.project.units.map(unit => <option key={unit}>{unit}</option>)}</select></label><label className="workspace-field">Team<select value={task.crew} onChange={event => update(index, { crew: event.target.value })}><option value="">Choose a team</option>{task.crew && !draft.project.crews.includes(task.crew) && <option value={task.crew}>{task.crew} (not in project)</option>}{draft.project.crews.map(crew => <option key={crew}>{crew}</option>)}</select></label><label className="workspace-field">Start<input type="datetime-local" value={localDate(task.start)} onChange={event => update(index, { start: isoDate(event.target.value) })} /></label><label className="workspace-field">End<input type="datetime-local" value={localDate(task.end)} onChange={event => update(index, { end: isoDate(event.target.value) })} /></label><label className="workspace-field">Status<select value={task.status} onChange={event => update(index, { status: event.target.value as Task["status"] })}><option value="planned">Planned</option><option value="on_hold">On hold</option><option value="in_progress">In progress</option><option value="done">Done</option></select></label><button className="button" onClick={() => onChange({ ...draft, plan: { ...draft.plan, tasks: tasks.filter((_, i) => i !== index).map(item => ({ ...item, depends_on: item.depends_on?.filter(id => id !== task.id) })) } })}>Remove task</button></fieldset>)}</div>;
}

function Drawings({ draft, onChange }: { draft: ImportDraft; onChange: (draft: ImportDraft) => void }) {
  const [selected, setSelected] = useState(0);
  const drawing = draft.drawings[selected];
  function editGeometry(key: "width" | "height" | "wall_height", value: string) {
    if (!drawing?.geometry) return;
    onChange({ ...draft, drawings: draft.drawings.map((item, index) => index === selected ? { ...item, geometry: { ...drawing.geometry!, [key]: Number(value) } } : item) });
  }
  return <div className="workspace-drawings">{draft.drawings.length ? <><label className="workspace-field workspace-handover">Drawing<select value={selected} onChange={event => setSelected(Number(event.target.value))}>{draft.drawings.map((item, index) => <option value={index} key={index}>{item.sheet} · {item.revision}{item.title ? ` · ${item.title}` : ""}</option>)}</select></label>{drawing?.geometry ? <><div className="workspace-drawing-layout"><div><GeometryPreview geometry={drawing.geometry} /><p className="muted">Drag to orbit. Scroll to zoom. Preview follows the imported geometry.</p></div><div className="workspace-editor"><h3>Check dimensions</h3><p className="muted">Dimensions are in millimetres. Changing an envelope value does not scale individual walls.</p>{[["width", "Plan width"], ["height", "Plan depth"], ["wall_height", "Wall height"]].map(([key, label]) => <label className="workspace-field" key={key}>{label} (mm)<input type="number" min="1" step="any" value={drawing.geometry![key as "width" | "height" | "wall_height"]} onChange={event => editGeometry(key as "width" | "height" | "wall_height", event.target.value)} /></label>)}<p className="muted">{drawing.geometry.walls.length} walls · {drawing.geometry.openings?.length ?? 0} openings · {drawing.geometry.rooms?.length ?? 0} room labels</p></div></div><details className="workspace-geometry-detail"><summary>Edit wall coordinates & room labels</summary><GeometryEditor geometry={drawing.geometry} onChange={geometry => onChange({ ...draft, drawings: draft.drawings.map((item, index) => index === selected ? { ...item, geometry } : item) })} /></details></> : <div className="workspace-empty"><h3>3D geometry is unavailable for this drawing</h3><p className="muted">The drawing was imported without wall coordinates. Aurora will keep it as a project drawing.</p></div>}</> : <div className="workspace-empty"><h3>No drawing geometry was returned</h3><p className="muted">Your rooms, teams, and programme can still be saved. Add a structured geometry file to get a 3D preview.</p></div>}</div>;
}

function GeometryPreview({ geometry }: { geometry: Geometry }) {
  return <div data-testid="project-model"><Immersive title={`Drawing ${geometry.sheet}`} testId="project-model"><GeometryScene geometry={geometry} label={`Drawing ${geometry.sheet}`} hostClass="workspace-model" /></Immersive></div>;
}

function GeometryEditor({ geometry, onChange }: { geometry: Geometry; onChange: (geometry: Geometry) => void }) {
  const [value, setValue] = useState(JSON.stringify(geometry, null, 2));
  const [error, setError] = useState("");
  useEffect(() => { setValue(JSON.stringify(geometry, null, 2)); }, [geometry]);
  function apply() {
    try {
      const parsed = JSON.parse(value) as Geometry;
      if (![parsed.width, parsed.height, parsed.wall_height].every(item => Number.isFinite(item) && item > 0) || !Array.isArray(parsed.walls) || parsed.walls.some(wall => ![wall.x1, wall.x2, wall.y1, wall.y2, wall.thickness].every(Number.isFinite) || wall.thickness <= 0)) throw new Error("Use positive dimensions and valid wall coordinates.");
      setError(""); onChange(parsed);
    } catch (reason) { setError(reason instanceof SyntaxError ? "The geometry is not valid JSON. Check commas and brackets." : errorText(reason)); }
  }
  return <div className="workspace-editor"><p className="muted">Edit the actual geometry in millimetres. Apply your changes to update the preview.</p><label className="workspace-field">Drawing geometry<textarea className="workspace-json" rows={12} value={value} onChange={event => setValue(event.target.value)} spellCheck={false} /></label>{error && <p role="alert" className="workspace-error-text">{error}</p>}<button className="button" onClick={apply}>Apply geometry</button></div>;
}

function Failure({ text, retry }: { text: string; retry?: () => void }) { return <div role="alert" className="workspace-error"><div><strong>We could not complete that step</strong><p>{text}</p></div>{retry && <button className="button" onClick={retry}>Try again</button>}</div>; }
function formatBytes(value: number) { return value >= 1024 * 1024 ? `${(value / (1024 * 1024)).toFixed(1)} MB` : `${Math.max(1, Math.round(value / 1024))} KB`; }
function localDate(value: string) { const date = new Date(value); return Number.isNaN(date.getTime()) ? "" : new Date(date.getTime() - date.getTimezoneOffset() * 60000).toISOString().slice(0, 16); }
function isoDate(value: string) { return value ? new Date(value).toISOString() : ""; }
