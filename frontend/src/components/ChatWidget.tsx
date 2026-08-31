import { useEffect, useRef, useState, type FormEvent, type KeyboardEvent } from "react";
import { Link, useLocation } from "react-router-dom";
import { api } from "../api/client";
import { customerApi } from "../api/customerChat";
import { clearVisitorSession, getVisitorSession, setVisitorSession } from "../hooks/useVisitorToken";
import { useAuth } from "../hooks/useAuth";
import type {
  AnonymousSessionResponse,
  ChatSessionResponse,
  CustomerAskResponse,
  CustomerChatSessionResponse,
  CustomerGate,
  MessageResponse,
  SessionStatus,
} from "../types";
import { AlertTriangleIcon, ArrowRightIcon, LoaderIcon, SendIcon, TrashIcon, UsersIcon, XIcon } from "./Icons";
import { AuremontAvatar } from "./AuremontAvatar";
import { RegisterGateModal } from "./RegisterGateModal";
import { MessageContent } from "./MessageContent";

const SUGGESTIONS = ["Còn căn 2PN dưới 3 tỷ không?", "Biệt thự song lập giá bao nhiêu?"];
const PUBLIC_SUGGESTIONS = ["Dự án ở vị trí nào?", "Có những tiện ích gì?"];

// Floating chat launcher shown app-wide (Sale, Customer, and anonymous visitors alike —
// only Admin has no use for it). Branches its API calls by role: Sale keeps the existing
// /sale/sessions flow (with the "ask for the customer's name" step, since a Sale's session
// list is organised by which customer it's for); Customer/anonymous go through
// /customer/sessions instead and can hit the soft-paywall gate mid-conversation.
export function ChatWidget() {
  const { isAuthenticated, role } = useAuth();
  const isSale = role === "sale";

  const [open, setOpen] = useState(false);
  const [sessionId, setSessionId] = useState<number | null>(null);
  const [messages, setMessages] = useState<MessageResponse[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [clearingHistory, setClearingHistory] = useState(false);
  const [gate, setGate] = useState<CustomerGate | null>(null);
  // Customer/anonymous only — once a Sale is involved, the widget stops trying to keep up
  // live (that experience lives in the full CustomerChatPage, which polls) and just points
  // there instead. Sale's own /sale/sessions flow never sets this.
  const [sessionStatus, setSessionStatus] = useState<SessionStatus>("bot_handling");
  // Sale-only: ask for the customer's name at the moment they send their first message
  // (not right when the panel opens), so the Sale-side session list shows the customer's
  // name instead of defaulting to the first question's text as the title. pendingMessage
  // holds the in-flight question and is actually sent once this step is resolved.
  const [pendingMessage, setPendingMessage] = useState<string | null>(null);
  const [askedName, setAskedName] = useState(false);
  const [customerName, setCustomerName] = useState("");
  const location = useLocation();
  const rootRef = useRef<HTMLDivElement>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const sessionCreationRef = useRef<Promise<number> | null>(null);

  // Customer and anonymous widget traffic must join the exact same durable conversation
  // as the full /chat page. Previously the widget started with sessionId=null on every
  // mount and created a second anonymous session even when localStorage already held one.
  useEffect(() => {
    if (isSale) return;
    let cancelled = false;

    const resume = async () => {
      try {
        let id: number | null = null;
        if (isAuthenticated) {
          const sessions = await customerApi.get<CustomerChatSessionResponse[]>("/customer/sessions");
          id = sessions[0]?.id ?? null;
        } else {
          id = getVisitorSession()?.sessionId ?? null;
        }
        if (!id || cancelled) return;

        const [detail, history] = await Promise.all([
          customerApi.get<CustomerChatSessionResponse>(`/customer/sessions/${id}`),
          customerApi.get<MessageResponse[]>(`/customer/sessions/${id}/messages`),
        ]);
        if (cancelled) return;
        setSessionId(id);
        setSessionStatus(detail.status);
        // The full page owns the complete transcript. The compact widget only needs the
        // recent visual tail; the backend still passes the canonical session history to AI.
        setMessages(history.slice(-20));
      } catch {
        if (!isAuthenticated) clearVisitorSession();
      }
    };

    resume();
    return () => {
      cancelled = true;
    };
  }, [isAuthenticated, isSale]);

  // The widget never unmounts on page change (App.tsx only toggles it via
  // showChatWidget), so a panel left open on one page would stay open when
  // navigating to another unless closed explicitly. Closing the panel is fine,
  // but the session state (sessionId/messages) is preserved so reopening the
  // widget doesn't lose an in-progress conversation.
  useEffect(() => {
    setOpen(false);
  }, [location.pathname]);

  // Clicking outside the panel closes it, matching every other popover/dropdown in the app.
  useEffect(() => {
    if (!open) return;
    const handleClickOutside = (e: MouseEvent) => {
      if (rootRef.current && !rootRef.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, [open]);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [messages, loading]);

  const ensureSession = async (): Promise<number> => {
    if (sessionId) return sessionId;
    if (sessionCreationRef.current) return sessionCreationRef.current;

    if (isSale) {
      const session = await api.post<ChatSessionResponse>("/sale/sessions", {
        customer_name: customerName.trim() || undefined,
      });
      setSessionId(session.id);
      return session.id;
    }

    // The resume effect may still be fetching history when the visitor sends immediately
    // after opening the widget. Reuse the cached ownership pair synchronously instead of
    // racing that fetch with a second anonymous-session creation.
    if (!isAuthenticated) {
      const visitor = getVisitorSession();
      if (visitor) {
        setSessionId(visitor.sessionId);
        return visitor.sessionId;
      }
    }

    const creation = (async () => {
      if (isAuthenticated) {
        const session = await customerApi.post<CustomerChatSessionResponse>("/customer/sessions", {});
        setSessionId(session.id);
        setSessionStatus(session.status);
        return session.id;
      }

      const anon = await customerApi.post<AnonymousSessionResponse>("/customer/sessions/anonymous");
      setVisitorSession(anon.session_id, anon.visitor_token);
      setSessionId(anon.session_id);
      return anon.session_id;
    })();
    sessionCreationRef.current = creation;
    try {
      return await creation;
    } finally {
      sessionCreationRef.current = null;
    }
  };

  const handleAuthenticated = async (canonicalSessionId?: number) => {
    setGate(null);
    if (!canonicalSessionId) return;
    setSessionId(canonicalSessionId);
    try {
      const [detail, history] = await Promise.all([
        customerApi.get<CustomerChatSessionResponse>(`/customer/sessions/${canonicalSessionId}`),
        customerApi.get<MessageResponse[]>(`/customer/sessions/${canonicalSessionId}/messages`),
      ]);
      setSessionStatus(detail.status);
      setMessages(history.slice(-20));
    } catch {
      // Auth succeeded; the normal resume effect can retry if this immediate fetch fails.
    }
  };

  const sendMessage = async (content: string, skipNameGate = false) => {
    const trimmed = content.trim();
    if (!trimmed || loading) return;

    // First send (no session yet, name gate not passed): hold the question and
    // show the name form instead of sending immediately. Sale only — the
    // customer/anonymous flow has no equivalent step.
    if (isSale && !sessionId && !askedName && !skipNameGate) {
      setPendingMessage(trimmed);
      setInput("");
      return;
    }

    setInput("");
    setLoading(true);

    const optimisticUser: MessageResponse = {
      id: -Date.now(),
      session_id: sessionId,
      sender: isSale ? "sale" : "customer",
      content: trimmed,
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

    try {
      const id = await ensureSession();
      if (isSale) {
        const reply = await api.post<MessageResponse>(`/sale/sessions/${id}/messages`, { content: trimmed });
        setMessages((prev) => [...prev, reply]);
      } else {
        // `null` once a Sale has taken over — the AI stays silent; the widget doesn't
        // poll for the Sale's reply itself, it just points to the full chat page below.
        const reply = await customerApi.post<CustomerAskResponse | null>(`/customer/sessions/${id}/messages`, {
          content: trimmed,
        });
        if (reply) {
          setMessages((prev) => [...prev, reply]);
          setSessionStatus(reply.status);
          if (reply.gate) setGate(reply.gate);
        }
      }
    } catch {
      setMessages((prev) => [
        ...prev,
        {
          id: -Date.now() - 1,
          session_id: sessionId,
          sender: "agent",
          content: "Tạm thời không gửi được câu hỏi — vui lòng thử lại.",
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
        },
      ]);
    } finally {
      setLoading(false);
    }
  };

  const confirmName = (e?: FormEvent) => {
    e?.preventDefault();
    setAskedName(true);
    const msg = pendingMessage;
    setPendingMessage(null);
    if (msg) sendMessage(msg, true);
  };

  const handleSubmit = (e: FormEvent) => {
    e.preventDefault();
    sendMessage(input);
  };

  const handleKeyDown = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter") {
      e.preventDefault();
      sendMessage(input);
    }
  };

  const clearCustomerHistory = async () => {
    if (isSale || !sessionId || clearingHistory || messages.length === 0) return;
    const confirmed = window.confirm(
      "Xóa toàn bộ lịch sử trò chuyện? Thông tin Auremont đã ghi nhớ từ cuộc trò chuyện này cũng sẽ bị xóa.",
    );
    if (!confirmed) return;

    setClearingHistory(true);
    try {
      await customerApi.delete<void>(`/customer/sessions/${sessionId}/messages`);
      setMessages([]);
      setInput("");
      setGate(null);
      setSessionStatus("bot_handling");
    } catch {
      window.alert("Tạm thời chưa xóa được lịch sử trò chuyện — vui lòng thử lại.");
    } finally {
      setClearingHistory(false);
    }
  };

  const fullChatHref = isSale && sessionId ? `/chat/sessions/${sessionId}` : "/chat";
  const suggestions = isSale ? SUGGESTIONS : PUBLIC_SUGGESTIONS;
  const visitor = getVisitorSession();

  return (
    <div className="chat-widget" ref={rootRef}>
      {open && (
        <div className="chat-widget-panel">
          <div className="chat-widget-head">
            <AuremontAvatar size={34} emotion={loading ? "thinking" : "idle"} variant="face" />
            <div>
              <p className="chat-widget-title">Trợ lý AI</p>
              <p className="chat-widget-sub">Hỏi nhanh về giá, pháp lý hoặc tồn kho</p>
            </div>
            <div className="chat-widget-head-actions">
              {!isSale && sessionId && messages.length > 0 && (
                <button
                  className="chat-widget-clear"
                  type="button"
                  onClick={clearCustomerHistory}
                  disabled={clearingHistory || loading}
                  aria-label="Xóa lịch sử trò chuyện"
                  title="Xóa lịch sử trò chuyện"
                >
                  {clearingHistory ? <LoaderIcon size={15} className="icon-spin" /> : <TrashIcon size={15} />}
                </button>
              )}
              <button className="chat-widget-close" type="button" onClick={() => setOpen(false)} aria-label="Đóng">
                <XIcon size={16} />
              </button>
            </div>
          </div>

          {pendingMessage !== null ? (
            <form className="chat-widget-name-form" onSubmit={confirmName}>
              <p className="chat-widget-name-hint">Cho Auremont biết tên bạn để lưu lại cuộc trò chuyện này nhé.</p>
              <input
                autoFocus
                type="text"
                placeholder="Tên của bạn (có thể bỏ trống)"
                value={customerName}
                onChange={(e) => setCustomerName(e.target.value)}
              />
              <div className="chat-widget-name-actions">
                <button type="submit" className="btn btn-primary chat-widget-name-submit">
                  Gửi câu hỏi
                </button>
                <button type="button" className="chat-widget-name-skip" onClick={() => confirmName()}>
                  Bỏ qua
                </button>
              </div>
            </form>
          ) : !isSale && sessionStatus !== "bot_handling" ? (
            <div className="chat-widget-handoff-hint">
              <UsersIcon size={22} />
              <p>
                {sessionStatus === "waiting_sale"
                  ? "Đang kết nối chuyên viên tư vấn cho bạn."
                  : "Bạn đang chat trực tiếp với chuyên viên tư vấn."}
              </p>
              <Link to={fullChatHref} className="btn btn-primary chat-widget-name-submit">
                Mở trợ lý đầy đủ để tiếp tục
              </Link>
            </div>
          ) : (
            <>
              {messages.length === 0 ? (
                <div className="chat-widget-suggestions">
                  {suggestions.map((s) => (
                    <button key={s} type="button" className="chat-widget-suggestion" onClick={() => sendMessage(s)}>
                      &ldquo;{s}&rdquo;
                    </button>
                  ))}
                </div>
              ) : (
                <div className="chat-widget-messages" ref={scrollRef}>
                  {messages.map((m, index) => {
                    const isLastMessage = index === messages.length - 1;
                    const showQuickReplies =
                      !isSale && isLastMessage && sessionStatus === "bot_handling" && !!m.quick_replies?.length;
                    // Follow-ups are offered on both surfaces, but never alongside quick
                    // replies: those answer the question the assistant just asked, and
                    // showing both at once asks the reader to choose between answering and
                    // changing the subject in one undifferentiated row of pills.
                    const showSuggestedQuestions =
                      isLastMessage &&
                      sessionStatus === "bot_handling" &&
                      !showQuickReplies &&
                      !!m.suggested_questions?.length;

                    // A price/commitment answer must not be readable — let alone copyable —
                    // from this widget: the mandatory confirm-and-copy gate lives only in the
                    // full chat window (routes/sale/ChatWindow.tsx). Rendering `m.content`
                    // here would hand the Sale the exact figures with no confirmation step,
                    // defeating the gate the backend flagged this message for.
                    if (m.requires_hitl) {
                      return (
                        <div key={m.id} className="chat-widget-hitl">
                          <AlertTriangleIcon size={20} />
                          <p>Câu trả lời này có thông tin giá/cam kết, cần xác nhận trước khi gửi khách.</p>
                          <Link to={fullChatHref} className="btn btn-primary chat-widget-name-submit">
                            Mở chat đầy đủ để xác nhận
                          </Link>
                        </div>
                      );
                    }

                    return (
                      <div key={m.id}>
                        <div
                          className={`chat-widget-msg ${m.sender === "sale" || m.sender === "customer" ? "chat-widget-msg--user" : ""}`}
                        >
                          <MessageContent content={m.content} />
                        </div>
                        {showQuickReplies && (
                          <div className="chat-quick-replies">
                            {m.quick_replies?.map((option) => (
                              <button
                                key={option}
                                type="button"
                                className="chat-quick-reply"
                                disabled={loading}
                                onClick={() => sendMessage(option)}
                              >
                                {option}
                              </button>
                            ))}
                          </div>
                        )}
                        {showSuggestedQuestions && (
                          <div className="chat-suggested-questions">
                            {m.suggested_questions?.map((question) => (
                              <button
                                key={question}
                                type="button"
                                className="chat-suggested-question"
                                disabled={loading}
                                onClick={() => sendMessage(question)}
                              >
                                {question}
                              </button>
                            ))}
                          </div>
                        )}
                      </div>
                    );
                  })}
                  {loading && (
                    <div className="chat-widget-msg">
                      <LoaderIcon size={14} className="icon-spin" />
                    </div>
                  )}
                </div>
              )}

              <form className="chat-widget-input" onSubmit={handleSubmit}>
                <input
                  type="text"
                  placeholder="Đặt câu hỏi cho Auremont AI..."
                  value={input}
                  onChange={(e) => setInput(e.target.value)}
                  onKeyDown={handleKeyDown}
                  disabled={loading}
                />
                <button type="submit" disabled={!input.trim() || loading} aria-label="Gửi">
                  <SendIcon size={15} />
                </button>
              </form>

              <Link to={fullChatHref} className="chat-widget-fulllink">
                Mở trợ lý đầy đủ
                <ArrowRightIcon size={13} />
              </Link>
            </>
          )}
        </div>
      )}

      <button
        className={`chat-widget-fab ${open ? "chat-widget-fab--open" : ""}`}
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-label={open ? "Đóng trợ lý AI" : "Mở trợ lý AI"}
      >
        {open ? <XIcon size={22} /> : <AuremontAvatar size={68} emotion="greeting" variant="face" />}
      </button>

      {gate && (
        <RegisterGateModal
          gate={gate}
          sessionId={sessionId}
          visitorToken={visitor?.visitorToken ?? null}
          onClose={() => setGate(null)}
          onAuthenticated={handleAuthenticated}
        />
      )}
    </div>
  );
}
