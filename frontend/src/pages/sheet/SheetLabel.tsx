import type { CSSProperties } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../../api/client";
import { useQuery } from "../../api/useQuery";
import { QUIET_ZONE, qrCode } from "./qr";
import { labelUrl } from "./labelUrl.js";
import "./sheet.css";

function statusUrl(sheet: string, revision: string) {
  return labelUrl(sheet, revision, import.meta.env.VITE_PUBLIC_URL, window.location.origin);
}

export function SheetLabel() {
  const { sheet = "", revision = "" } = useParams();
  const project = useQuery(api.project, []);
  const url = statusUrl(sheet, revision);
  const code = qrCode(url);

  return (
    <article className="sheet-label" data-testid="sheet-label">
      <header className="sheet-label-head">
        <span className="sheet-label-brand">Aurora</span>
        <span className="muted small">{project.data ? project.data.name : "Project"}</span>
      </header>

      <p className="sheet-label-kicker">Drawing sheet</p>
      <h1 className="sheet-label-id">{sheet}</h1>
      <p className="sheet-label-rev">Rev {revision}</p>

      <div
        className="sheet-label-qr"
        data-testid="sheet-qr"
        data-qr-value={url}
        data-qr-modules={code.modules}
        data-qr-size={code.size}
        data-quiet-zone={QUIET_ZONE}
        style={{ "--qr-size": code.size } as CSSProperties}
      >
        <svg
          viewBox={`0 0 ${code.size} ${code.size}`}
          shapeRendering="crispEdges"
          role="img"
          aria-label={`QR code for the status page of ${sheet} Rev ${revision}`}
        >
          <rect className="sheet-qr-paper" width={code.size} height={code.size} />
          <path className="sheet-qr-ink" d={code.path} />
        </svg>
      </div>

      <p className="sheet-label-scan">Scan before you build</p>
      <p className="sheet-label-url num">{url}</p>
      <p className="sheet-label-open">
        <Link
          className="button"
          to={`/sheet/${encodeURIComponent(sheet)}/${encodeURIComponent(revision)}`}
          data-testid="sheet-open-status"
        >
          Open the status page
        </Link>
      </p>
      <p className="sheet-label-note muted small">
        The status page names the newest revision on record. A red band means this revision is superseded.
      </p>
      <button type="button" className="button sheet-label-print" onClick={() => window.print()}>
        Print this label
      </button>
    </article>
  );
}
