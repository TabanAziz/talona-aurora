import type { CSSProperties } from "react";
import type { ProjectBrand } from "../../pages/projects/api";
import "./project-mark.css";

export function ProjectMark({ brand, name }: { brand?: ProjectBrand | null; name: string }) {
  const style = brand ? { "--logo-primary": brand.primary, "--logo-accent": brand.accent, "--logo-background": brand.background } as CSSProperties : undefined;
  return <div className="workspace-project-mark project-logo" style={style} role="img" aria-label={brand ? `${name}: ${brand.description}` : `${name} project`} title={brand?.description} data-testid="project-logo">
    <svg viewBox={brand ? "0 0 64 64" : "0 0 40 40"} aria-hidden="true">
      {brand ? brand.paths.map((path, index) => <path key={`${index}-${path.d}`} className="project-logo-path" d={path.d} pathLength={1}
        stroke={path.color === "accent" ? brand.accent : brand.primary} fill={path.filled ? path.color === "accent" ? brand.accent : brand.primary : "none"}
        strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" data-filled={path.filled} style={{ "--logo-path-order": index } as CSSProperties} />)
        : <path d="M6 31V13l14-7 14 7v18M6 15l14 7 14-7M20 22v12M13 19v10M27 19v10" />}
    </svg>
  </div>;
}
