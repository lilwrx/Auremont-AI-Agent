import { useState } from "react";
import { api } from "../api/client";
import { ThumbsDownIcon, ThumbsUpIcon } from "./Icons";

type FeedbackType = "helpful" | "wrong";

// Feedback under each answer — lets Sale flag a bad reply, feeding the Admin loop.
// Two icons rather than the three labelled buttons this used to be: the row sat under
// every answer and the labels crowded the timestamp beside them. `FeedbackType` on the
// backend still has a third value (`incomplete`); it keeps working for rows already
// stored, it simply has no button of its own any more.
export function FeedbackButtons({ messageId }: { messageId: number }) {
  const [sent, setSent] = useState<FeedbackType | null>(null);
  const [busy, setBusy] = useState(false);

  const send = async (type: FeedbackType) => {
    if (busy || sent) return;
    setBusy(true);
    try {
      await api.post("/feedback", { message_id: messageId, type });
      setSent(type);
    } catch {
      // A failed feedback submission must not block the sales conversation.
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="feedback-row">
      <button
        className={`feedback-icon-btn ${sent === "helpful" ? "feedback-icon-btn--active" : ""}`}
        title="Câu trả lời hữu ích"
        aria-label="Câu trả lời hữu ích"
        disabled={busy || sent !== null}
        onClick={() => send("helpful")}
      >
        <ThumbsUpIcon size={14} />
      </button>
      <button
        className={`feedback-icon-btn ${sent === "wrong" ? "feedback-icon-btn--active" : ""}`}
        title="Câu trả lời sai hoặc thiếu"
        aria-label="Câu trả lời sai hoặc thiếu"
        disabled={busy || sent !== null}
        onClick={() => send("wrong")}
      >
        <ThumbsDownIcon size={14} />
      </button>
    </div>
  );
}
