import type { RefObject } from "react";
import type { Viewer } from "./scene";
import "./viewer-controls.css";

export function ViewerControls({ viewer }: { viewer: RefObject<Viewer | null> }) {
  return <div className="plan3d-controls-area">
    <div className="plan3d-controls" role="group" aria-label="3D view controls" data-testid="plan3d-controls">
      <button type="button" onClick={() => viewer.current?.rotate(-Math.PI / 8)} data-testid="plan3d-rotate-left">↶ <span>Rotate left</span></button>
      <button type="button" onClick={() => viewer.current?.rotate(Math.PI / 8)} data-testid="plan3d-rotate-right">↷ <span>Rotate right</span></button>
      <button type="button" aria-label="Zoom in" title="Zoom in" onClick={() => viewer.current?.zoom(.8)} data-testid="plan3d-zoom-in">+</button>
      <button type="button" aria-label="Zoom out" title="Zoom out" onClick={() => viewer.current?.zoom(1.25)} data-testid="plan3d-zoom-out">−</button>
      <button type="button" onClick={() => viewer.current?.fit()} data-testid="plan3d-fit">Fit view</button>
      <button type="button" onClick={() => viewer.current?.reset()} data-testid="plan3d-reset">Reset view</button>
    </div>
    <ul className="plan3d-material-key" aria-label="Model materials"><li><i className="model-key-wall" />Exterior walls</li><li><i className="model-key-partition" />Partitions</li><li><i className="model-key-glass" />Windows</li></ul>
    <p className="plan3d-control-hint">Drag to rotate. Scroll or pinch to zoom. Two fingers or right-drag to pan. The grid is a viewing guide.</p>
  </div>;
}
