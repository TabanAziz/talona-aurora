import { useEffect, useMemo, useRef, useState } from "react";
import { useQuery } from "../../api/useQuery";
import { Async } from "../../components/States";
import { loadGeometry, type Geometry } from "../../components/plan3d/geometry";
import { createViewer, webglAvailable, type Viewer } from "../../components/plan3d/scene";
import { ViewerControls } from "../../components/plan3d/ViewerControls";
import { splitFloors } from "../../components/plan3d/floors";

export function GeometryView({ url, label }: { url: string; label: string }) {
  const geometry = useQuery(() => loadGeometry(url), [url]);
  return <Async query={geometry} rows={6}>{(data) => <GeometryScene geometry={data} label={label} />}</Async>;
}
export function GeometryScene({ geometry, label, hostClass = "drawings-geometry" }: { geometry: Geometry; label: string; hostClass?: string }) {
  const host = useRef<HTMLDivElement>(null);
  const viewer = useRef<Viewer | null>(null);
  const [unavailable, setUnavailable] = useState(false);
  const [selected, setSelected] = useState("all");
  const [presentation, setPresentation] = useState<"building" | "exploded">("building");
  const floors = useMemo(() => splitFloors(geometry), [geometry]);
  const chosen = floors.find(floor => floor.level === selected);
  useEffect(() => {
    if (!host.current || !webglAvailable()) { setUnavailable(true); return; }
    try {
      setUnavailable(false);
      const shown = chosen ? { ...geometry, walls: chosen.walls, rooms: chosen.rooms, openings: chosen.openings } : geometry;
      viewer.current = createViewer(host.current, shown, shown, () => {}, chosen ? [chosen] : floors, chosen ? "exploded" : presentation);
      viewer.current.show("after");
      return () => { viewer.current?.dispose(); viewer.current = null; };
    } catch { setUnavailable(true); }
  }, [geometry, floors, chosen, presentation]);
  if (unavailable) return <p className="drawings-unavailable" role="status">3D is unavailable in this browser. Choose Drawing or PDF to read this revision.</p>;
  return <div className="plan3d-view"><div className="plan3d-model-heading"><p className="muted small">{geometry.rooms?.length ?? 0} rooms & areas · {geometry.walls.length} walls · {floors.length} {floors.length === 1 ? "floor" : "floors"}</p>{floors.length > 1 && <label className="drawings-revision-select">Floor<select value={chosen ? selected : "all"} onChange={event => setSelected(event.target.value)}><option value="all">All floors</option>{floors.map(floor => <option value={floor.level} key={floor.level}>Level {floor.level}</option>)}</select></label>}</div><div className={hostClass} ref={host} role="img" aria-label={`${label}. Drag to rotate, scroll or pinch to zoom, two fingers to pan.`} data-testid="drawings-geometry" /><div className="segmented" role="group" aria-label="Building presentation"><button type="button" aria-pressed={presentation === "building"} onClick={() => setPresentation("building")}>Building</button><button type="button" aria-pressed={presentation === "exploded"} onClick={() => setPresentation("exploded")}>Explore floors</button></div><ViewerControls viewer={viewer} /></div>;
}
