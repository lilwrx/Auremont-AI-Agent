import { useEffect, useState } from "react";
import { API_SERVER_URL } from "../../api/client";
import { ExternalLinkIcon, XIcon } from "../Icons";

interface SwaggerConsoleModalProps {
  open: boolean;
  onClose: () => void;
}

export function SwaggerConsoleModal({ open, onClose }: SwaggerConsoleModalProps) {
  const [mode, setMode] = useState<"docs" | "redoc">("docs");

  useEffect(() => {
    if (!open) return;
    const closeOnEscape = (event: KeyboardEvent) => event.key === "Escape" && onClose();
    window.addEventListener("keydown", closeOnEscape);
    return () => window.removeEventListener("keydown", closeOnEscape);
  }, [open, onClose]);

  if (!open) return null;
  const url = `${API_SERVER_URL}/${mode}`;

  return (
    <div className="admin-modal-backdrop" role="presentation" onMouseDown={onClose}>
      <section
        className="swagger-console"
        role="dialog"
        aria-modal="true"
        aria-label="FastAPI console"
        onMouseDown={(event) => event.stopPropagation()}
      >
        <header className="swagger-console-head">
          <div>
            <span className="admin-eyebrow">FastAPI embedded console</span>
            <h2>API Documentation</h2>
          </div>
          <div className="swagger-console-actions">
            <div className="admin-segmented">
              <button type="button" className={mode === "docs" ? "is-active" : ""} onClick={() => setMode("docs")}>Swagger</button>
              <button type="button" className={mode === "redoc" ? "is-active" : ""} onClick={() => setMode("redoc")}>ReDoc</button>
            </div>
            <a className="btn btn-sm btn-outline" href={url} target="_blank" rel="noreferrer">
              <ExternalLinkIcon size={14} /> Mở tab mới
            </a>
            <button className="admin-icon-button" type="button" onClick={onClose} aria-label="Đóng console">
              <XIcon size={19} />
            </button>
          </div>
        </header>
        <iframe className="swagger-frame" title={`FastAPI ${mode}`} src={url} />
      </section>
    </div>
  );
}
