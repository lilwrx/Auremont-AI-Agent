import { useCallback, useEffect, useRef, useState, type FormEvent, type KeyboardEvent } from "react";
import { useLocation, useParams } from "react-router-dom";
import { api } from "../../api/client";
import type { MessageResponse } from "../../types";
import { HitlCard } from "./HitlCard";
import { BotIcon, LoaderIcon, SendIcon, TrashIcon, UserIcon } from "../../components/Icons";
import { FeedbackButtons } from "../../components/FeedbackButtons";
import { CitationList } from "../../components/CitationList";
import { AuremontAvatar } from "../../components/AuremontAvatar";
import { MessageContent } from "../../components/MessageContent";
import { AnswerImageStrip } from "./AnswerImageStrip";
import { PropertyListingCarousel } from "../PropertyListingCarousel";
import { ChatSuggestions } from "./ChatSuggestions";
import { parseServerDate } from "../../utils/datetime";
import { useCursorTrail } from "../../hooks/useCursorTrail";

function formatTime(iso: string): string {
  const d = parseServerDate(iso);
  return Number.isNaN(d.getTime()) ? "" : d.toLocaleTimeString("vi-VN", { hour: "2-digit", minute: "2-digit" });
}

interface Props {
  /** Called when the session list may have changed (e.g. after clearing history). */
  onSessionsChange?: () => void;
}

