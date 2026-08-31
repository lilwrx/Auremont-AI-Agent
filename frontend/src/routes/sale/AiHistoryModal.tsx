import { startTransition, useEffect, useState } from "react";
import { createPortal } from "react-dom";
import { saleLiveApi } from "../../api/saleLive";
import type { MessageResponse } from "../../types";
import { AnswerImageStrip } from "./AnswerImageStrip";
import { PropertyListingCarousel } from "../PropertyListingCarousel";
import { MessageContent } from "../../components/MessageContent";
import { CitationList } from "../../components/CitationList";
import { AuremontAvatar } from "../../components/AuremontAvatar";
import { parseServerDate } from "../../utils/datetime";
import { LoaderIcon, UserIcon, XIcon } from "../../components/Icons";

function formatTime(iso: string): string {
  const d = parseServerDate(iso);
  return Number.isNaN(d.getTime()) ? "" : d.toLocaleTimeString("vi-VN", { hour: "2-digit", minute: "2-digit" });
}

interface AiHistoryModalProps {
  sessionId: number;
  open: boolean;
  onClose: () => void;
}

/** Read-only look at the customer's AI-era conversation (backend/routers/sale_live.py::
 * get_ai_history) — a deliberate, explicit ask rather than the old behaviour of silently
 * merging it into the live transcript above. Fetched once per open, not polled: this is a
 * past conversation, not a live one. */
export function AiHistoryModal({ sessionId, open, onClose }: AiHistoryModalProps) {
  const [history, setHistory] = useState<{ sessionId: number; messages: MessageResponse[] } | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const hasLoadedHistory = history?.sessionId === sessionId;
  const messages = hasLoadedHistory ? history.messages : [];

  useEffect(() => {
    if (!open || hasLoadedHistory) return;
    let cancelled = false;
    setLoading(true);
    setError(null);
    saleLiveApi
      .getAiHistory(sessionId)
      .then((result) => {
        if (cancelled) return;
        // Keep the modal responsive while React prepares a potentially media-heavy history.
        startTransition(() => setHistory({ sessionId, messages: result }));
      })
      .catch(() => {
        if (!cancelled) setError("Không tải được hội thoại AI — vui lòng thử lại.");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [open, sessionId, hasLoadedHistory]);

  useEffect(() => {
    if (!open) return;
    const closeOnEscape = (event: KeyboardEvent) => event.key === "Escape" && onClose();
    window.addEventListener("keydown", closeOnEscape);
    return () => window.removeEventListener("keydown", closeOnEscape);
  }, [open, onClose]);

  if (!open) return null;

  return createPortal(
    <div className="admin-modal-backdrop ai-history-backdrop" role="presentation" onMouseDown={onClose}>
      <section
        className="chat-page ai-history-modal"
        role="dialog"
        aria-modal="true"
        aria-label="Hội thoại AI trước khi chuyển giao"
        onMouseDown={(event) => event.stopPropagation()}
      >
        <header className="chat-topbar">
          <div className="chat-topbar-info">
            <div>
              <div className="chat-topbar-name">Hội thoại với Auremont AI</div>
              <div className="chat-topbar-status">Chỉ xem — trước khi khách yêu cầu gặp chuyên viên</div>
            </div>
          </div>
          <button className="btn btn-ghost btn-sm" type="button" onClick={onClose} aria-label="Đóng">
            <XIcon size={16} />
          </button>
        </header>

        <div className="chat-messages">
          <div className="chat-messages-inner">
            {(loading || (!hasLoadedHistory && !error)) && (
              <div className="chat-empty-text">
                <LoaderIcon size={16} className="icon-spin" /> Đang tải hội thoại...
              </div>
            )}
            {error && <div className="alert alert-danger">{error}</div>}
            {hasLoadedHistory && !loading && !error && messages.length === 0 && (
              <div className="chat-empty-text">Khách chưa từng chat với Auremont AI trước đó.</div>
            )}
            {messages.map((m) => {
              const isCustomer = m.sender === "customer";
              return (
                <div
                  key={m.id}
                  className={`chat-message ai-history-message ${isCustomer ? "chat-message--bot" : "chat-message--user"}`}
                >
                  <div className={`chat-avatar ${isCustomer ? "chat-avatar--bot" : "chat-avatar--user"}`}>
                    {isCustomer ? <UserIcon size={16} /> : <AuremontAvatar size={20} emotion={m.emotion ?? "idle"} variant="face" />}
                  </div>
                  <div className="chat-bubble-wrap">
                    {!isCustomer && <span className="chat-sale-label">Auremont AI</span>}
                    <div className={`chat-bubble ${isCustomer ? "chat-bubble--bot" : "chat-bubble--user"}`}>
                      <MessageContent content={m.content} className="chat-bubble-text" />
                      {!isCustomer && m.citations && m.citations.length > 0 && (
                        <CitationList citations={m.citations} className="chat-citations" label="Nguồn" />
                      )}
                      {!isCustomer && m.images && m.images.length > 0 && <AnswerImageStrip images={m.images} />}
                      {!isCustomer && m.listings && m.listings.length > 0 && (
                        <PropertyListingCarousel listings={m.listings} />
                      )}
                    </div>
                    <span className="chat-timestamp">{formatTime(m.created_at)}</span>
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      </section>
    </div>,
    document.body,
  );
}
