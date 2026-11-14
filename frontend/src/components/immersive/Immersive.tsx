import { useEffect, useRef, useState, type ReactNode } from "react";
import "./immersive.css";

/** The same live canvas stays mounted when its dialog enters the browser's top layer. */
export function Immersive({ title, children, testId = "viewer" }: { title: string; children: ReactNode; testId?: string }) {
  const dialog = useRef<HTMLDialogElement>(null);
  const stage = useRef<HTMLDivElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const active = useRef(false);
  const native = useRef(false);
  const restore = useRef({ x: 0, y: 0, overflow: "" });
  const [expanded, setExpanded] = useState(false);

  function close() {
    if (!active.current) return;
    active.current = false;
    if (document.fullscreenElement === stage.current) void document.exitFullscreen().catch(() => {});
    dialog.current?.close();
    dialog.current?.setAttribute("open", "");
    document.body.style.overflow = restore.current.overflow;
    setExpanded(false);
    native.current = false;
    requestAnimationFrame(() => {
      trigger.current?.focus({ preventScroll: true });
      window.scrollTo(restore.current.x, restore.current.y);
    });
  }

  async function open() {
    if (!dialog.current || !stage.current || active.current) return;
    restore.current = { x: window.scrollX, y: window.scrollY, overflow: document.body.style.overflow };
    active.current = true;
    dialog.current.removeAttribute("open");
    dialog.current.showModal();
    document.body.style.overflow = "hidden";
    setExpanded(true);
    // Native fullscreen is optional. The modal top layer is the complete viewport fallback.
    try {
      if (stage.current.requestFullscreen && document.fullscreenEnabled) {
        await stage.current.requestFullscreen();
        if (!active.current) { if (document.fullscreenElement === stage.current) await document.exitFullscreen(); return; }
        native.current = document.fullscreenElement === stage.current;
      }
    } catch { /* The modal remains usable when browser policy rejects fullscreen. */ }
  }

  useEffect(() => { if (expanded) dialog.current?.querySelector<HTMLButtonElement>("button")?.focus({ preventScroll: true }); }, [expanded]);

  useEffect(() => {
    const changed = () => { if (native.current && !document.fullscreenElement) close(); };
    const escaped = (event: KeyboardEvent) => { if (active.current && event.key === "Escape") { event.preventDefault(); close(); } };
    document.addEventListener("fullscreenchange", changed);
    document.addEventListener("keydown", escaped);
    return () => {
      document.removeEventListener("fullscreenchange", changed);
      document.removeEventListener("keydown", escaped);
      if (active.current) document.body.style.overflow = restore.current.overflow;
    };
  }, []);

  return <dialog open ref={dialog} className={`immersive${expanded ? " immersive-expanded" : ""}`} aria-label={title}
    data-testid={`${testId}-immersive`} onCancel={(event) => { event.preventDefault(); close(); }}>
    <div className="immersive-frame" ref={stage}>
      <div className="immersive-toolbar">
        <span className="immersive-title">{title}</span>
        {expanded ? <button autoFocus type="button" className="button immersive-action" data-testid={`${testId}-close`} onClick={close}>Close full screen <span aria-hidden="true">×</span></button> :
          <button ref={trigger} type="button" className="button immersive-action" data-testid={`${testId}-fullscreen`} onClick={() => void open()}>Full screen <span aria-hidden="true">⛶</span></button>}
      </div>
      <div className="immersive-content">{children}</div>
    </div>
  </dialog>;
}