// Agent Pipeline: text input -> answer + citations, or a HITL card.
export function ChatWindow({ onSessionsChange }: Props = {}) {
  const { sessionId } = useParams<{ sessionId: string }>();
  const location = useLocation();
  const [messages, setMessages] = useState<MessageResponse[]>([]);
  const [input, setInput] = useState(() => (location.state as { prefill?: string } | null)?.prefill ?? "");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const scrollRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const { layerRef: particleLayerRef, handleMouseMove: handleChatMouseMove } = useCursorTrail();

  useEffect(() => {
    if (!sessionId) return;
    setError(null);
    api
      .get<MessageResponse[]>(`/sale/sessions/${sessionId}/messages`)
      .then(setMessages)
      .catch(() => setError("Không tải được lịch sử phiên tư vấn."));
  }, [sessionId]);

  // Always scroll to the latest message.
  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [messages, loading]);

  // Auto-grow the textarea with content, capped at 160px.
  useEffect(() => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 160)}px`;
  }, [input]);

  // TODO: add voice input (STT provider TBD).

  const sendMessage = useCallback(async () => {
    if (!sessionId || !input.trim() || loading) return;
    const content = input.trim();
    // First message in the session -> the backend auto-names the session from this
    // content, so notify SalePage to reload the sidebar so the new name shows up
    // immediately.
    const isFirstMessage = messages.length === 0;

    // Optimistic UI: the server only returns the agent's reply (response_model=
    // MessageResponse, not a list), so the Sale's own message must be appended
    // locally right away — otherwise it would appear to vanish until the AI
    // finishes responding.
    const optimisticUser: MessageResponse = {
      id: -Date.now(),
      session_id: Number(sessionId) || null,
      sender: "sale",
      content,
      citations: null,
      images: null,
      verifier_score: null,
      requires_hitl: false,
      hitl_confirmed: false,
      emotion: null,
      quick_replies: null,
      listings: null,
      suggested_questions: null,
      created_at: new Date().toISOString(),
    };
    setMessages((prev) => [...prev, optimisticUser]);
    setInput("");
    setLoading(true);
    setError(null);
    try {
      const reply = await api.post<MessageResponse>(`/sale/sessions/${sessionId}/messages`, { content });
      setMessages((prev) => [...prev, reply]);
      if (isFirstMessage) onSessionsChange?.();
    } catch {
      setError("Tạm thời không tra được tồn kho — vui lòng thử lại.");
    } finally {
      setLoading(false);
    }
  }, [sessionId, input, loading, messages.length, onSessionsChange]);

  // HitlCard keeps its own local "confirmed" state, but if the messages list
  // re-renders (e.g. switching sessions and back) while requires_hitl is still
  // true in parent state, the card would show the confirm button again even
  // though it was already confirmed — so clear the flag here once confirmed.
  const handleHitlConfirmed = useCallback((messageId: number) => {
    setMessages((prev) => prev.map((m) => (m.id === messageId ? { ...m, requires_hitl: false } : m)));
  }, []);

  const handleSubmit = (e: FormEvent) => {
    e.preventDefault();
    sendMessage();
  };

  const handleKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  };

  const clearChat = async () => {
    if (!sessionId) return;
    await api.delete(`/sale/sessions/${sessionId}/messages`).catch(() => {});
    setMessages([]);
    onSessionsChange?.();
  };

  const ready = Boolean(input.trim()) && !loading;

  const pickSuggestion = (question: string) => {
    setInput(question);
    textareaRef.current?.focus();
  };

  return (
    <div className="chat-page" onMouseMove={handleChatMouseMove}>
      <div className="cursor-particle-layer" ref={particleLayerRef} aria-hidden="true" />
      <header className="chat-topbar">
        <div className="chat-topbar-info">
          <div className="chat-topbar-icon">
            <BotIcon size={20} />
          </div>
          <div>
            <div className="chat-topbar-name">Trợ lý tư vấn Auremont</div>
            <div className="chat-topbar-status">
              <span className="chat-status-dot" />
              Sẵn sàng tra cứu tài liệu &amp; tồn kho
            </div>
          </div>
        </div>

        <button className="chat-clear-btn" onClick={clearChat} type="button">
          <TrashIcon size={15} />
          Xóa chat
        </button>
      </header>

      <div className="chat-messages" ref={scrollRef}>
        <div className="chat-messages-inner">
          {messages.length === 0 && !loading && (
            <div className="chat-landing">
              <AuremontAvatar size={64} emotion="greeting" className="chat-landing-mascot" />
              <h2 className="chat-empty-title">Hỏi Auremont bằng câu nói của bạn</h2>
              <p className="chat-empty-text">
                Ví dụ "bảng giá căn 2 ngủ The Zurich" hoặc "mặt bằng tòa BE1 The Beverly". Auremont tra tài liệu đang
                có và trả lời kèm trích nguồn.
              </p>
              <ChatSuggestions onPick={pickSuggestion} />
            </div>
          )}

          {messages.map((m, index) => {
            if (m.requires_hitl) {
              // A risky answer still stays in the feedback loop like any other message.
              return (
                <div key={m.id} className="chat-hitl-row">
                  <HitlCard message={m} onConfirmed={() => handleHitlConfirmed(m.id)} />
                  <div className="chat-hitl-meta">
                    <span className="chat-timestamp">{formatTime(m.created_at)}</span>
                    <FeedbackButtons messageId={m.id} />
                  </div>
                </div>
              );
            }

            const isUser = m.sender === "sale";
            // Only the newest answer's follow-ups are still worth offering — an older
            // message's suggestions have already been overtaken by the conversation.
            const showSuggestedQuestions =
              !isUser && index === messages.length - 1 && !loading && !!m.suggested_questions?.length;
            return (
              <div key={m.id} className={`chat-message ${isUser ? "chat-message--user" : "chat-message--bot"}`}>
                <div className={`chat-avatar ${isUser ? "chat-avatar--user" : "chat-avatar--bot"}`}>
                  {isUser ? <UserIcon size={16} /> : <AuremontAvatar size={22} emotion={m.emotion ?? "idle"} variant="face" />}
                </div>

                <div className="chat-bubble-wrap">
                  <div className={`chat-bubble ${isUser ? "chat-bubble--user" : "chat-bubble--bot"}`}>
                    <MessageContent content={m.content} className="chat-bubble-text" />

                    {!isUser && m.citations && m.citations.length > 0 && (
                      <CitationList citations={m.citations} className="chat-citations" label="Nguồn" />
                    )}

                    {!isUser && m.images && m.images.length > 0 && <AnswerImageStrip images={m.images} />}
                    {!isUser && m.listings && m.listings.length > 0 && (
                      <PropertyListingCarousel listings={m.listings} />
                    )}
                  </div>
                  {showSuggestedQuestions && (
                    <div className="chat-suggested-questions">
                      {m.suggested_questions?.map((question) => (
                        <button
                          key={question}
                          type="button"
                          className="chat-suggested-question"
                          // Fills the input rather than sending outright, matching
                          // ChatSuggestions' empty-state card: a Sale is mid-consultation
                          // and usually wants to adjust the wording before asking.
                          onClick={() => pickSuggestion(question)}
                        >
                          {question}
                        </button>
                      ))}
                    </div>
                  )}
                  <span className="chat-timestamp">{formatTime(m.created_at)}</span>
                  {!isUser && <FeedbackButtons messageId={m.id} />}
                </div>
              </div>
            );
          })}

          {loading && (
            <div className="chat-thinking">
              <div className="chat-avatar chat-avatar--bot">
                <AuremontAvatar size={22} emotion="thinking" variant="face" />
              </div>
              <div className="thinking-bubble">
                <div className="thinking-dots">
                  <span className="thinking-dot" />
                  <span className="thinking-dot" />
                  <span className="thinking-dot" />
                </div>
                <span className="thinking-label">Đang đọc tài liệu bảng giá...</span>
              </div>
            </div>
          )}

          {error && <div className="alert alert-danger">{error}</div>}
        </div>
      </div>

      <div className="chat-input-wrapper">
        <form className="chat-input-area" onSubmit={handleSubmit}>
          <div className={`chat-input-box ${input.trim()? "chat-input-box--active" : ""}`}>
            <textarea
              ref={textareaRef}
              className="chat-input"
              placeholder="Nhập câu hỏi tư vấn..."
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={handleKeyDown}
              disabled={loading}
              rows={1}
            />
            <button type="submit" className={`chat-send-btn ${ready ? "chat-send-btn--ready" : ""}`} disabled={!ready} aria-label="Gửi">
              {loading ? <LoaderIcon size={18} className="icon-spin" /> : <SendIcon size={18} />}
            </button>
          </div>
          <p className="chat-input-hint">Enter để gửi · Shift + Enter để xuống dòng</p>
        </form>
      </div>
    </div>
  );
}
