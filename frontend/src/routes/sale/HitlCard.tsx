import { useState } from "react";
import { api } from "../../api/client";
import type { MessageResponse } from "../../types";
import { AlertIcon, CheckIcon, CopyIcon, LoaderIcon } from "../../components/Icons";
import { CitationList } from "../../components/CitationList";
import { MessageContent } from "../../components/MessageContent";
import { AnswerImageStrip } from "./AnswerImageStrip";
import { PropertyListingCarousel } from "../PropertyListingCarousel";

interface HitlCardProps {
  message: MessageResponse;
  onConfirmed: () => void;
}

// Commitment-risk warning card — confirmation is mandatory before send/copy.
export function HitlCard({ message, onConfirmed }: HitlCardProps) {
  const [confirming, setConfirming] = useState(false);
  // Seeded from the server: confirmation lives in the audit trail, so reopening a
  // conversation must show an already-approved answer as approved.
  const [confirmed, setConfirmed] = useState(message.hitl_confirmed);
  const [copied, setCopied] = useState(false);

  const confirm = async () => {
    setConfirming(true);
    try {
      await api.post(`/hitl/${message.id}/confirm`, { confirmed_content: message.content });
      // Only allow copying the content to send to the customer after the Sale
      // has read and confirmed it.
      try {
        await navigator.clipboard.writeText(message.content);
        setCopied(true);
      } catch {
        // Clipboard access blocked (non-HTTPS context / permission not granted) —
        // still treat the confirmation as successful.
      }
      setConfirmed(true);
      onConfirmed();
    } finally {
      setConfirming(false);
    }
  };

  return (
    <div className="hitl-card">
      <div className="hitl-head">
        <AlertIcon size={16} />
        <span className="hitl-title">Cảnh báo thông tin cam kết</span>

        {/* Confirmation stays mandatory (spec §5.2d) — this is the same gate as before,
            just as a corner icon instead of a full-width button. Copying still only
            happens through it, never straight from the card body. */}
        <button
          onClick={confirm}
          disabled={confirming || confirmed}
          className={`hitl-copy-btn ${confirmed ? "hitl-copy-btn--done" : ""}`}
          type="button"
          title={confirmed ? "Đã xác nhận & copy" : "Xác nhận & copy gửi khách"}
          aria-label={confirmed ? "Đã xác nhận và copy" : "Xác nhận và copy gửi khách"}
        >
          {confirming ? (
            <LoaderIcon size={15} className="icon-spin" />
          ) : confirmed ? (
            <CheckIcon size={15} />
          ) : (
            <CopyIcon size={15} />
          )}
        </button>
      </div>

      <div className="hitl-body">
        <MessageContent content={message.content} />
      </div>

      {message.citations && message.citations.length > 0 && (
        <CitationList citations={message.citations} className="hitl-sources" label="Tài liệu" />
      )}

      {message.images && message.images.length > 0 && <AnswerImageStrip images={message.images} />}
      {message.listings && message.listings.length > 0 && (
        <PropertyListingCarousel listings={message.listings} />
      )}

      {/* Only the confirmed state gets a line of its own — before confirming, the copy
          icon in the header is the whole affordance and needs no caption. */}
      {confirmed && (
        <div className="hitl-actions">
          <span className="hitl-confirmed">
            <CheckIcon size={14} />
            {copied ? "Đã xác nhận & copy vào clipboard" : "Đã xác nhận"}
          </span>
        </div>
      )}
    </div>
  );
}
