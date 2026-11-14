import { useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { api, type InboundEvent } from "../../api/client";
import { useQuery } from "../../api/useQuery";
import { Async, Empty } from "../../components/States";
import { Immersive } from "../../components/immersive/Immersive";
import { drawingsApi, type DrawingRevision, type DrawingSheet } from "./api";
import { comparisonsOf, confirmationsOf, receivedLabel, revisionOf } from "./logic";
import { GeometryView } from "./GeometryView";
import { PlanDrawing } from "./PlanDrawing";
import "./drawings.css";

export function Drawings() {
  const register = useQuery(drawingsApi.list, [], { empty: { sheets: [] } });
  return <article className="drawings" data-testid="drawings-view">
    <header className="page-head"><div><p className="drawings-eyebrow">Project library</p><h1>Drawings</h1><p className="muted">The current set, every revision, and the people working from it.</p></div>
      <div className="row"><Link className="button" to="/site">Building & live site</Link><button className="button" type="button" onClick={register.reload} data-testid="drawings-refresh">Refresh register</button></div></header>
    {register.data?.model_name && <div className="panel"><strong>Prepared by Aurora</strong>{register.data.model_summary && <p>{register.data.model_summary.replace(/^DeepSeek building design:\s*/, "").replace(/\bDeepSeek\b/gi, "Aurora")}</p>}<div className="row"><Link to="/robot">Open layout robot</Link><Link to="/drone">Open survey drone</Link></div></div>}
    <Async query={register} rows={8}>{({ sheets }) => sheets.length === 0 ? <Empty>No drawings have been added to this project. <Link to="/projects/new?design=1">Create a project with Aurora</Link> to start the register.</Empty> : <Register sheets={sheets} />}</Async>
  </article>;
}

function Register({ sheets }: { sheets: DrawingSheet[] }) {
  const [params, setParams] = useSearchParams();
  const [search, setSearch] = useState("");
  const selected = sheets.find((sheet) => sheet.id === params.get("sheet")) ?? sheets[0];
  const revision = revisionOf(selected, params.get("revision"));
  const filtered = sheets.filter((sheet) => `${sheet.id} ${sheet.title}`.toLowerCase().includes(search.toLowerCase()));
  function select(sheet: DrawingSheet, rev?: string) {
    const next = new URLSearchParams(params);
    next.set("sheet", sheet.id);
    if (rev) next.set("revision", rev); else next.delete("revision");
    setParams(next, { replace: true });
  }
  return <div className="drawings-layout">
    <aside className="drawings-register" aria-label="Drawing register">
      <div className="drawings-register-head"><h2>All drawings <span className="muted">{sheets.length}</span></h2><label className="drawings-search">Find a drawing<input type="search" placeholder="Sheet number or title" value={search} onChange={(event) => setSearch(event.target.value)} data-testid="drawings-search" /></label></div>
      {filtered.length === 0 ? <p className="drawings-unavailable">No drawings match this search.</p> : <ul className="drawings-list" data-testid="drawings-register">{filtered.map((sheet) => <li key={sheet.id}><button type="button" onClick={() => select(sheet)} aria-pressed={sheet.id === selected.id} className="drawings-sheet" data-testid="drawings-sheet" data-sheet={sheet.id}>
        <span className="drawings-sheet-line"><strong>{sheet.id}</strong><span className="drawings-revision-tag">{sheet.current_revision ? `Rev ${sheet.current_revision}` : "Revision unavailable"}</span></span><span>{sheet.title}</span><span className="muted small">{sheet.revisions.length} {sheet.revisions.length === 1 ? "revision" : "revisions"}</span>
      </button></li>)}</ul>}
    </aside>
    <section className="drawings-detail" aria-label="Selected drawing" data-testid="drawings-detail" data-sheet={selected.id}>
      <div className="drawings-detail-head"><div><h2>{selected.id} <span className="muted">{selected.title}</span></h2><p className="muted small">Current revision: {selected.current_revision ?? "unavailable"}</p></div>
        {revision && <label className="drawings-revision-select">Revision<select value={revision.revision} onChange={(event) => select(selected, event.target.value)} data-testid="drawings-revision">{[...selected.revisions].reverse().map((item) => <option value={item.revision} key={item.revision}>Rev {item.revision}{item.revision === selected.current_revision ? " (current)" : " (older)"}</option>)}</select></label>}
      </div>
      {revision ? <RevisionDetail key={`${selected.id}-${revision.revision}`} sheet={selected} revision={revision} onRevision={(value) => select(selected, value)} /> : <Empty>This sheet has no available revisions.</Empty>}
    </section>
  </div>;
}

function RevisionDetail({ sheet, revision, onRevision }: { sheet: DrawingSheet; revision: DrawingRevision; onRevision: (value: string) => void }) {
  const [mode, setMode] = useState<"drawing" | "pdf" | "3d">(new URLSearchParams(window.location.search).get("view") === "3d" && revision.has_geometry ? "3d" : revision.image_url ? "drawing" : revision.pdf_url ? "pdf" : "3d");
  const [zoom, setZoom] = useState(1);
  const [imageFailed, setImageFailed] = useState(false);
  const diffs = useQuery(api.diffs, []);
  const waiting = useQuery(api.waiting, []);
  const events = useQuery(api.events, []);
  const label = `${sheet.id}, Rev ${revision.revision}`;
  return <>
    <Immersive title={label} testId="drawings">
    <div className="drawings-view-controls"><div className="segmented" role="group" aria-label="Drawing view">
      <button type="button" aria-pressed={mode === "drawing"} onClick={() => setMode("drawing")} disabled={!revision.image_url && !revision.geometry_url} data-testid="drawings-mode-drawing">Drawing</button>
      <button type="button" aria-pressed={mode === "pdf"} onClick={() => setMode("pdf")} disabled={!revision.pdf_url} data-testid="drawings-mode-pdf">PDF</button>
      {revision.has_geometry && revision.geometry_url && <button type="button" aria-pressed={mode === "3d"} onClick={() => setMode("3d")} data-testid="drawings-mode-3d">3D</button>}
    </div>{mode === "drawing" && <label className="drawings-zoom">Zoom<select value={zoom} onChange={(event) => setZoom(Number(event.target.value))}><option value={1}>Fit</option><option value={1.5}>150%</option><option value={2}>200%</option><option value={3}>300%</option></select></label>}
    {revision.pdf_url && <a href={revision.pdf_url} className="drawings-file-link" target="_blank" rel="noreferrer" data-testid="drawings-open-pdf">Open PDF ↗</a>}{mode === "drawing" && revision.image_url && revision.geometry_url && <a href={revision.image_url} className="drawings-file-link" target="_blank" rel="noreferrer">Source image ↗</a>}</div>
      <div className={`drawings-preview drawings-preview-${mode}`} data-testid="drawings-preview">
        {mode === "3d" && revision.has_geometry && revision.geometry_url ? <GeometryView url={revision.geometry_url} label={label} /> : mode === "drawing" && revision.has_geometry && revision.geometry_url ? <PlanDrawing url={revision.geometry_url} zoom={zoom} /> : mode === "drawing" && revision.image_url && !imageFailed ?
          <div className="drawings-paper-scroll" tabIndex={0} aria-label="Drawing, scroll to pan when zoomed"><img src={revision.image_url} alt={`${label}, ${sheet.title}`} onError={() => setImageFailed(true)} style={{ width: `${zoom * 100}%` }} data-testid="drawings-image" /></div> : revision.pdf_url ?
          <object data={revision.pdf_url} type="application/pdf" aria-label={`${label} original PDF`} className="drawings-pdf" data-testid="drawings-pdf"><p>This browser cannot display the PDF here. <a href={revision.pdf_url} target="_blank" rel="noreferrer">Open the original PDF</a>.</p></object> :
          <p className="drawings-unavailable">No readable file is available for this revision. Its source and version history remain below.</p>}
      </div>
    </Immersive>
    {!revision.has_geometry && <p className="drawings-geometry-note muted" data-testid="drawings-no-geometry">This revision has no structured geometry. Read the original drawing; a 3D model has not been inferred from the PDF.</p>}
    <div className="drawings-context">
      <section className="drawings-context-section"><h3>Revision history</h3><ol className="drawings-history" data-testid="drawings-history">{[...sheet.revisions].reverse().map((item) => <li key={item.revision}><button type="button" onClick={() => onRevision(item.revision)} aria-current={item.revision === revision.revision ? "true" : undefined}>Rev {item.revision}</button><span>{item.revision === sheet.current_revision ? "Current" : "Superseded"}</span><time className="muted small" dateTime={item.received_at ?? undefined}>{receivedLabel(item.received_at)}</time></li>)}</ol></section>
      <section className="drawings-context-section"><h3>Revision changes</h3><Async query={diffs} rows={2}>{(all) => {
        const related = comparisonsOf(all, sheet.id, revision.revision);
        return related.length ? <ul className="drawings-related">{related.map((diff) => <li key={diff.id}><Link to={`/compare/${encodeURIComponent(diff.id)}`} data-testid="drawings-compare">Compare Rev {diff.from_rev} with Rev {diff.to_rev}</Link><p className="muted small">{diff.summary ?? "Open the comparison to inspect the change."}</p></li>)}</ul> : <p className="muted">No comparison has been recorded for this revision.</p>;
      }}</Async></section>
      <section className="drawings-context-section"><h3>Crew confirmations</h3><Async query={waiting} rows={2}>{(all) => {
        const items = confirmationsOf(all, sheet.id, revision.revision);
        return items.length ? <ul className="drawings-related" data-testid="drawings-confirmations">{items.map((item) => <li key={item.id}><strong>{item.on}</strong><span className={item.status === "done" ? "drawings-confirmed" : "drawings-pending"}>{item.status === "done" ? "Confirmed" : "Awaiting confirmation"}</span><p className="muted small">{item.what}</p></li>)}</ul> : <p className="muted">No confirmation request is recorded for this revision.</p>;
      }}</Async></section>
      <section className="drawings-context-section"><h3>Source</h3><p className="muted small">Received {receivedLabel(revision.received_at)}</p><Async query={events} rows={2}>{(all) => <Sources ids={revision.source_event_ids} events={all} />}</Async></section>
    </div>
  </>;
}

function Sources({ ids, events }: { ids: string[]; events: InboundEvent[] }) {
  if (ids.length === 0) return <p className="muted">Registered project document. No inbound message is linked.</p>;
  return <ul className="drawings-related" data-testid="drawings-sources">{ids.map((id) => {
    const event = events.find((item) => item.id === id);
    return <li key={id}>{event ? <details><summary>{event.sender} · {event.channel} · {id}</summary>{event.subject && <p><strong>{event.subject}</strong></p>}<p>{event.text || event.transcript || "Drawing received"}</p><time className="muted small" dateTime={event.received_at}>{receivedLabel(event.received_at)}</time></details> : <p>{id}: source message unavailable.</p>}</li>;
  })}</ul>;
}
