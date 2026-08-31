import { useState } from "react";
import type { Citation } from "../types";
import { DocumentIcon, ExternalLinkIcon, XIcon } from "./Icons";
import { fetchDocumentViewUrl } from "../api/projects";

interface Props {
  citations: Citation[];
  /** Wrapper class — the chat bubble and the HITL card lay this row out differently. */
  className: string;
  label: string;
}

const PDF_TITLE = /\.pdf$/i;

// #page=N is a PDF viewer convention (Chrome/Firefox/Edge's built-in viewer, and the
// <iframe> preview below, both jump straight there) — a plain URL fragment, so it rides
// along on the signed link without touching its query-string signature. `&zoom=100,0,Y`
// goes a step further and scrolls to a specific vertical spot ON that page (confirmed
// against this project's own viewer — see chunking_service.py for where Y comes from):
// without it, a page with several unrelated sections only lands at the top of the page,
// which in the compact preview panel below is often nowhere near the cited paragraph.
function withPageAnchor(url: string, citation: Citation): string {
  if (!citation.page || !PDF_TITLE.test(citation.title)) return url;
  const target = `${url}#page=${citation.page}`;
  return citation.y_position != null ? `${target}&zoom=100,0,${Math.round(citation.y_position)}` : target;
}

// Source chips under an answer: one per file. Sale/Admin only — a citation click-through
// to the raw file is a "verify what I'm about to tell the customer" tool for a Sale, not
// something a customer sees (CustomerChatPage renders no citations at all).
//
// The de-duplication is repeated here even though the backend already collapses
// citations per file, because messages stored before that change still hold one entry
// per chunk — five rows of the same PDF name — and reopening an old conversation
// renders whatever was saved. Doing it at render time fixes the history too.
//
// Keyed on document_id rather than title, matching build_citations: those legacy per-chunk
// entries all repeat the same document_id, so this still collapses them, while two
// genuinely different files that share a name both survive instead of one being dropped
// and the other left standing in for it.
export function CitationList({ citations, className, label }: Props) {
  const [loadingId, setLoadingId] = useState<number | null>(null);
  const [preview, setPreview] = useState<{ title: string; url: string } | null>(null);

  const seen = new Set<number>();
  const unique = citations.filter((c) => {
    if (seen.has(c.document_id)) return false;
    seen.add(c.document_id);
    return true;
  });

  if (unique.length === 0) return null;

  const openDocument = async (citation: Citation) => {
    if (loadingId !== null) return;
    setLoadingId(citation.document_id);
    try {
      const url = await fetchDocumentViewUrl(citation.document_id);
      const target = withPageAnchor(url, citation);
      // A PDF renders straight into the page via <iframe> below — no reason to leave the
      // chat for it. A .docx (or anything else) has no in-browser renderer at all, native
      // or embedded, so that one still has to go to a new tab (where the browser either
      // shows or downloads it, whichever it does for that file type).
      if (PDF_TITLE.test(citation.title)) {
        setPreview({ title: citation.title, url: target });
      } else {
        window.open(target, "_blank", "noopener,noreferrer");
      }
    } catch {
      // The signed link can fail to generate (file moved, storage hiccup) — worth a
      // console trace for support, not worth a chat bubble interrupting the answer.
      console.error("Không mở được tài liệu.");
    } finally {
      setLoadingId(null);
    }
  };

  return (
    <div className={className}>
      <span className="chat-citations-label">{label}</span>
      {unique.map((c) => (
        <button
          key={c.document_id}
          type="button"
          className="chat-citation"
          onClick={() => openDocument(c)}
          disabled={loadingId === c.document_id}
        >
          <DocumentIcon size={12} />
          {c.title}
          {/* Only present when another chip carries the same file name — without it the
              Sale sees two identical chips and cannot tell which source is which. */}
          {c.qualifier && <span className="chat-citation-qualifier">{c.qualifier}</span>}
        </button>
      ))}

      {preview && (
        <div className="doc-preview-backdrop" onMouseDown={() => setPreview(null)}>
          <div className="doc-preview-panel" onMouseDown={(e) => e.stopPropagation()}>
            <div className="doc-preview-header">
              <span className="doc-preview-title">{preview.title}</span>
              <a
                className="doc-preview-action"
                href={preview.url}
                target="_blank"
                rel="noopener noreferrer"
                aria-label="Mở trong tab mới"
              >
                <ExternalLinkIcon size={15} />
              </a>
              <button
                type="button"
                className="doc-preview-action"
                onClick={() => setPreview(null)}
                aria-label="Đóng"
              >
                <XIcon size={16} />
              </button>
            </div>
            <iframe className="doc-preview-iframe" src={preview.url} title={preview.title} />
          </div>
        </div>
      )}
    </div>
  );
}
